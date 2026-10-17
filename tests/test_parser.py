"""Unit tests for the regex extractors in src/parser.py (Submission 1 bonus).

Runs against 20 crawled pages in data/raw/ (not in git); skipped when the data is absent.
Two kinds of tests:
  * gold: hand-checked expected values for 6 species
  * invariants: structural properties that must hold on every page
"""

import re
from pathlib import Path

import pytest

from parser import SKIP_SECTIONS, Animal, parse_animal

RAW_DIR = Path("data/raw")

GOLD = {
    "Panthera_leo": {
        "scientific_name": "Panthera leo",
        "common_name": "lion",
        "conservation_status": "Vulnerable",
        "order": "Carnivora",
        "family": "Felidae",
        "diet": ["carnivore"],
        "range": ["palearctic", "oriental", "ethiopian"],
    },
    "Melopsittacus_undulatus": {
        "scientific_name": "Melopsittacus undulatus",
        "common_name": "budgerigar",
        "conservation_status": "Least Concern",
        "order": "Psittaciformes",
        "family": "Psittacidae",
        "diet": ["herbivore"],
        "range": ["nearctic", "australian"],
    },
    "Apis_mellifera": {
        "scientific_name": "Apis mellifera",
        "common_name": "honey bee",
        "conservation_status": "No special status",
        "order": "Hymenoptera",
        "family": "Apidae",
        "diet": ["herbivore"],
        "range": [
            "nearctic",
            "palearctic",
            "oriental",
            "ethiopian",
            "neotropical",
            "australian",
        ],
    },
    "Carcharodon_carcharias": {
        "scientific_name": "Carcharodon carcharias",
        "common_name": "Great white shark",
        "conservation_status": "Vulnerable",
        "order": "Lamniformes",
        "family": "Lamnidae",
        "diet": ["carnivore"],
        "range": ["atlantic ocean", "pacific ocean"],
    },
    "Ornithorhynchus_anatinus": {
        "scientific_name": "Ornithorhynchus anatinus",
        "common_name": "duck-billed platypus",
        "conservation_status": "No special status",
        "order": "Monotremata",
        "family": "Ornithorhynchidae",
        "diet": ["carnivore"],
        "range": ["australian"],
    },
    "Sorex_cinereus": {
        "scientific_name": "Sorex cinereus",
        "common_name": "cinereus shrew",
        "conservation_status": "Least Concern",
        "order": "Soricomorpha",
        "family": "Soricidae",
        "diet": ["carnivore"],
        "range": ["nearctic"],
    },
}

# 6 gold pages + 14 sampled evenly across the alphabet: mammals, birds, fish, insects, amphibians, reptiles
PAGES = list(GOLD) + [
    "Abrawayaomys_ruschii",
    "Aonyx_cinerea",
    "Capra_walie",
    "Cryptomys_hottentotus",
    "Eupetaurus_cinereus",
    "Icterus_galbula",
    "Marmosa_lepida",
    "Notophthalmus_perstriatus",
    "Phrynosoma_solare",
    "Rhyacotriton_olympicus",
    "Tamias_quadrivittatus",
    "Wyeomyia_smithii",
    "Puma_concolor",
    "Eumetopias_jubatus",
]

IUCN_CATEGORIES = {
    "Least Concern",
    "Near Threatened",
    "Vulnerable",
    "Endangered",
    "Critically Endangered",
    "Extinct in the Wild",
    "Extinct",
    "Data Deficient",
    "Not Evaluated",
    "No special status",
    "Lower Risk",
    "Lower Risk - Least Concern",
    "Lower Risk - Near Threatened",
    "Lower Risk - Conservation Dependent",
}
# ADW omits Phylum on some insect pages and Order on some amphibians; only these are universal
REQUIRED_RANKS = {"Kingdom", "Class", "Family", "Genus"}
# real HTML tags only; literal "<g.Pan>" in Apis_mellifera prose must not count
HTML_TAG = re.compile(
    r"</?(p|a|ul|li|span|div|section|h[1-6]|button|em|i|b|br|dl|dt|dd|table|tr|td|img)\b[^>]*>"
)


@pytest.fixture(scope="module", params=PAGES)
def animal(request) -> Animal:
    path = RAW_DIR / f"{request.param}.html"
    if not path.exists():
        pytest.skip(f"{path} not crawled")
    return parse_animal(path.read_text(encoding="utf-8"), request.param)


# --- gold ---------------------------------------------------------------------


@pytest.mark.parametrize("slug", list(GOLD))
def test_gold_values(slug: str) -> None:
    path = RAW_DIR / f"{slug}.html"
    if not path.exists():
        pytest.skip(f"{path} not crawled")
    a = parse_animal(path.read_text(encoding="utf-8"), slug)
    g = GOLD[slug]
    assert a.scientific_name == g["scientific_name"]
    assert a.common_name == g["common_name"]
    assert a.conservation_status == g["conservation_status"]
    assert a.taxonomy["Order"] == g["order"]
    assert a.taxonomy["Family"] == g["family"]
    assert a.diet == g["diet"]
    assert a.range == g["range"]


# --- invariants on all 20 pages ----------------------------------------------


def test_scientific_name_matches_slug(animal: Animal) -> None:
    assert animal.scientific_name == animal.slug.replace("_", " ")


def test_taxonomy_has_main_ranks(animal: Animal) -> None:
    assert REQUIRED_RANKS <= animal.taxonomy.keys()
    assert animal.taxonomy["Kingdom"] == "Animalia"
    assert animal.taxonomy["Genus"] == animal.slug.split("_")[0]


def test_conservation_status_is_iucn_category(animal: Animal) -> None:
    assert (
        animal.conservation_status is None
        or animal.conservation_status in IUCN_CATEGORIES
    )


def test_sections_present_and_clean(animal: Animal) -> None:
    assert "geographic_range" in animal.sections
    assert len(animal.sections) >= 5
    assert not SKIP_SECTIONS & animal.sections.keys()
    for body in animal.sections.values():
        # no HTML tags left ("<<g.Pan>>" on Apis_mellifera is literal site text, not a tag)
        assert not HTML_TAG.search(body)
        assert "&amp;" not in body and "  " not in body


def test_tags_are_non_empty_strings(animal: Animal) -> None:
    for tag in animal.range + animal.habitat + animal.diet:
        assert tag and tag == tag.strip()


def test_text_is_concatenation_of_sections(animal: Animal) -> None:
    assert animal.text == " ".join(animal.sections.values())
    assert len(animal.text.split()) > 100
