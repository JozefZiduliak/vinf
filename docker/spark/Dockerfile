FROM apache/spark:4.2.1-python3

# src/parser.py (Stage 1) imports pydantic for the Animal model; parse_html.py
# imports its regexes from there, so the Spark container needs it too.
USER root
RUN pip install --no-cache-dir pydantic==2.11.7
USER spark
