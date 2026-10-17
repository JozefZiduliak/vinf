"""Shared tokenization. Must be identical for documents and queries."""

import re

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Standard English function words (Manning IIR 2.2.2 style list) + domain-specific ones
STOP_WORDS = frozenset(
    """
    a an the and or but if of in on at to for from by with as is are was were be been being
    it its this that these those they them their there then than so such not no nor can may
    has have had do does did will would also into over under between which who whom whose
    """.split()  # noqa: SIM905
)

# naive suffix stripping, applied only when --stem is on
SUFFIXES = ("ies", "ing", "ed", "es", "s")


def stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for suf in SUFFIXES:
        if token.endswith(suf):
            if suf == "ies":
                return token[:-3] + "y"
            return token[: -len(suf)]
    return token


def tokenize(text: str, use_stem: bool = False) -> list[str]:
    tokens = [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP_WORDS]
    if use_stem:
        tokens = [stem(t) for t in tokens]
    return tokens
