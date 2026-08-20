"""Every transformation class the normalizer performs, one case at a time.

Each case is written as a (raw, normalized) pair drawn from how Persian is
actually typed: Arabic keyboard letters in questions, Persian digits in prose,
ZWNJ in documentation. A failure here is a class of questions that will never
match its answer.
"""

from __future__ import annotations

import pytest

from src.core.normalization import (
    NORMALIZER_VERSION,
    normalize_query,
    normalize_text,
)

ZWNJ = chr(0x200C)
ZWSP = chr(0x200B)
RLM = chr(0x200F)


@pytest.mark.parametrize(
    ("label", "raw", "expected"),
    [
        # --- Yeh and kaf: the two that matter most ---
        ("arabic yeh", "چگونه ديتابيس بسازم", "چگونه دیتابیس بسازم"),
        ("alef maksura", "علیى", "علیی"),
        ("arabic kaf", "يك برنامه", "یک برنامه"),
        # --- Zero-width non-joiner becomes a word boundary ---
        ("zwnj to space", f"می{ZWNJ}شود", "می شود"),
        ("zwnj matches spaced form", f"نمی{ZWNJ}توانم", "نمی توانم"),
        # --- Digit systems all fold to ASCII ---
        ("persian digits", "پلن ۲", "پلن 2"),
        ("arabic-indic digits", "پورت ٨٠٨٠", "پورت 8080"),
        ("ascii digits untouched", "port 8080", "port 8080"),
        # --- Spacing ---
        ("collapsed whitespace", "  دیپلوی    اپ  ", "دیپلوی اپ"),
        ("newlines and tabs", "خطای\n\t404", "خطای 404"),
        # --- Invisible characters carry no signal ---
        ("zero-width space", f"دی{ZWSP}پلوی", "دیپلوی"),
        ("direction mark", f"{RLM}لیارا", "لیارا"),
        ("tatweel", "لیـــارا", "لیارا"),
        ("harakat", "مُحَمَّد", "محمد"),
        # --- Alef, heh, and waw variants ---
        ("hamza alef", "أرور", "ارور"),
        ("alef madda kept", "آدرس", "آدرس"),
        ("teh marbuta", "قاعدة", "قاعده"),
        # --- Punctuation folds to ASCII so quoted errors tokenize alike ---
        ("persian question mark", "چطور؟", "چطور?"),
        ("persian comma", "اول، دوم", "اول, دوم"),
        # --- Latin identifiers are case-folded ---
        ("latin case", "Docker Compose", "docker compose"),
        ("command preserved", "liara deploy --app my-app", "liara deploy --app my-app"),
    ],
)
def test_transformation_classes(label: str, raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected, label


@pytest.mark.parametrize(
    ("written_one_way", "written_another_way"),
    [
        ("ديتابيس", "دیتابیس"),
        ("يك", "یک"),
        (f"می{ZWNJ}شود", "می شود"),
        ("پلن ۲", "پلن 2"),
        ("Liara", "liara"),
    ],
)
def test_variant_spellings_converge(written_one_way: str, written_another_way: str) -> None:
    """The whole point: two spellings of one thing become one string."""
    assert normalize_text(written_one_way) == normalize_text(written_another_way)


@pytest.mark.parametrize(
    "value",
    ["", "   ", "دیتابیس", f"می{ZWNJ}شود", "liara deploy", "خطای ۵۰۳؟"],
)
def test_idempotent(value: str) -> None:
    once = normalize_text(value)
    assert normalize_text(once) == once


def test_empty_input_is_not_an_error() -> None:
    assert normalize_text("") == ""


def test_query_normalization_is_the_same_function() -> None:
    """Not merely equivalent — the same code, so the two cannot drift apart."""
    samples = ["ديتابيس ايجاد كنم", f"می{ZWNJ}خواهم دیپلوی کنم", "PORT 8080"]
    for sample in samples:
        assert normalize_query(sample) == normalize_text(sample)


def test_version_is_declared() -> None:
    """The version is what forces a reindex when a rule changes."""
    assert isinstance(NORMALIZER_VERSION, int)
    assert NORMALIZER_VERSION >= 1
