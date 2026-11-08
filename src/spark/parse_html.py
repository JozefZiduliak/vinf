import sys
import time

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from src import parser as p
from src.spark.session import get_spark

RAW_GLOB = "data/raw/*.html"
OUTPUT = "data/spark/animals.parquet"
JSONL = "data/animals.jsonl"  # Stage-1 output, used only to verify the Spark result

# Python patterns compiled with re.DOTALL need the (?s) prefix in Java
IUCN_RE = "(?s)" + p.IUCN_RE.pattern
SECTION_RE = "(?s)" + p.SECTION_RE.pattern
NESTED_UL_RE = "(?s)" + p.NESTED_UL_RE.pattern
BUTTON_RE = "(?s)" + p.BUTTON_RE.pattern

HTML_ENTITIES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&nbsp;": " ",
}


def tag_block_re(header: str) -> str:
    """The <li class="keywords-header">HEADER</li> block, same shape as parser.TAG_BLOCK_RE."""
    return (
        r'(?s)<li class="keywords-header">\s*'
        + header
        + r'\s*</li>(.*?)(?=<li class="keywords-header">|</section>)'
    )


def tags(html: Column, header: str) -> Column:
    """Array of tag names under one keywords header (parser.extract_tags for one key)."""
    block = F.regexp_extract(html, tag_block_re(header), 1)
    block = F.regexp_replace(block, NESTED_UL_RE, "")
    return F.regexp_extract_all(block, F.lit(p.TAG_ITEM_RE.pattern), 1)


def clean(fragment: Column) -> Column:
    """parser.clean(): drop <button>s, strip tags, decode entities, collapse whitespace."""
    col = F.regexp_replace(fragment, BUTTON_RE, " ")
    col = F.regexp_replace(col, p.HTML_TAG_RE.pattern, " ")
    for entity, char in HTML_ENTITIES.items():
        col = F.regexp_replace(col, entity, char)
    return F.trim(F.regexp_replace(col, p.WHITESPACE_RE.pattern, " "))


def parse(pages: DataFrame) -> DataFrame:

    html = F.col("html")
    section_ids = F.regexp_extract_all(html, F.lit(SECTION_RE), 1)
    section_bodies = F.regexp_extract_all(html, F.lit(SECTION_RE), 2)
    sections = F.filter(
        F.arrays_zip(section_ids.alias("id"), section_bodies.alias("body")),
        lambda s: ~s["id"].isin(*p.SKIP_SECTIONS),
    )
    sections = F.transform(
        sections,
        lambda s: F.struct(s["id"].alias("id"), clean(s["body"]).alias("body")),
    )

    slug = F.regexp_extract(F.col("path"), r"([^/]+)\.html$", 1)
    return pages.select(
        slug.alias("slug"),
        F.coalesce(
            F.nullif(
                F.regexp_extract(html, p.SCIENTIFIC_NAME_RE.pattern, 1), F.lit("")
            ),
            F.regexp_replace(slug, "_", " "),
        ).alias("scientific_name"),
        F.nullif(
            F.regexp_extract(html, p.VERNACULAR_NAME_RE.pattern, 1), F.lit("")
        ).alias("common_name"),
        F.map_from_arrays(
            F.regexp_extract_all(html, F.lit(p.TAXONOMY_RE.pattern), 1),
            F.regexp_extract_all(html, F.lit(p.TAXONOMY_RE.pattern), 2),
        ).alias("taxonomy"),
        F.nullif(F.regexp_extract(html, IUCN_RE, 1), F.lit("")).alias(
            "conservation_status"
        ),
        tags(html, "Biogeographic Regions").alias("range"),
        F.concat(tags(html, "Habitat Regions"), tags(html, "Terrestrial Biomes")).alias(
            "habitat"
        ),
        tags(html, "Primary Diet").alias("diet"),
        F.map_from_entries(sections).alias("sections"),
        F.concat_ws(" ", F.transform(sections, lambda s: s["body"])).alias("text"),
    )


def verify(spark, animals: DataFrame) -> None:
    """Compare the Spark result with the Stage-1 JSONL on the fields the join and report use."""
    stage1 = spark.read.json(JSONL).select(
        "slug",
        F.col("scientific_name").alias("s1_name"),
        F.col("conservation_status").alias("s1_status"),
        F.col("taxonomy.Order").alias("s1_order"),
        F.col("diet").alias("s1_diet"),
    )
    animals = animals.withColumn("order", F.col("taxonomy")["Order"])
    both = animals.join(stage1, "slug", "inner")
    print(
        "spark rows:",
        animals.count(),
        "stage-1 rows:",
        stage1.count(),
        "joined on slug:",
        both.count(),
    )
    for spark_col, s1_col in [
        ("scientific_name", "s1_name"),
        ("conservation_status", "s1_status"),
        ("order", "s1_order"),
        ("diet", "s1_diet"),
    ]:
        mismatches = both.filter(~F.col(spark_col).eqNullSafe(F.col(s1_col)))
        n = mismatches.count()
        print(f"mismatch {spark_col:20s} {n}")
        if n:
            mismatches.select("slug", spark_col, s1_col).show(5, truncate=60)


if __name__ == "__main__":
    raw_glob = sys.argv[1] if len(sys.argv) > 1 else RAW_GLOB
    spark = get_spark("parse-html")
    start = time.time()

    pages = spark.read.text(raw_glob, wholetext=True).select(
        F.input_file_name().alias("path"), F.col("value").alias("html")
    )
    animals = parse(pages)
    animals.write.mode("overwrite").parquet(OUTPUT)
    print(f"parsed {raw_glob} -> {OUTPUT} in {time.time() - start:.1f}s")

    verify(spark, spark.read.parquet(OUTPUT))
    spark.stop()
