"""Corpus statistics for the report (Submission 1, section 13).

Reads data/raw/ (size on disk), data/animals.jsonl (text, attributes).
Prints a table: documents, bytes, words, IR tokens, tiktoken tokens, attribute coverage.
"""

import statistics
from collections import Counter
from pathlib import Path

import tiktoken

from index.tokenizer import tokenize
from parser import Animal

RAW_DIR = Path("data/raw")
ANIMALS_FILE = Path("data/animals.jsonl")
ATTRIBUTES = (
    "common_name",
    "taxonomy",
    "conservation_status",
    "range",
    "habitat",
    "diet",
)


def main() -> None:
    enc = tiktoken.get_encoding("o200k_base")  # GPT-4o tokenizer
    words: list[int] = []
    ir_tokens: list[int] = []
    llm_tokens: list[int] = []
    coverage: Counter[str] = Counter()

    with ANIMALS_FILE.open(encoding="utf-8") as f:
        for line in f:
            a = Animal.model_validate_json(line)
            words.append(len(a.text.split()))
            ir_tokens.append(len(tokenize(a.text)))
            llm_tokens.append(len(enc.encode(a.text)))
            coverage.update(attr for attr in ATTRIBUTES if getattr(a, attr))

    n = len(words)
    html_bytes = sum(p.stat().st_size for p in RAW_DIR.glob("*.html"))
    text_bytes = sum(
        len(a.encode()) for a in [ANIMALS_FILE.read_text(encoding="utf-8")]
    )

    print(f"{'documents (species accounts)':34s} {n:>12,}")
    print(f"{'raw HTML on disk':34s} {html_bytes / 1e6:>10.1f} MB")
    print(f"{'parsed JSONL on disk':34s} {text_bytes / 1e6:>10.1f} MB")
    for label, xs in (
        ("words", words),
        ("IR tokens (no stop-words)", ir_tokens),
        ("tiktoken o200k tokens", llm_tokens),
    ):
        print(
            f"{label:34s} {sum(xs):>12,}   median/doc {int(statistics.median(xs)):>6,}"
        )
    print()
    for attr in ATTRIBUTES:
        print(
            f"{'has ' + attr:34s} {coverage[attr]:>12,}   {100 * coverage[attr] / n:5.1f}%"
        )


if __name__ == "__main__":
    main()
