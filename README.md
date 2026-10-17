# vinf

A small search engine over [Animal Diversity Web](https://animaldiversity.org), built from scratch for the Information Retrieval course at FIIT STU. It crawls the species accounts, pulls structured attributes out of the HTML with regular expressions, builds its own inverted index and ranks results with TF-IDF. No search libraries are used in this stage, the point is to see how the pieces work.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) for dependencies and running

```sh
uv sync
```

This creates the virtual environment and installs `requests`, `pydantic` and `tiktoken`. All commands below go through `uv run dev <stage>`.

## Pipeline

Each stage reads the output of the previous one, so run them in order. Everything lands in `data/`, which is git-ignored.

### 1. Crawl

```sh
uv run dev crawl
```

Walks the ADW taxonomy tree from `Animalia` down to species and saves every species account as HTML into `data/raw/`. It honours `robots.txt`, which asks for an 8 second delay, so a full crawl of ~4,200 species and the taxonomy pages above them takes a bit over a day. Progress is checkpointed, so you can stop it and run the same command again to resume.

### 2. Parse

```sh
uv run dev parse
```

Turns each HTML file into one JSON record with scientific and common name, taxonomy, IUCN status, range, habitat, diet and the full text of every section. Output is `data/animals.jsonl`, one animal per line, and the log prints how many records have each attribute.

### 3. Build the index

```sh
uv run dev build-index
uv run dev build-index --stem
```

Tokenizes the text, drops English stop words and writes an inverted index (`term -> {document: frequency}`) to `data/index/`. The second command builds a separate index with naive suffix stripping, so the two can be compared without rebuilding.

### 4. Search

```sh
uv run dev search "lions in africa"
```

Prints the top 10 results with score, common name, order/family, conservation status and which query terms each document matched. Scoring is TF-IDF and the knobs below change how it is computed.

```sh
uv run dev search "native carnivore" --idf bm25
```

Swaps the classic `log(N/df)` for the BM25 variant, which gives a negative weight to terms that appear in most documents.

```sh
uv run dev search "australia parrot popular pet" --tf log --top-k 5
```

Uses `1 + log(tf)` instead of raw term frequency, so a document that repeats one query word twenty times no longer wins on that alone.

```sh
uv run dev search "lions in africa" --stem
```

Queries the stemmed index, where `lion` and `lions` are the same term.

```sh
uv run dev show Panthera_leo
```

Prints the full parsed record for one document, attributes first, then every text section.

## Extras

```sh
uv run dev stats
```

Corpus statistics for the report: document count, size on disk, word and token counts (including tiktoken), attribute coverage.

```sh
uv run pytest
```

Runs the regex extractors against 20 crawled pages and checks the extracted values. The tests need `data/raw/` and skip themselves when it is missing.

## Layout

```
src/
  crawler.py        BFS crawler with checkpoint and metadata TSV
  parser.py         regex extraction into the Animal model
  index/
    tokenizer.py    shared tokenization for documents and queries
    builder.py      inverted index
    search.py       TF-IDF ranking, two IDF variants
  stats.py          corpus statistics
  cli.py            the `dev` entry point
tests/
  test_parser.py    extractor tests
docs/               crawler diagrams
```
