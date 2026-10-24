"""Unit tests for the scoring formulas. No data needed."""

import math

import pytest

from index.search import IDF, NORM, TF

N = 4239  # corpus size


def test_classic_idf_is_zero_for_term_in_every_doc():
    assert IDF["classic"](N, N) == 0.0


def test_classic_idf_grows_for_rare_terms():
    assert IDF["classic"](N, 1) > IDF["classic"](N, 100) > 0


def test_smooth_idf_never_zero():
    assert IDF["smooth"](N, N) > 0
    assert IDF["smooth"](N, 1) == pytest.approx(1 + math.log(N / 2))


def test_bm25_idf_is_negative_for_terms_in_most_docs():
    assert IDF["bm25"](N, N - 1) < 0
    assert IDF["bm25"](N, 1) == pytest.approx(math.log((N - 0.5) / 1.5))


def test_unary_idf_ignores_df():
    assert IDF["unary"](N, 1) == IDF["unary"](N, N) == 1.0


def test_all_idf_variants_rank_rare_above_common():
    for name, fn in IDF.items():
        if name != "unary":
            assert fn(N, 10) > fn(N, 1000), name


def test_log_tf_compresses_repetition():
    assert TF["log"](1) == 1
    assert TF["log"](20) < TF["raw"](20) / 4


def test_norms_on_a_toy_index():
    index = {
        "doc_lengths": {"a": 100, "b": 400},
        "doc_norms": {"raw": {"a": 10.0, "b": 20.0}, "log": {"a": 5.0, "b": 6.0}},
        "avg_len": 250,
    }
    assert NORM["none"](index, "a", "raw") == 1.0
    assert NORM["len"](index, "b", "raw") == 400
    assert NORM["cosine"](index, "a", "log") == 5.0
    # pivot: short doc below 1, long doc above 1, average doc exactly 1
    assert NORM["pivot"](index, "a", "raw") < 1 < NORM["pivot"](index, "b", "raw")
    index["doc_lengths"]["avg"] = 250
    assert NORM["pivot"](index, "avg", "raw") == pytest.approx(1.0)
