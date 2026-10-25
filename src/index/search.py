"""Stage 1.4 — query parsing + TF-IDF ranking over data/index/.

score(d) = sum over query terms t of  tf_weight(tf(t,d)) / norm(d) * idf(t)

IDF variants (assignment: at least two; probabilistic idf does not count):
  classic: log(N / df)                      Spärck Jones 1972, Manning IIR 6.2.1
  smooth:  1 + log(N / (1 + df))            Lucene classic TFIDFSimilarity; never 0
  unary:   1                                no idf at all, pure TF baseline
  bm25:    log((N - df + 0.5) / (df + 0.5)) Manning IIR 11.4.3, probabilistic, extra
TF weightings:
  raw: tf                               linear, rewards repetition
  log: 1 + log(tf)                      logarithmic, Manning IIR 6.4.1
Document length normalizations (what the TF weight is divided by):
  none:   1                             long documents win
  len:    number of tokens in d
  cosine: Euclidean length of the tf vector of d, Manning IIR 6.3.1
  pivot:  (1 - b) + b * len(d) / avg_len, b = 0.75, Singhal 1996
Stemmed and unstemmed indexes are separate directories; --stem picks which one.
"""

import math
from collections import defaultdict
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from index import storage
from index.tokenizer import tokenize
from parser import Animal

ANIMALS_FILE = Path("data/animals.jsonl")
PIVOT_B = 0.75


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


def idf_smooth(n: int, df: int) -> float:
    return 1 + math.log(n / (1 + df))


def idf_unary(n: int, df: int) -> float:
    return 1.0


def idf_bm25(n: int, df: int) -> float:
    return math.log((n - df + 0.5) / (df + 0.5))


IDF = {
    "classic": idf_classic,
    "smooth": idf_smooth,
    "unary": idf_unary,
    "bm25": idf_bm25,
}
TF = {"raw": lambda tf: tf, "log": lambda tf: 1 + math.log(tf)}


def norm_none(index: dict, doc: int, tf_weight: str) -> float:
    return 1.0


def norm_len(index: dict, doc: int, tf_weight: str) -> float:
    return index["doc_lengths"][doc]


def norm_cosine(index: dict, doc: int, tf_weight: str) -> float:
    return index["doc_norms"][tf_weight][doc]


def norm_pivot(index: dict, doc: int, tf_weight: str) -> float:
    return (1 - PIVOT_B) + PIVOT_B * index["doc_lengths"][doc] / index["avg_len"]


NORM = {"none": norm_none, "len": norm_len, "cosine": norm_cosine, "pivot": norm_pivot}


@cache
def load_index(use_stem: bool = False) -> dict:
    index = storage.load_index(storage.index_dir(use_stem))
    index["stem"] = use_stem
    return index


def search(
    query: str,
    top_k: int = 10,
    idf: str = "classic",
    tf_weight: str = "raw",
    norm: str = "len",
    use_stem: bool = False,
) -> list[SearchResult]:
    index = load_index(use_stem)
    n = index["N"]
    idf_fn, tf_fn, norm_fn = IDF[idf], TF[tf_weight], NORM[norm]

    scores: dict[int, float] = defaultdict(float)
    matched: dict[int, list[str]] = defaultdict(list)
    # one open file per query; each term is one seek + one read of its postings
    with index["postings_path"].open("rb") as f:
        for term in tokenize(query, index["stem"]):
            plist = storage.read_postings(f, index["terms"], term)
            if not plist:
                continue
            w = idf_fn(n, len(plist))
            for doc, tf in plist:
                scores[doc] += tf_fn(tf) / norm_fn(index, doc, tf_weight) * w
                matched[doc].append(term)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        SearchResult(
            doc_id=index["slugs"][d], score=s, matched=matched[d], **index["docs"][d]
        )
        for d, s in ranked
    ]


def show(slug: str) -> Animal | None:
    """Full record for one document, read from the parser output."""
    with ANIMALS_FILE.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith(f'{{"slug":"{slug}"'):
                return Animal.model_validate_json(line)
    return None
