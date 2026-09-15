"""Optional thin FastAPI wrapper over index.search."""

from fastapi import FastAPI

from index.search import search

app = FastAPI(title="vinf search")


@app.get("/search")
def search_endpoint(q: str, top_k: int = 10):
    return search(q, top_k)
