"""Stage 1.4 — query parsing + TF-IDF/BM25 ranking over data/index/."""

from pydantic import BaseModel


class SearchResult(BaseModel):
    doc_id: str
    score: float


def load_index(index_dir: str = "data/index"):
    raise NotImplementedError


def search(query: str, top_k: int = 10) -> list[SearchResult]:
    raise NotImplementedError
