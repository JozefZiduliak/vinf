from pyspark.sql import functions as F
from src.spark.session import get_spark


def field_re(name: str) -> str:
    """Value of an infobox line '| <name> = ...', up to the first <, {, | or end of line."""
    return rf"(?m)^\s*\|\s*{name}\s*=\s*([^<{{|\n]+)"


TAXOBOX_RE = r"\{\{\s*(Speciesbox|Taxobox|Automatic taxobox|Subspeciesbox)"
TAXON_RE = field_re("taxon")
GENUS_RE = field_re("genus")
SPECIES_FIELD_RE = field_re("species")
STATUS_RE = field_re("status")
STATUS_SYSTEM_RE = field_re("status_system")
AUTHORITY_RE = r"(?m)^\s*\|\s*authority\s*=\s*(.*)$"
LEAD_RE = r"(?m)^([A-Za-z][^\n]*'''[^\n]*)$"  # first prose line with bold = lead sentence

# wikitext cleanup, applied with regexp_replace (Java syntax: group reference is $1)
REF_RE = r"<ref[^>]*/>|<ref[^>]*>.*?</ref>"
PIPED_LINK_RE = r"\[\[[^\]|]*\|([^\]]*)\]\]"  # [[target|label]] -> label
PLAIN_LINK_RE = r"\[\[([^\]]*)\]\]"  # [[target]] -> target
TEMPLATE_RE = r"\{\{[^{}]*\}\}"  # {{...}} without nesting
QUOTES_RE = r"'{2,}"  # '' and ''' markup


def clean_wikitext(col):
    col = F.regexp_replace(col, REF_RE, "")
    col = F.regexp_replace(col, TEMPLATE_RE, "")
    col = F.regexp_replace(col, PIPED_LINK_RE, "$1")
    col = F.regexp_replace(col, PLAIN_LINK_RE, "$1")
    col = F.regexp_replace(col, QUOTES_RE, "")
    return F.trim(col)


if __name__ == "__main__":
    path = "data/wiki/dump/enwiki-20261001-pages-articles1.xml-p1p41242.bz2"
    spark = get_spark("vinf-project")

    pages = spark.read.format("xml").option("rowTag", "page").load(path)

    articles = pages.filter(F.col("ns") == 0).select(
        F.col("title"),
        F.col("redirect._title").alias("redirect_to"),
        F.col("revision.text._VALUE").alias("text"),
    )

    redirects = articles.filter(F.col("redirect_to").isNotNull()).select(
        "title", F.col("redirect_to").alias("target")
    )

    species = articles.filter(
        F.col("redirect_to").isNull() & F.col("text").rlike(TAXOBOX_RE)
    )

    species = (
        species.withColumn("taxon", F.trim(F.regexp_extract("text", TAXON_RE, 1)))
        .withColumn("genus", F.trim(F.regexp_extract("text", GENUS_RE, 1)))
        .withColumn(
            "species_epithet", F.trim(F.regexp_extract("text", SPECIES_FIELD_RE, 1))
        )
        .withColumn("status", F.trim(F.regexp_extract("text", STATUS_RE, 1)))
        .withColumn(
            "status_system", F.trim(F.regexp_extract("text", STATUS_SYSTEM_RE, 1))
        )
    )

    # Speciesbox gives the name either as `taxon` or as `genus` + `species`
    species = species.withColumn(
        "taxon",
        F.when(F.col("taxon") == "", F.concat_ws(" ", "genus", "species_epithet"))
        .otherwise(F.col("taxon")),
    )

    species = species.withColumn(
        "authority", clean_wikitext(F.regexp_extract("text", AUTHORITY_RE, 1))
    ).withColumn("lead", clean_wikitext(F.regexp_extract("text", LEAD_RE, 1)))

    redirects.write.mode("overwrite").parquet("data/wiki/redirects.parquet")
    species.select(
        "title", "taxon", "status", "status_system", "authority", "lead"
    ).write.mode("overwrite").parquet("data/wiki/species.parquet")

    # stats from the written parquet: fast, no second pass over the dump
    redirects = spark.read.parquet("data/wiki/redirects.parquet")
    species = spark.read.parquet("data/wiki/species.parquet")
    print("redirects:", redirects.count(), "species:", species.count())
    print("empty taxon:", species.filter(F.col("taxon") == "").count())
    print("binomial:", species.filter(F.col("taxon").rlike(r"^[A-Z][a-z]+ [a-z]+$")).count())
    species.filter(F.col("title") == "Lion").show(vertical=True, truncate=120)

    spark.stop()