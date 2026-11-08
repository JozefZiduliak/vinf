from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from src.spark.session import get_spark

ANIMALS = "data/animals.jsonl"
SPECIES = "data/wiki/species.parquet"
REDIRECTS = "data/wiki/redirects.parquet"
OUTPUT = "data/wiki/joined.parquet"

# ADW spells the IUCN category out, Wikipedia uses the code
ADW_STATUS_CODE = {
    "Least Concern": "LC",
    "Near Threatened": "NT",
    "Vulnerable": "VU",
    "Endangered": "EN",
    "Critically Endangered": "CR",
    "Extinct in the Wild": "EW",
    "Extinct": "EX",
    "Data Deficient": "DD",
    "Not Evaluated": "NE",
}

WIKI_COLS = ["wiki_title", "taxon", "wiki_status", "status_system", "authority", "lead"]


def norm(col) -> Column:
    """Join key: lower-cased, trimmed, without disambiguators ("Donax (bivalve) variabilis")."""
    return F.lower(F.trim(F.regexp_replace(col, r"\s*\([^)]*\)", "")))


def load_animals(spark) -> DataFrame:
    status_code = F.create_map(
        *[F.lit(x) for kv in ADW_STATUS_CODE.items() for x in kv]
    )
    return spark.read.json(ANIMALS).select(
        "slug",
        "scientific_name",
        "common_name",
        F.col("conservation_status").alias("adw_status"),
        status_code[F.col("conservation_status")].alias("adw_status_code"),
        norm("scientific_name").alias("key"),
    )


def load_species(spark) -> DataFrame:
    species = spark.read.parquet(SPECIES).select(
        F.col("title").alias("wiki_title"),
        "taxon",
        F.col("status").alias("wiki_status"),
        "status_system",
        "authority",
        "lead",
    )
    return species.withColumn("key", norm("taxon"))


def one_page_per_name(species: DataFrame) -> DataFrame:
    preference = Window.partitionBy("key").orderBy(
        F.when(norm(F.col("wiki_title")) == F.col("key"), 0).otherwise(1),
        F.length("wiki_title"),
        F.col("wiki_title"),
    )
    return (
        species.withColumn("rank", F.row_number().over(preference))
        .filter(F.col("rank") == 1)
        .drop("rank")
    )


def join_direct(animals: DataFrame, species: DataFrame) -> DataFrame:
    # the redirect stage joins by title, so it must see the full species table
    return animals.join(one_page_per_name(species), "key", "inner").withColumn(
        "match", F.lit("direct")
    )


def join_via_redirect(
    animals: DataFrame, species: DataFrame, redirects: DataFrame
) -> DataFrame:
    redirects = redirects.select(
        norm("title").alias("key"), F.col("target").alias("wiki_title")
    )
    by_title = species.drop("key")
    return (
        animals.join(redirects, "key", "inner")
        .join(by_title, "wiki_title", "inner")
        .withColumn("match", F.lit("redirect"))
    )


def join_all(animals: DataFrame, species: DataFrame, redirects: DataFrame) -> DataFrame:
    direct = join_direct(animals, species)
    rest = animals.join(direct.select("slug"), "slug", "left_anti")
    via = join_via_redirect(rest, species, redirects)
    cols = [
        "slug",
        "scientific_name",
        "common_name",
        "adw_status",
        "adw_status_code",
        *WIKI_COLS,
        "match",
    ]
    return direct.select(cols).unionByName(via.select(cols)).dropDuplicates(["slug"])


def report(animals: DataFrame, joined: DataFrame) -> None:
    n = animals.count()
    matched = joined.count()
    print(f"ADW species: {n}")
    print(f"matched: {matched} ({100 * matched / n:.1f}%)")
    joined.groupBy("match").count().show()
    print("unique wiki pages joined:", joined.select("wiki_title").distinct().count())

    print("wiki attribute coverage among matched:")
    for col in ("wiki_status", "authority", "lead"):
        k = joined.filter(F.col(col) != "").count()
        print(f"  {col:14s} {k:5d} ({100 * k / max(matched, 1):.1f}%)")

    comparable = joined.filter(
        (F.col("wiki_status") != "") & F.col("adw_status_code").isNotNull()
    )
    agree = comparable.filter(F.col("wiki_status") == F.col("adw_status_code")).count()
    print(f"IUCN status: {comparable.count()} comparable, {agree} agree")
    comparable.filter(F.col("wiki_status") != F.col("adw_status_code")).select(
        "scientific_name", "adw_status", "wiki_status"
    ).show(10, truncate=False)

    unmatched = animals.join(joined.select("slug"), "slug", "left_anti")
    print("unmatched:", unmatched.count())
    unmatched.select("scientific_name", "common_name").show(20, truncate=False)


if __name__ == "__main__":
    spark = get_spark("join")
    animals = load_animals(spark)
    species = load_species(spark)
    redirects = spark.read.parquet(REDIRECTS)

    joined = join_all(animals, species, redirects)
    joined.write.mode("overwrite").parquet(OUTPUT)

    report(animals, spark.read.parquet(OUTPUT))
    spark.stop()
