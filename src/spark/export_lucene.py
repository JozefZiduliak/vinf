from pyspark.sql import functions as F

from src.spark.join import ADW_STATUS_CODE, WIKI_COLS
from src.spark.session import get_spark

ANIMALS = "data/animals.jsonl"
JOINED = "data/wiki/joined.parquet"
OUTPUT = "data/lucene/input.json"

if __name__ == "__main__":
    spark = get_spark("export-lucene")

    animals = spark.read.json(ANIMALS)
    wiki = spark.read.parquet(JOINED).select("slug", *WIKI_COLS, "match")

    # left: every ADW animal stays, 59 without a wiki page get null wiki fields
    out = animals.join(wiki, "slug", "left")

    # one IUCN code per animal: wiki value is newer, ADW fills the gaps
    adw_code = F.create_map(*[F.lit(x) for kv in ADW_STATUS_CODE.items() for x in kv])
    out = out.withColumn(
        "status",
        F.coalesce(F.nullif("wiki_status", F.lit("")), adw_code["conservation_status"]),
    )

    # one part file, nulls written explicitly so the Lucene builder sees every key
    out.coalesce(1).write.mode("overwrite").option("ignoreNullFields", False).json(
        OUTPUT
    )

    out = spark.read.json(OUTPUT)
    print("rows:", out.count())
    print("with wiki page:", out.filter(F.col("wiki_title").isNotNull()).count())
    out.select("slug", "common_name", "wiki_status", "authority", "match").show(
        5, truncate=30
    )
    spark.stop()
