import sys

from pyspark.sql import functions as F

from src.spark.session import get_spark

DEV_PATH = "data/wiki/dump/enwiki-20261001-pages-articles1.xml-p1p41242.bz2"


def field_re(name: str) -> str:
    """Value of an infobox line '| <name> = ...', up to the first <, {, | or end of line."""
    return rf"(?m)^\s*\|\s*{name}\s*=\s*([^<{{|\n]+)"


# (?i): template names are case-insensitive on Wikipedia, {{speciesbox}} is common
TAXOBOX_RE = r"(?i)\{\{\s*(Speciesbox|Taxobox|Automatic taxobox|Subspeciesbox)"
TAXON_RE = field_re("taxon")
BINOMIAL_RE = field_re("binomial")  # old {{Taxobox}} pages
TRINOMIAL_RE = field_re("trinomial")  # old {{Taxobox}} subspecies pages
GENUS_RE = field_re("genus")
SPECIES_FIELD_RE = field_re("species")
SUBSPECIES_RE = field_re(
    "subspecies"
)  # {{Subspeciesbox}}: genus + species + subspecies
ABBREVIATED_GENUS_RE = r"^[A-Z][a-z]?\.\s*"  # "P. leo" -> "leo"
STATUS_RE = field_re("status")
STATUS_SYSTEM_RE = field_re("status_system")
AUTHORITY_RE = r"(?m)^\s*\|\s*authority\s*=\s*(.*)$"
LEAD_RE = (
    r"(?m)^([A-Za-z][^\n]*'''[^\n]*)$"  # first prose line with bold = lead sentence
)

# wikitext cleanup, applied with regexp_replace (Java syntax: group reference is $1)
REF_RE = r"<ref[^>]*/>|<ref[^>]*>.*?</ref>"
PIPED_LINK_RE = r"\[\[[^\]|]*\|([^\]]*)\]\]"  # [[target|label]] -> label
PLAIN_LINK_RE = r"\[\[([^\]]*)\]\]"  # [[target]] -> target
TEMPLATE_RE = r"\{\{[^{}]*\}\}"  # {{...}} without nesting
QUOTES_RE = r"'{2,}"  # '' and ''' markup


def clean_name(col):
    """Scientific name fields: ''[[Panthera]]'' -> Panthera, '''''P. leo''''' -> P. leo."""
    col = F.regexp_replace(col, PIPED_LINK_RE, "$1")
    col = F.regexp_replace(col, PLAIN_LINK_RE, "$1")
    col = F.regexp_replace(col, QUOTES_RE, "")
    col = F.regexp_replace(col, r"\s*\([^)]*\)", "")  # "Donax (bivalve)" -> "Donax"
    return F.trim(col)


def clean_wikitext(col):
    col = F.regexp_replace(col, REF_RE, "")
    col = F.regexp_replace(col, TEMPLATE_RE, "")
    col = F.regexp_replace(col, PIPED_LINK_RE, "$1")
    col = F.regexp_replace(col, PLAIN_LINK_RE, "$1")
    col = F.regexp_replace(col, QUOTES_RE, "")
    col = F.regexp_replace(
        col, r"\(\s*[;,]\s*", "("
    )  # "(; Orycteropus afer)" after a dropped {{IPAc-en}}
    return F.trim(col)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEV_PATH
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
        species.withColumn("taxon", clean_name(F.regexp_extract("text", TAXON_RE, 1)))
        .withColumn("binomial", clean_name(F.regexp_extract("text", BINOMIAL_RE, 1)))
        .withColumn("trinomial", clean_name(F.regexp_extract("text", TRINOMIAL_RE, 1)))
        .withColumn("genus", clean_name(F.regexp_extract("text", GENUS_RE, 1)))
        .withColumn(
            "subspecies", clean_name(F.regexp_extract("text", SUBSPECIES_RE, 1))
        )
        .withColumn(
            "species_epithet",
            F.regexp_replace(
                clean_name(F.regexp_extract("text", SPECIES_FIELD_RE, 1)),
                ABBREVIATED_GENUS_RE,
                "",
            ),
        )
        .withColumn("status", F.trim(F.regexp_extract("text", STATUS_RE, 1)))
        .withColumn(
            "status_system", F.trim(F.regexp_extract("text", STATUS_SYSTEM_RE, 1))
        )
    )

    # subspecies pages need the three-word name, otherwise "Caucasian moose" and
    # "Moose" both become "Alces alces" and the join cannot tell them apart
    species = species.withColumn(
        "taxon",
        F.when(F.col("taxon") != "", F.col("taxon"))
        .when(F.col("trinomial") != "", F.col("trinomial"))
        .when(F.col("binomial") != "", F.col("binomial"))
        # concat_ws skips NULL but not "", so trim the trailing space when
        # species or subspecies is empty ("Ursus arctos " -> "Ursus arctos")
        .otherwise(F.trim(F.concat_ws(" ", "genus", "species_epithet", "subspecies"))),
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
    print(
        "binomial:",
        species.filter(F.col("taxon").rlike(r"^[A-Z][a-z]+ [a-z]+$")).count(),
    )
    species.filter(F.col("title") == "Lion").show(vertical=True, truncate=120)

    spark.stop()
