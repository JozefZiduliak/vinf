"""Stage 2: Spark jobs over the ADW HTML and the Wikipedia dump.

Run inside the spark container, never locally:
    docker compose exec spark spark-submit src/spark/<job>.py
"""
