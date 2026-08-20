"""Section-aware chunking: semantic units, configured bounds, citation metadata.

Synthetic documents pin each rule down in isolation; the verbatim fixtures in
`tests/fixtures/mdx/` then prove the rules survive contact with the real corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.normalization import normalize_text
from src.db.models.enums import ChunkContentType
from src.services.ingestion.chunking import (
    Chunk,
    chunk_document,
    count_tokens,
    source_url_for,
)
from src.services.ingestion.mdx import transform_mdx

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mdx"
MANIFEST = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))
FIXTURE_NAMES = sorted(MANIFEST["documents"])


def chunks_for(name: str, **overrides: object) -> list[Chunk]:
    entry = MANIFEST["documents"][name]
    document = transform_mdx((FIXTURES / name).read_text(encoding="utf-8"))
    return chunk_document(
        document,
        source_path=entry["source_path"],
        source_url=entry["source_url"],
        **overrides,  # type: ignore[arg-type]
    )


def tiny_bounds(**overrides: int) -> Settings:
    """Bounds small enough to exercise packing on a short synthetic document."""
    defaults = {
        "chunk_min_tokens": 5,
        "chunk_target_tokens": 60,
        "chunk_max_tokens": 90,
        "chunk_overlap_tokens": 5,
    }
    return Settings(**{**defaults, **overrides})  # type: ignore[arg-type]


# --- Semantic units ----------------------------------------------------------


def test_code_stays_in_the_same_chunk_as_the_prose_that_explains_it() -> None:
    document = transform_mdx(
        '<Section id="deploy" title="استقرار">'
        "<p>برای استقرار برنامه، دستور زیر را اجرا کنید:</p>"
        '<Highlight className="bash">{`liara deploy --app my-app`}</Highlight>'
        "<p>پس از اجرا، خروجی را بررسی کنید.</p>"
        "</Section>"
    )

    result = chunk_document(
        document,
        source_path="src/pages/paas/x.mdx",
        settings=tiny_bounds(chunk_target_tokens=200),
    )

    assert len(result) == 1
    assert "برای استقرار برنامه" in result[0].text
    assert "liara deploy --app my-app" in result[0].text
    assert "پس از اجرا" in result[0].text
    assert result[0].code_languages == ["bash"]


def test_trailing_code_blocks_bind_back_to_their_prose() -> None:
    document = transform_mdx(
        "<p>مقدمه‌ای که قطعه کد بعدی را توضیح می‌دهد.</p>"
        '<Highlight className="bash">{`liara logs`}</Highlight>'
        '<Highlight className="bash">{`liara restart`}</Highlight>'
    )

    result = chunk_document(document, source_path="src/pages/paas/x.mdx", settings=tiny_bounds())

    assert len(result) == 1
    assert "liara logs" in result[0].text and "liara restart" in result[0].text


def test_code_opening_a_section_is_bound_forward_to_the_prose_that_follows() -> None:
    document = transform_mdx(
        '<Section id="s" title="عنوان">'
        '<Highlight className="bash">{`liara deploy`}</Highlight>'
        "<p>این دستور برنامه را مستقر می‌کند.</p>"
        "</Section>"
    )

    result = chunk_document(
        document,
        source_path="src/pages/paas/x.mdx",
        settings=tiny_bounds(chunk_target_tokens=200),
    )

    assert len(result) == 1
    assert "liara deploy" in result[0].text
    assert "این دستور برنامه را مستقر می‌کند." in result[0].text


def test_a_step_stays_with_its_image() -> None:
    document = transform_mdx(
        "<Step steps={[\n"
        '{ step: "۱", content: (<><p>وارد کنسول شوید</p>'
        '<img src="https://media.liara.ir/console.png" alt="کنسول" /></>) },\n'
        "]} />"
    )

    result = chunk_document(document, source_path="src/pages/paas/x.mdx", settings=tiny_bounds())

    assert len(result) == 1
    assert "وارد کنسول شوید" in result[0].text
    assert "https://media.liara.ir/console.png" in result[0].text
    assert result[0].content_type == ChunkContentType.STEP
    assert result[0].images[0]["alt"] == "کنسول"


def test_a_real_step_keeps_its_image_in_one_chunk() -> None:
    result = chunks_for("one-click-apps__ackee__quick-start.mdx")
    with_image = [chunk for chunk in result if chunk.images]

    assert with_image, "the fixture's step images were lost"
    for chunk in with_image:
        for image in chunk.images:
            assert image["url"] in chunk.text
            assert chunk.content_type in {ChunkContentType.STEP, ChunkContentType.MIXED}


# --- Bounds ------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_no_stored_chunk_falls_outside_the_configured_bounds(name: str) -> None:
    settings = get_settings()
    result = chunks_for(name)

    assert result
    for chunk in result:
        assert chunk.token_count <= settings.chunk_max_tokens, chunk.section_title
        if len(result) > 1:
            # The single documented exception: a document too small to reach the
            # floor has no neighbour to merge with.
            assert chunk.token_count >= settings.chunk_min_tokens, chunk.section_title


def test_undersized_sections_are_merged_rather_than_stored_alone() -> None:
    document = transform_mdx(
        "".join(
            f'<Section id="s{index}" title="بخش {index}"><p>یک جمله کوتاه.</p></Section>'
            for index in range(6)
        )
    )
    settings = tiny_bounds(chunk_min_tokens=40, chunk_target_tokens=120, chunk_max_tokens=200)

    result = chunk_document(document, source_path="src/pages/paas/x.mdx", settings=settings)

    assert len(result) < 6
    assert all(chunk.token_count >= settings.chunk_min_tokens for chunk in result)


def test_an_oversized_block_is_split_against_the_configured_maximum() -> None:
    lines = "\n".join(f"echo line-number-{index}" for index in range(400))
    document = transform_mdx(f'<Highlight className="bash">{{`{lines}`}}</Highlight>')
    settings = tiny_bounds(chunk_min_tokens=10, chunk_target_tokens=200, chunk_max_tokens=300)

    result = chunk_document(document, source_path="src/pages/paas/x.mdx", settings=settings)

    assert len(result) > 1
    assert all(chunk.token_count <= settings.chunk_max_tokens for chunk in result)


def test_bounds_come_from_configuration_not_from_code() -> None:
    document = transform_mdx((FIXTURES / "overview__about.mdx").read_text(encoding="utf-8"))
    entry = MANIFEST["documents"]["overview__about.mdx"]

    narrow = chunk_document(
        document,
        source_path=entry["source_path"],
        settings=tiny_bounds(chunk_min_tokens=20, chunk_target_tokens=150, chunk_max_tokens=400),
    )
    wide = chunk_document(
        document,
        source_path=entry["source_path"],
        settings=tiny_bounds(chunk_min_tokens=20, chunk_target_tokens=900, chunk_max_tokens=1600),
    )

    assert len(narrow) > len(wide)


def test_a_document_smaller_than_the_floor_is_stored_as_one_chunk() -> None:
    document = transform_mdx("<p>یک صفحه بسیار کوتاه.</p>")

    result = chunk_document(document, source_path="src/pages/paas/x.mdx")

    assert len(result) == 1
    assert result[0].token_count < get_settings().chunk_min_tokens


# --- Metadata and citations --------------------------------------------------


def test_a_citation_resolves_to_source_url_plus_the_section_anchor() -> None:
    name = "references__cli__add-account.mdx"
    result = chunks_for(name)
    anchored = [chunk for chunk in result if chunk.heading_anchor]

    assert anchored, "the fixture's <Section> anchors were lost"
    chunk = anchored[0]
    assert chunk.heading_anchor == "command-parameters"
    assert (
        chunk.citation_url == "https://docs.liara.ir/references/cli/add-account#command-parameters"
    )
    assert chunk.citation_url == f"{chunk.source_url}#{chunk.heading_anchor}"


def test_a_chunk_without_an_anchor_cites_the_page_itself() -> None:
    document = transform_mdx("# فقط یک عنوان\n\n<p>" + "متن. " * 60 + "</p>")

    chunk = chunk_document(document, source_path="src/pages/overview/about.mdx")[0]

    assert chunk.heading_anchor is None
    assert chunk.citation_url == "https://docs.liara.ir/overview/about"


@pytest.mark.parametrize(
    ("path", "url"),
    [
        (
            "src/pages/paas/django/getting-started.mdx",
            "https://docs.liara.ir/paas/django/getting-started",
        ),
        ("src/pages/overview/about.mdx", "https://docs.liara.ir/overview/about"),
        ("paas/about.mdx", "https://docs.liara.ir/paas/about"),
    ],
)
def test_source_url_mapping(path: str, url: str) -> None:
    assert source_url_for(path) == url


def test_path_metadata_separates_runtime_from_framework() -> None:
    django = chunks_for("paas__django__how-tos__create-app.mdx")[0]
    postgres = chunks_for("dbaas__postgresql__how-tos__connect-via-platform__django.mdx")[0]

    assert django.framework == "django"
    assert django.runtime is None
    assert django.service == "paas"
    assert postgres.service == "postgresql"


def test_breadcrumbs_carry_the_path_the_document_and_the_section() -> None:
    chunk = chunks_for("references__cli__add-account.mdx")[0]

    assert "references" in chunk.breadcrumbs
    assert chunk.section_title in chunk.breadcrumbs


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_chunk_carries_what_a_citation_needs(name: str) -> None:
    for chunk in chunks_for(name):
        assert chunk.source_path and chunk.source_url
        assert chunk.text.strip()
        assert chunk.token_count > 0
        assert chunk.language in {"fa", "en"}
        assert chunk.content_type in set(ChunkContentType)
        assert chunk.citation_url.startswith(chunk.source_url)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_normalized_text_comes_from_the_shared_normalizer(name: str) -> None:
    for chunk in chunks_for(name):
        assert chunk.text_normalized == normalize_text(chunk.text)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_ordinals_are_dense_and_ordered(name: str) -> None:
    result = chunks_for(name)

    assert [chunk.ordinal for chunk in result] == list(range(len(result)))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_the_mistune_ast_lines_up_with_the_span_scan(name: str) -> None:
    """A mismatch is recorded, never hidden — it means the pre-pass output moved."""
    for chunk in chunks_for(name):
        assert chunk.extra_metadata["ast_aligned"] is True


def test_images_carry_url_alt_and_position() -> None:
    result = chunks_for("paas__django__how-tos__create-app.mdx")
    images = [image for chunk in result for image in chunk.images]

    assert images
    for image in images:
        assert image["url"].startswith("http")
        assert "alt" in image
        assert isinstance(image["ordinal"], int)


def test_a_table_is_typed_as_a_table_and_kept_whole() -> None:
    document = transform_mdx(
        '<Table headers={["پلن", "رم"]} data={[["small", "0.5 GB"], ["medium", "1 GB"]]} />'
    )

    result = chunk_document(document, source_path="src/pages/references/x.mdx")

    assert len(result) == 1
    assert result[0].content_type == ChunkContentType.TABLE
    assert "| small | 0.5 GB |" in result[0].text
    assert "| medium | 1 GB |" in result[0].text


def test_the_chunk_text_opens_with_its_breadcrumb_so_it_reads_standalone() -> None:
    chunk = chunks_for("references__cli__add-account.mdx")[0]

    assert chunk.text.splitlines()[0].startswith("مستندات اضافه کردن حساب کاربری جدید")
    assert chunk.section_title in chunk.text.splitlines()[0]


# --- Failure paths -----------------------------------------------------------


def test_a_document_with_text_but_no_chunks_names_its_own_cause() -> None:
    document = transform_mdx("<p>متن</p>").__class__(  # rebuild with an unsplittable body
        markdown="   ",
        title=None,
        sections=(),
        images=(),
        code_languages=(),
        step_texts=(),
        source_char_count=10,
        content_char_count=10,
        discarded_char_count=0,
        discarded_char_ratio=0.0,
        flagged_for_review=False,
        unrecognized_tags={},
    )

    assert chunk_document(document, source_path="src/pages/paas/x.mdx") == []


def test_chunking_raises_when_cleaned_text_produces_nothing() -> None:
    document = transform_mdx("<p>متن</p>").__class__(
        markdown="---",
        title=None,
        sections=(),
        images=(),
        code_languages=(),
        step_texts=(),
        source_char_count=10,
        content_char_count=10,
        discarded_char_count=0,
        discarded_char_ratio=0.0,
        flagged_for_review=False,
        unrecognized_tags={},
    )

    with pytest.raises(RescueError) as error:
        chunk_document(document, source_path="src/pages/paas/x.mdx")

    assert error.value.code is ErrorCode.DOCUMENT_PARSE_FAILED


def test_token_counting_is_the_embedding_model_s_own_ruler() -> None:
    assert count_tokens("") == 0
    assert count_tokens("liara deploy") > 0
