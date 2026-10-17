"""Stage 1.3 — build inverted index.

Reads:  data/animals.jsonl
Writes: data/index/index.json
  {"stem": bool, "N": int, "doc_lengths": {slug: int},
   "postings": {term: {slug: tf}},          # the inverted index (searchable)
   "docs": {slug: {name, order, family, status}}}  # stored fields (shown in results)
"""

import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path

from index.tokenizer import tokenize
from parser import Animal

log = logging.getLogger(__name__)

INPUT_FILE = Path("data/animals.jsonl")
INDEX_DIR = Path("data/index")


def index_path(use_stem: bool) -> Path:
    return INDEX_DIR / ("index_stem.json" if use_stem else "index.json")


def document_text(a: Animal) -> str:
    """Everything we want searchable: names, tags, full text."""
    parts = [
        a.scientific_name,
        a.common_name or "",
        *a.range,
        *a.habitat,
        *a.diet,
        a.text,
    ]
    return " ".join(parts)


def build(use_stem: bool = False) -> dict:
    postings: dict[str, dict[str, int]] = defaultdict(dict)
    doc_lengths: dict[str, int] = {}
    docs: dict[str, dict[str, str | None]] = {}

    with INPUT_FILE.open(encoding="utf-8") as f:
        for line in f:
            animal = Animal.model_validate_json(line)
            tokens = tokenize(document_text(animal), use_stem)
            doc_lengths[animal.slug] = len(tokens)
            for term, tf in Counter(tokens).items():
                postings[term][animal.slug] = tf
            docs[animal.slug] = {
                "name": animal.common_name,
                "order": animal.taxonomy.get("Order"),
                "family": animal.taxonomy.get("Family"),
                "status": animal.conservation_status,
            }

    return {
        "stem": use_stem,
        "N": len(doc_lengths),
        "doc_lengths": doc_lengths,
        "postings": postings,
        "docs": docs,
    }


def main(use_stem: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    start = time.time()
    index = build(use_stem)
    log.info(
        "built in %.1fs: N=%d, vocab=%d, tokens=%d, stem=%s",
        time.time() - start,
        index["N"],
        len(index["postings"]),
        sum(index["doc_lengths"].values()),
        use_stem,
    )

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path = index_path(use_stem)
    path.write_text(json.dumps(index), encoding="utf-8")
    log.info(
        "saved %s (%.1f MB) in %.1fs total",
        path,
        path.stat().st_size / 1e6,
        time.time() - start,
    )


if __name__ == "__main__":
    main()
