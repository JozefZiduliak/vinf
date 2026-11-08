"""SparkSession factory shared by all Stage-2 jobs.

Run inside the spark container:
    docker compose exec spark spark-submit src/spark/session.py
"""

from pyspark.sql import SparkSession

SHUFFLE_PARTITIONS = "16"


def get_spark(app_name: str) -> SparkSession:
    """Return the shared local SparkSession (memory is set via spark-submit --driver-memory)."""
    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", SHUFFLE_PARTITIONS)
        .getOrCreate()
    )


if __name__ == "__main__":
    spark = get_spark("smoke-test")
    animals = spark.read.json("data/animals.jsonl")
    animals.printSchema()
    print("animals:", animals.count())
    spark.stop()
