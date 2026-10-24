import csv
import struct
from pathlib import Path

INDEX_DIR = Path("data/index")
POSTING = struct.Struct("<IH")
STORED = ("name", "order", "family", "status")


def index_dir(use_stem: bool) -> Path:
    return INDEX_DIR / "stem"  if use_stem else INDEX_DIR / "plain"



def write_index(index: dict, directory: Path) -> None:
    """Write the dict built by builder.build() as docs.tsv, terms.tsv, postings.bin."""
    directory.mkdir(parents=True, exist_ok=True)
    slugs = list(index["doc_lengths"])
    doc_id = {slug: i for i, slug in enumerate(slugs)}

    with (directory / "docs.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "slug", "len", "norm_raw", "norm_log", *STORED])
        for i, slug in enumerate(slugs):
            stored = index["docs"][slug]
            w.writerow(
                [
                    i,
                    slug,
                    index["doc_lengths"][slug],
                    f"{index['doc_norms']['raw'][slug]:.4f}",
                    f"{index['doc_norms']['log'][slug]:.4f}",
                    *(stored[k] or "" for k in STORED),
                ]
            )

    with (
        (directory / "terms.tsv").open("w", encoding="utf-8", newline="") as t,
        (directory / "postings.bin").open("wb") as p,
    ):
        w = csv.writer(t, delimiter="\t", lineterminator="\n")
        w.writerow(["term", "df", "offset"])
        offset = 0
        for term, plist in sorted(index["postings"].items()):
            w.writerow([term, len(plist), offset])
            for slug, tf in plist.items():
                p.write(POSTING.pack(doc_id[slug], tf))
            offset += len(plist) * POSTING.size


def load_index(directory: Path) -> dict:
    """Dictionary and per-document data into RAM; postings stay on disk."""
    with (directory / "docs.tsv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    with (directory / "terms.tsv").open(encoding="utf-8", newline="") as f:
        terms = {
            r["term"]: (int(r["df"]), int(r["offset"]))
            for r in csv.DictReader(f, delimiter="\t")
        }
    lengths = [int(r["len"]) for r in rows]
    return {
        "N": len(rows),
        "slugs": [r["slug"] for r in rows],
        "doc_lengths": lengths,
        "doc_norms": {
            "raw": [float(r["norm_raw"]) for r in rows],
            "log": [float(r["norm_log"]) for r in rows],
        },
        "docs": [{k: r[k] or None for k in STORED} for r in rows],
        "terms": terms,
        "avg_len": sum(lengths) / len(rows),
        "postings_path": directory / "postings.bin",
    }
