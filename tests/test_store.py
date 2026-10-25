"""Round-trip tests for the on-disk index format. Toy data, no corpus needed."""

import pytest

from index.storage import POSTING, load_index, read_postings, write_index

LION, BUDGIE = "Panthera_leo", "Melopsittacus_undulatus"


def toy_index() -> dict:
    return {
        "stem": False,
        "N": 2,
        "doc_lengths": {LION: 3, BUDGIE: 2},
        "doc_norms": {
            "raw": {LION: 2.2361, BUDGIE: 1.4142},
            "log": {LION: 1.9, BUDGIE: 1.4142},
        },
        "postings": {
            "lion": {LION: 2},
            "africa": {LION: 1, BUDGIE: 1},
            "parrot": {BUDGIE: 1},
        },
        "docs": {
            LION: {
                "name": "lion",
                "order": "Carnivora",
                "family": "Felidae",
                "status": None,
            },
            BUDGIE: {
                "name": "budgerigar",
                "order": "Psittaciformes",
                "family": "Psittacidae",
                "status": "Least Concern",
            },
        },
    }


@pytest.fixture
def written(tmp_path):
    write_index(toy_index(), tmp_path)
    return tmp_path


def test_documents_round_trip(written):
    index = load_index(written)
    assert index["N"] == 2
    assert index["slugs"] == [LION, BUDGIE]
    assert index["doc_lengths"] == [3, 2]
    assert index["doc_norms"]["raw"] == [2.2361, 1.4142]
    assert index["avg_len"] == 2.5
    assert index["docs"][0]["status"] is None  # empty TSV cell comes back as None
    assert index["docs"][1]["status"] == "Least Concern"


def test_postings_round_trip(written):
    index = load_index(written)
    with (written / "postings.bin").open("rb") as f:
        assert read_postings(f, index["terms"], "lion") == [(0, 2)]
        assert read_postings(f, index["terms"], "africa") == [(0, 1), (1, 1)]
        assert read_postings(f, index["terms"], "parrot") == [(1, 1)]
        assert read_postings(f, index["terms"], "zebra") == []


def test_dictionary_has_df_and_contiguous_offsets(written):
    terms = load_index(written)["terms"]
    # terms are written sorted, so each offset = previous offset + previous df * 6
    assert terms["africa"] == (2, 0)
    assert terms["lion"] == (1, 2 * POSTING.size)
    assert terms["parrot"] == (1, 3 * POSTING.size)
    assert (written / "postings.bin").stat().st_size == 4 * POSTING.size
