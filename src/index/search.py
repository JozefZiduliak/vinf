"""Stage 1.4 — query parsing + TF-IDF ranking over data/index/.

score(d) = sum over query terms t of  tf_weight(tf(t,d)) / len(d) * idf(t)
Two IDF variants (assignment requirement):
  classic: log(N / df)                      Manning IIR 6.2.1
  bm25:    log((N - df + 0.5) / (df + 0.5)) Manning IIR 11.4.3, probabilistic
Two TF weightings (our experiment):
  raw: tf                                   linear, rewards repetition
  log: 1 + log(tf)                          sublinear, Manning IIR 6.4.1
Stemmed and unstemmed indexes are separate files; --stem picks which one to load.
"""

import json
import math
from collections import defaultdict
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from index.builder import index_path
from index.tokenizer import tokenize
from parser import Animal

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
TF = {"raw": lambda tf: tf, "log": lambda tf: 1 + math.log(tf)}


@cache
def load_index(use_stem: bool = False) -> dict:
    """Read once per process; every search() call reuses it."""
    return json.loads(index_path(use_stem).read_text(encoding="utf-8"))


def search(
    query: str,
    top_k: int = 10,
    idf: str = "classic",
    tf_weight: str = "raw",
    use_stem: bool = False,
) -> list[SearchResult]:
    index = load_index(use_stem)
    n, postings, doc_lengths = index["N"], index["postings"], index["doc_lengths"]
    idf_fn, tf_fn = IDF[idf], TF[tf_weight]

    scores: dict[str, float] = defaultdict(float)
    matched: dict[str, list[str]] = defaultdict(list)
    for term in tokenize(query, index["stem"]):
        plist = postings.get(term)
        if not plist:
            continue
        w = idf_fn(n, len(plist))
        for doc, tf in plist.items():
            scores[doc] += tf_fn(tf) / doc_lengths[doc] * w
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
