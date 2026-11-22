# pyright: reportMissingImports=false  (PyLucene exists only inside the container)
"""Build the Lucene index from the Spark export. Runs inside the lucene container:

docker compose exec lucene python3 src/lucene/build_index.py
"""

import glob
import json
import re

import lucene
from java.nio.file import Paths
from org.apache.lucene.analysis.en import EnglishAnalyzer
from org.apache.lucene.document import (
    Document,
    Field,
    IntPoint,
    StoredField,
    StringField,
    TextField,
)
from org.apache.lucene.index import IndexWriter, IndexWriterConfig
from org.apache.lucene.store import FSDirectory

INPUT = "data/lucene/input.json/part-*.json"
INDEX = "data/lucene/index"

# "(Linnaeus, 1758)" -> 1758; species descriptions start with Linnaeus in 1758
YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


KEYWORDS = ["slug", "scientific_name", "status"]
RANKS = ["Class", "Order", "Family", "Genus"]  # taxonomy dict keys
LISTS = ["range", "habitat", "diet"]  # one StringField per value
# TextField: analyzed, searched by word, scored
TEXTS = ["scientific_name_text", "common_name", "wiki_title", "authority", "lead", "text"]
NOT_STORED = {"text"}  # searchable but not returned, it is 60 MB


def to_document(row: dict) -> Document:
    doc = Document()
    row["scientific_name_text"] = row["scientific_name"]
    for name in KEYWORDS:
        if row.get(name):
            doc.add(StringField(name, row[name], Field.Store.YES))
    for rank in RANKS:
        if row["taxonomy"].get(rank):
            doc.add(StringField(rank.lower(), row["taxonomy"][rank], Field.Store.YES))
    for name in LISTS:
        for value in row[name] or []:
            doc.add(StringField(name, value, Field.Store.YES))
    for name in TEXTS:
        if row.get(name):
            store = Field.Store.NO if name in NOT_STORED else Field.Store.YES
            doc.add(TextField(name, row[name], store))
    m = YEAR_RE.search(row.get("authority") or "")
    if m:
        year = int(m.group(1))
        doc.add(IntPoint("year", year))  # indexed for range queries
        doc.add(StoredField("year", year))  # returned in results
    return doc


if __name__ == "__main__":
    lucene.initVM()
    config = IndexWriterConfig(EnglishAnalyzer())
    config.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
    writer = IndexWriter(FSDirectory.open(Paths.get(INDEX)), config)

    n = 0
    for path in glob.glob(INPUT):
        with open(path, encoding="utf-8") as f:
            for line in f:
                writer.addDocument(to_document(json.loads(line)))
                n += 1
    writer.commit()
    print("indexed:", n, "docs in", INDEX)
    writer.close()
