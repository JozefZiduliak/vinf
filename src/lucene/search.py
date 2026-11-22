# pyright: reportMissingImports=false  (PyLucene exists only inside the container)
"""Query the Lucene index. Runs inside the lucene container:

docker compose exec lucene python3 src/lucene/search.py "lions in africa"
docker compose exec lucene python3 src/lucene/search.py "diet:carnivore AND status:EN"
docker compose exec lucene python3 src/lucene/search.py '"tropical rainforest"'
docker compose exec lucene python3 src/lucene/search.py "cheeta~"
docker compose exec lucene python3 src/lucene/search.py "family:Felidae" --year 1750-1800
"""

import argparse

import lucene
from java.nio.file import Paths
from java.util import HashMap
from org.apache.lucene.analysis.core import KeywordAnalyzer
from org.apache.lucene.analysis.en import EnglishAnalyzer
from org.apache.lucene.analysis.miscellaneous import PerFieldAnalyzerWrapper
from org.apache.lucene.document import IntPoint
from org.apache.lucene.index import DirectoryReader
from org.apache.lucene.queryparser.classic import QueryParser
from org.apache.lucene.search import BooleanClause, BooleanQuery, IndexSearcher
from org.apache.lucene.store import FSDirectory

INDEX = "data/lucene/index"
DEFAULT_FIELD = "text"  # "lion" alone searches the full text
# StringFields hold one exact token, the query side must not stem or lowercase them
EXACT = [
    "slug",
    "scientific_name",
    "status",
    "class",
    "order",
    "family",
    "genus",
    "range",
    "habitat",
    "diet",
]


def query_analyzer():
    """EnglishAnalyzer for text fields, KeywordAnalyzer for the exact ones."""
    per_field = HashMap()
    for name in EXACT:
        per_field.put(name, KeywordAnalyzer())
    return PerFieldAnalyzerWrapper(EnglishAnalyzer(), per_field)


def build_query(text: str, year: str | None):
    # QueryParser syntax: AND OR NOT, field:value, "phrase", fuzzy~, (grouping)
    query = QueryParser(DEFAULT_FIELD, query_analyzer()).parse(text)
    if year is None:
        return query
    lo, hi = (int(y) for y in year.split("-"))
    lo, hi = min(lo, hi), max(lo, hi)  # "1800-1750" would be an empty interval
    both = BooleanQuery.Builder()
    both.add(query, BooleanClause.Occur.MUST)
    both.add(IntPoint.newRangeQuery("year", lo, hi), BooleanClause.Occur.MUST)
    return both.build()


def search(query, top_k: int) -> list[tuple[float, dict]]:
    reader = DirectoryReader.open(FSDirectory.open(Paths.get(INDEX)))
    searcher = IndexSearcher(reader)  # BM25 by default
    stored = searcher.storedFields()
    rows = []
    for hit in searcher.search(query, top_k).scoreDocs:
        doc = stored.document(hit.doc)
        rows.append(
            (
                hit.score,
                {name: doc.get(name) for name in ("slug", "common_name", "order", "family", "status", "year")},
            )
        )
    reader.close()
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--year", help="range on the description year, e.g. 1750-1800")
    args = ap.parse_args()

    lucene.initVM()
    query = build_query(args.query, args.year)
    print("parsed:", query.toString())
    for score, d in search(query, args.top_k):
        print(
            f"{score:.4f}  {d['slug']:28s} {d['common_name'] or '-':26s} "
            f"{d['order'] or '-'}/{d['family'] or '-':14s} {d['status'] or '-':4s} {d['year'] or '-'}"
        )
