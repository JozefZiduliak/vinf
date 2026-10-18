"""Stage 1.2 — regex extraction of structured records.

Reads:  data/raw/*.html
Writes: data/animals.jsonl (one Animal per line)
"""

import html as html_lib
import logging
import re
import time
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
METADATA_FILE = Path("data/metadata.tsv")
OUTPUT_FILE = Path("data/animals.jsonl")


SCIENTIFIC_NAME_RE = re.compile(r'<h1 class="rank--Species">\s*([^<]+?)\s*</h1>')


VERNACULAR_NAME_RE = re.compile(r'<p class="vernacular-name">\s*([^<]+?)\s*</p>')

TAXONOMY_RE = re.compile(
    r'<span class="rank-label">\s*(\w+)\s*</span>\s*</td>\s*<td>\s*'
    r'<a class="taxon-link rank--\w+" href="[^"]+">\s*([^<]+?)\s*</a>'
)


# Two markups on ADW: "IUCN Red List</a></dt><dd><span>Vulnerable</span>" on most
# pages, "IUCN Red List <a>[Link]</a></dt><dd>Not Evaluated</dd>" on ~40 pages.
IUCN_RE = re.compile(
    r"IUCN Red List.{0,200}?</dt>\s*<dd>\s*(?:<span>\s*)?([^<]+?)\s*<", re.DOTALL
)


SECTION_RE = re.compile(r'<h2 id="(\w+)">.*?</h2>(.*?)</section>', re.DOTALL)

SKIP_SECTIONS = {"comments", "contributors", "references", "label"}


TAG_BLOCK_RE = re.compile(
    r'<li class="keywords-header">\s*([^<]+?)\s*</li>(.*?)(?=<li class="keywords-header">|</section>)',
    re.DOTALL,
)
# Tags with a glossary entry are links, tags without one (e.g. "indian ocean",
# "icecap") are plain <span>s. Match both.
TAG_ITEM_RE = re.compile(
    r'(?:popover-replace" href="[^"]+"|<span)>\s*([^<]+?)\s*</(?:a|span)>'
)

NESTED_UL_RE = re.compile(r"<ul>.*?</ul>", re.DOTALL)

# HTML -> plain text helpers
BUTTON_RE = re.compile(r"<button.*?</button>", re.DOTALL)  # duplicate of each tag's <a>
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean(fragment: str) -> str:
    """Strip tags, decode entities (&amp; -> &), collapse whitespace."""
    fragment = BUTTON_RE.sub(" ", fragment)
    return WHITESPACE_RE.sub(
        " ", html_lib.unescape(HTML_TAG_RE.sub(" ", fragment))
    ).strip()


def extract_tags(html: str) -> dict[str, list[str]]:
    """{'Primary Diet': ['carnivore'], 'Terrestrial Biomes': [...], ...}"""
    return {
        header: TAG_ITEM_RE.findall(NESTED_UL_RE.sub("", block))
        for header, block in TAG_BLOCK_RE.findall(html)
    }


class Animal(BaseModel):
    slug: str
    scientific_name: str
    common_name: str | None
    taxonomy: dict[str, str]  # {"Order": "Carnivora", ...}
    conservation_status: str | None
    range: list[str]  # Biogeographic Regions
    habitat: list[str]  # Habitat Regions + Terrestrial Biomes
    diet: list[str]  # Primary Diet
    sections: dict[str, str]  # section id -> clean text
    text: str  # all sections joined, the full-text field


def first(pattern: re.Pattern[str], html: str) -> str | None:
    m = pattern.search(html)
    return m.group(1) if m else None


def parse_animal(html: str, slug: str) -> Animal:
    tags = extract_tags(html)
    sections = {
        sid: clean(body)
        for sid, body in SECTION_RE.findall(html)
        if sid not in SKIP_SECTIONS
    }
    return Animal(
        slug=slug,
        scientific_name=first(SCIENTIFIC_NAME_RE, html) or slug.replace("_", " "),
        common_name=first(VERNACULAR_NAME_RE, html),
        taxonomy=dict(TAXONOMY_RE.findall(html)),
        conservation_status=first(IUCN_RE, html),
        range=tags.get("Biogeographic Regions", []),
        habitat=tags.get("Habitat Regions", []) + tags.get("Terrestrial Biomes", []),
        diet=tags.get("Primary Diet", []),
        sections=sections,
        text=" ".join(sections.values()),
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    paths = sorted(RAW_DIR.glob("*.html"))
    coverage: Counter[str] = Counter()
    start = time.time()

    with OUTPUT_FILE.open("w", encoding="utf-8") as out:
        for i, path in enumerate(paths, 1):
            animal = parse_animal(path.read_text(encoding="utf-8"), path.stem)
            out.write(animal.model_dump_json() + "\n")
            for field in (
                "common_name",
                "taxonomy",
                "conservation_status",
                "range",
                "habitat",
                "diet",
                "text",
            ):
                if getattr(animal, field):
                    coverage[field] += 1
            if i % 500 == 0:
                log.info("parsed %d/%d", i, len(paths))

    log.info(
        "done: %d animals in %.1fs -> %s", len(paths), time.time() - start, OUTPUT_FILE
    )
    for field, n in coverage.items():
        log.info(
            "coverage %-20s %5d / %d (%.1f%%)",
            field,
            n,
            len(paths),
            100 * n / len(paths),
        )


if __name__ == "__main__":
    main()
