"""Persian text normalization — one function, both paths.

This is the highest-risk small component in the system. Indexed text and
incoming queries must be normalized **byte-identically**; asymmetry does not
raise, does not log, and does not fail a test that only checks one side. It just
quietly loses recall.

Everything here is therefore pure and versioned. `NORMALIZER_VERSION` is stored
on every index version, so changing a rule below invalidates existing lexical
and dense indexes and forces a reindex rather than silently mixing conventions.
"""

from __future__ import annotations

import re
import unicodedata

#: Bump on **any** change to the rules below. An index built under a different
#: version is not comparable with a query normalized under this one.
NORMALIZER_VERSION = 1

# --- Character folding -------------------------------------------------------
# Persian is routinely typed with Arabic keyboard characters. The pairs below
# are visually identical in most fonts and semantically the same letter, so a
# user typing يك and documentation containing یک must reach the same string.
_CHARACTER_MAP = {
    # Yeh: Arabic yeh and alef maksura → Persian yeh
    "ي": "ی",
    "ى": "ی",
    "ے": "ی",  # yeh barree
    # Kaf: Arabic kaf and its variants → Persian keheh
    "ك": "ک",
    "ڪ": "ک",
    # Hamzated and wasla alefs → bare alef. Alef madda (آ) is kept: it carries a
    # pronunciation distinction that Persian spelling observes consistently.
    "أ": "ا",
    "إ": "ا",
    "ٱ": "ا",
    # Heh: teh marbuta and heh-with-yeh → heh
    "ة": "ه",
    "ۀ": "ه",
    "ۂ": "ه",
    # Waw variants → waw
    "ؤ": "و",
    # Persian/Arabic punctuation → ASCII, so an error string quoted in either
    # form tokenizes the same way.
    "،": ",",
    "؛": ";",
    "؟": "?",
    "٫": ".",
    "٬": ",",
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "«": '"',
    "»": '"',
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
}

# --- Digits ------------------------------------------------------------------
# Three digit systems appear in this corpus: ASCII in commands and versions,
# Persian in prose, Arabic-Indic occasionally. All fold to ASCII so "پلن ۲" and
# "پلن 2" are one term.
_DIGIT_MAP = {chr(0x06F0 + i): str(i) for i in range(10)} | {
    chr(0x0660 + i): str(i) for i in range(10)
}

# --- Characters that carry no matching signal --------------------------------
# Harakat, tatweel, and the invisible formatting characters that ride along in
# copied text: present inconsistently in the source and never typed into a
# search box. Named by codepoint rather than pasted in: most are invisible, and a literal
# copy of one cannot be reviewed, diffed, or edited safely.
_STRIPPED_RANGES: tuple[tuple[int, int], ...] = (
    (0x064B, 0x0652),  # harakat: fathatan through sukun
    (0x0670, 0x0670),  # superscript alef
    (0x0640, 0x0640),  # tatweel (kashida)
    (0x200B, 0x200B),  # zero-width space
    (0x200D, 0x200D),  # zero-width joiner
    (0x200E, 0x200F),  # left-to-right and right-to-left marks
    (0x00AD, 0x00AD),  # soft hyphen
    (0xFEFF, 0xFEFF),  # byte-order mark
)
_STRIPPED = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _STRIPPED_RANGES) + "]")

#: Zero-width non-joiner (U+200C). Persian writes one word three ways: with a
#: ZWNJ, with a space, or with neither. Mapping it to a space merges the first
#: two -- the pair that actually appears in this corpus -- and keeps the word
#: boundary, which `to_tsvector('simple', ...)` needs; deleting it instead
#: would fuse both parts into one token that matches nothing.
_ZWNJ = chr(0x200C)

_WHITESPACE = re.compile(r"\s+")
_TRANSLATION = str.maketrans(_CHARACTER_MAP | _DIGIT_MAP | {_ZWNJ: " "})


def normalize_text(value: str) -> str:
    """Fold Persian text to the single form used for indexing and querying.

    Pure and idempotent: ``normalize_text(normalize_text(x)) == normalize_text(x)``.
    Call this — never a local variant — everywhere text is stored for search or
    submitted as a query.
    """
    if not value:
        return ""
    # NFC first: composed and decomposed forms of the same letter must not
    # survive as two different strings into the translation table.
    text = unicodedata.normalize("NFC", value)
    text = _STRIPPED.sub("", text)
    text = text.translate(_TRANSLATION)
    # Latin identifiers — service names, commands, error strings — are matched
    # case-insensitively; `to_tsvector('simple', …)` folds case anyway, and the
    # dense side benefits from the same consistency.
    text = text.lower()
    return _WHITESPACE.sub(" ", text).strip()


def normalize_query(value: str) -> str:
    """Normalize an incoming question.

    Deliberately a thin alias rather than a second implementation: the index
    path and the query path must not be able to drift apart.
    """
    return normalize_text(value)
