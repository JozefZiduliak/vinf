"""Stage 1.2 — regex extraction of structured records.

Reads:  data/raw/*.html
Writes: data/animals.jsonl (one Animal per line)
"""

from pathlib import Path
import re

RAW_DIR = Path("data/raw")
METADATA_FILE = Path("data/metadata.tsv")
OUTPUT_FILE = Path("data/animals.jsonl")


SCIENTIFIC_NAME_RE = re.compile(
    r'<h1 class="rank--Species">\s*(?:<span>\w+</span>)?\s</h1>'
)

# There are more vernacular names, that we might add later
VERNACULAR_NAME_RE = re.compile(r'<p class="vernacular-name">\s*([^<]+?)\s*</p>')

# My regex
TAXONOMY_RE = re.compile(
    r'<span class="rank-label">\s*(\w+)\s*</span>\s*</td>\s*<td>\s*'
    r'<a class="taxon-link rank--\w+" href="[^"]+">\s*([^<]+?)\s*</a>'
)


IUCN_RE = re.compile(r'IUCN Red List\s*</a>\s*</dt>\s*<dd>\s*<span>\s*([^<]+?)\s*</span>')

def main() -> None:
    for path in sorted(RAW_DIR.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        slug = path.stem

if __name__ == "__main__":
    main()
