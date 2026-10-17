"""Stage 1.4 — query parsing + TF-IDF ranking over data/index/.

score(d) = sum over query terms t of  (tf(t,d) / len(d)) * idf(t)
Two IDF variants (assignment requirement):
  classic: log(N / df)                      Manning IIR 6.2.1
  bm25:    log((N - df + 0.5) / (df + 0.5)) Manning IIR 11.4.3, probabilistic
"""

import json
import math
from collections import defaultdict
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from index.tokenizer import tokenize
from parser import Animal

INDEX_FILE = Path("data/index/index.json")
ANIMALS_FILE = Path("data/animals.jsonl")


class SearchResult(BaseModel):
    doc_id: str
    score: float
    matched: list[str]  # query terms found in this doc
    name: str | None = None
    order: str | None = None
    family: str | None = None
    status: str | None = None


def idf_classic(n: int, df: int) -> float:
    return math.log(n / df)


def idf_bm25(n: int, df: int) -> float:
    return math.log((n - df + 0.5) / (df + 0.5))


IDF = {"classic": idf_classic, "bm25": idf_bm25}


@cache
def load_index() -> dict:
    """Read once per process; every search() call reuses it."""
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def search(query: str, top_k: int = 10, idf: str = "classic") -> list[SearchResult]:
    index = load_index()
    n, postings, doc_lengths = index["N"], index["postings"], index["doc_lengths"]
    idf_fn = IDF[idf]

    scores: dict[str, float] = defaultdict(float)
    matched: dict[str, list[str]] = defaultdict(list)
    for term in tokenize(query, index["stem"]):
        plist = postings.get(term)
        if not plist:
            continue
        w = idf_fn(n, len(plist))
        for doc, tf in plist.items():
            scores[doc] += tf / doc_lengths[doc] * w
            matched[doc].append(term)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        SearchResult(doc_id=d, score=s, matched=matched[d], **index["docs"][d])
        for d, s in ranked
    ]


def show(slug: str) -> Animal | None:
    """Full record for one document, read from the parser output."""
    with ANIMALS_FILE.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith(f'{{"slug":"{slug}"'):
                return Animal.model_validate_json(line)
    return None
