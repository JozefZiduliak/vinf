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

Tokenizes the text, drops English stop words and writes an inverted index to `data/index/plain/` as three files:

| file | contents |
|---|---|
| `docs.tsv` | one row per document: id, slug, length, two vector norms, common name, order, family, IUCN status |
| `terms.tsv` | dictionary: term, document frequency, byte offset into the postings file |
| `postings.bin` | postings, 6 bytes each (`uint32` document id, `uint16` term frequency), grouped by term |

The dictionary and document table are loaded into memory; postings stay on disk and a query reads only the slices for its own terms. The second command builds a separate index with naive suffix stripping into `data/index/stem/`, so the two can be compared without rebuilding. A build takes about 1.5 s.

### 4. Search

```sh
uv run dev search "lions in africa"
```

Prints the top 10 results with score, slug, common name, order/family, conservation status and which query terms each document matched. Score of a document is the sum over query terms of `tf_weight(tf) / norm(doc) * idf(term)`. Four flags pick the pieces, defaults in bold.

| flag | values | meaning |
|---|---|---|
| `--idf` | **`classic`**, `smooth`, `unary`, `bm25` | `log(N/df)`; `1 + log(N/(1+df))`, never zero; `1`, no IDF at all; `log((N-df+0.5)/(df+0.5))`, negative for very common terms |
| `--tf` | **`raw`**, `log` | term frequency as is, or `1 + log(tf)` |
| `--norm` | `none`, **`len`**, `cosine`, `pivot` | no length normalization; divide by document length; divide by vector length; pivoted length, `0.25 + 0.75 * len / avg_len` |
| `--stem` | | query the stemmed index |
| `--top-k` | **10** | number of results |

One command per knob:

```sh
uv run dev search "native carnivore" --idf classic --top-k 5
uv run dev search "native carnivore" --idf smooth --top-k 5
```

Under classic IDF the term `native` (in 4,094 of 4,239 documents) weighs almost nothing, so only documents with `carnivore` rank; under smooth IDF it still counts and the top result matches `native` alone.

```sh
uv run dev search "hibernates during winter" --norm len --top-k 5
uv run dev search "hibernates during winter" --norm cosine --top-k 5
uv run dev search "hibernates during winter" --norm none --top-k 5
```

Without normalization long documents win; `len` favours short ones most; `cosine` sits in between.

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

Prints the full parsed record for one document, attributes first, then every text section. The full text lives only in `data/animals.jsonl`; the index stores just the four fields shown in the result line.

## Extras

```sh
uv run dev stats
```

Corpus statistics for the report: document count, size on disk, word and token counts (including tiktoken), attribute coverage.

```sh
uv run pytest
```

137 tests in three files: `test_parser.py` runs the regex extractors against 20 crawled pages (hand-checked values for 6 species, structural checks on all 20); `test_search.py` checks the IDF, TF and normalization formulas against hand-computed numbers; `test_store.py` writes a toy index and reads it back. The parser tests need `data/raw/` and skip themselves when it is missing.

## Layout

```
src/
  crawler.py        BFS crawler with checkpoint and metadata TSV
  parser.py         regex extraction into the Animal model
  index/
    tokenizer.py    shared tokenization for documents and queries
    builder.py      inverted index
    storage.py      index files on disk: docs.tsv, terms.tsv, postings.bin
    search.py       TF-IDF ranking: 4 IDF variants, 2 TF weights, 4 length norms
  stats.py          corpus statistics
  cli.py            the `dev` entry point
tests/
  test_parser.py    extractor tests on crawled pages
  test_search.py    scoring formulas
  test_store.py     index round trip
docs/               crawler and pipeline diagrams
```
