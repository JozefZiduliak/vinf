"""Single entry point. Usage:

uv run dev crawl
uv run dev parse
uv run dev build-index
uv run dev search "lions in africa"
"""

import argparse

import crawler
import parser
from index import builder
from index.search import search


def main() -> None:
    ap = argparse.ArgumentParser(prog="vinf")
    sub = ap.add_subparsers(dest="mode", required=True)

    sub.add_parser("crawl", help="stage 1.1: crawl site to data/raw/")
    sub.add_parser("parse", help="stage 1.2: regex-extract data/animals.jsonl")
    b = sub.add_parser("build-index", help="stage 1.3: build inverted index")
    b.add_argument("--stem", action="store_true", help="apply naive suffix stripping")
    s = sub.add_parser("search", help="stage 1.4: query the index")
    s.add_argument("query")
    s.add_argument("--top-k", type=int, default=10)
    s.add_argument("--idf", choices=["classic", "bm25"], default="classic")

    args = ap.parse_args()
    match args.mode:
        case "crawl":
            crawler.main()
        case "parse":
            parser.main()
        case "build-index":
            builder.main(args.stem)
        case "search":
            for r in search(args.query, args.top_k, args.idf):
                print(f"{r.score:.4f}\t{r.doc_id}")


if __name__ == "__main__":
    main()
