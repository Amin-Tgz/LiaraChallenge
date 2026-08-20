"""The JSX pre-pass, against synthetic cases and against the real corpus.

The fixtures in `tests/fixtures/mdx/` are verbatim copies of upstream documents
from `liara-cloud/docs`, recorded with their paths and commit in `MANIFEST.json`.
They are unedited on purpose: the pre-pass encodes assumptions about a
repository we do not control, and a hand-tidied sample would stop testing the
thing that actually breaks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.core.config import get_settings
from src.core.errors import ErrorCode, RescueError
from src.services.ingestion.mdx import transform_mdx

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mdx"
MANIFEST = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))
FIXTURE_NAMES = sorted(MANIFEST["documents"])

#: Fenced code and inline code are *content*: the corpus is full of
#: `<LIARA_API_KEY>` placeholders, `${VAR}` shell expansions, and JSON braces
#: that must reach the embedding intact. "No `<` or `{` survives" is therefore
#: an assertion about prose, and these strip the code so prose is what is left.
_FENCE = re.compile(r"^(`{3,})[^\n]*\n.*?^\1[ \t]*$", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def prose_of(markdown: str) -> str:
    return _INLINE_CODE.sub("", _FENCE.sub("", markdown))


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- Section headings and anchors -------------------------------------------


def test_section_component_becomes_a_heading_carrying_its_anchor() -> None:
    result = transform_mdx('<Layout><Section id="envs" title="متغیرهای محیطی" /></Layout>')

    assert "## متغیرهای محیطی" in result.markdown
    assert [(s.title, s.anchor, s.level) for s in result.sections] == [
        ("متغیرهای محیطی", "envs", 2)
    ]


def test_section_heading_tag_sets_the_level() -> None:
    result = transform_mdx(
        '<Section headingTag="h3" id="mirrors" title="میرورها" />',
    )

    assert result.sections[0].level == 3
    assert "### میرورها" in result.markdown


def test_section_children_are_kept_under_their_heading() -> None:
    result = transform_mdx('<Section id="a" title="عنوان"><p>بدنه</p></Section>')

    assert result.markdown.index("## عنوان") < result.markdown.index("بدنه")


def test_markdown_headings_join_the_anchor_sequence() -> None:
    """A plain `# title` must appear in `sections` or the anchors misalign."""
    result = transform_mdx('# سرآغاز\n\n<Section id="x" title="بخش" />')

    assert [(s.title, s.anchor) for s in result.sections] == [("سرآغاز", None), ("بخش", "x")]


# --- Non-content constructs --------------------------------------------------


def test_imports_layout_head_and_expression_blocks_are_removed() -> None:
    source = """import Layout from "@/components/Layout";
import {
  GoArrowLeft,
} from "react-icons/go";

<Layout>
<Head>
<title>عنوان صفحه</title>
<meta property="og:title" content="x" />
</Head>

متن اصلی

<div className="grid">
  {[{ text: 'برو', link: './x' }].map(item => <Card>{item.text}</Card>)}
</div>
</Layout>
"""
    result = transform_mdx(source)

    assert result.markdown.strip() == "متن اصلی"
    assert result.title == "عنوان صفحه"
    assert "react-icons" not in result.markdown
    assert "og:title" not in result.markdown


def test_navigation_only_components_are_dropped() -> None:
    result = transform_mdx(
        "<div>نگه‌داشتنی<Card>کارت</Card><Button>دکمه</Button>"
        '<PlatformIcon platform="django" /><GoArrowLeft /></div>'
    )

    assert "کارت" not in result.markdown
    assert "دکمه" not in result.markdown
    assert "نگه‌داشتنی" in result.markdown


def test_a_dropped_subtree_counts_against_the_discard_ratio() -> None:
    result = transform_mdx("<div>" + "متن" * 10 + "<Card>" + "کارت" * 40 + "</Card></div>")

    assert result.discarded_char_count > 0
    assert 0.0 < result.discarded_char_ratio < 1.0


# --- Links -------------------------------------------------------------------


def test_inline_anchor_keeps_its_target_and_drops_its_styling() -> None:
    result = transform_mdx(
        '<a href="https://www.djangoproject.com/" className="text-[#2196f3]">Django</a> است'
    )

    assert "[Django](https://www.djangoproject.com/)" in result.markdown
    assert "className" not in result.markdown


def test_next_link_component_is_not_treated_as_the_void_html_link_element() -> None:
    """`<link>` closes itself; `<Link>` does not — folding case empties 808 links."""
    result = transform_mdx("<Alert><Link href='./related-links'>لینک‌های مرتبط</Link></Alert>")

    assert "[لینک‌های مرتبط](./related-links)" in result.markdown


# --- Import-path inconsistency ----------------------------------------------


TAB_BODY = """<Tabs
  tabs={[{ label: "JavaScript" }, { label: "Python" }]}
  content={[<><p>یک</p></>, <><p>دو</p></>]}
/>"""


def test_the_same_component_transforms_identically_from_different_import_paths() -> None:
    singular = transform_mdx(f'import Tabs from "@/components/Common/tab";\n{TAB_BODY}')
    plural = transform_mdx(f'import Tabs from "@/components/Common/tabs";\n{TAB_BODY}')

    assert singular.markdown == plural.markdown
    assert "**JavaScript**" in singular.markdown
    assert "یک" in singular.markdown and "دو" in singular.markdown


# --- Code --------------------------------------------------------------------


def test_highlight_becomes_a_fenced_code_block_with_its_language() -> None:
    """The corpus has no Markdown fences at all; `<Highlight>` is the only one."""
    result = transform_mdx('<Highlight className="bash">{`liara deploy --app my-app`}</Highlight>')

    assert result.markdown == "```bash\nliara deploy --app my-app\n```"
    assert result.code_languages == ("bash",)


def test_code_inside_an_expression_block_is_kept_not_discarded() -> None:
    result = transform_mdx('<Highlight className="json">{`{"port": 8000}`}</Highlight>')

    assert '{"port": 8000}' in result.markdown
    assert result.discarded_char_count == 0


def test_shell_expansion_and_placeholders_survive_inside_code() -> None:
    result = transform_mdx(
        '<Highlight className="bash">{`curl -H "Authorization: Bearer ${LIARA_API_KEY}" '
        "<baseUrl>/v1`}</Highlight>"
    )

    assert "${LIARA_API_KEY}" in result.markdown
    assert "<baseUrl>" in result.markdown


def test_highlight_tabs_emits_one_labelled_fence_per_tab() -> None:
    result = transform_mdx(
        "<HighlightTabs tabs={[\n"
        '{ label: "openAI", language: "javascript", code: `const a = 1;` },\n'
        '{ label: "cURL", language: "bash", code: `curl x` },\n'
        "]} />"
    )

    assert "**openAI**" in result.markdown
    assert "```javascript\nconst a = 1;\n```" in result.markdown
    assert "```bash\ncurl x\n```" in result.markdown


# --- Callouts, badges, steps, tables ----------------------------------------


def test_alert_becomes_a_blockquote() -> None:
    result = transform_mdx('<Alert variant="warning">مراقب باشید</Alert>')

    assert result.markdown == "> مراقب باشید"


def test_important_is_an_inline_badge_not_a_blockquote() -> None:
    result = transform_mdx("<p>متد <Important>chat.completions.create</Important> را ببینید</p>")

    assert "`chat.completions.create`" in result.markdown
    assert not result.markdown.startswith(">")


def test_step_content_is_recorded_as_an_atomic_region() -> None:
    result = transform_mdx(
        "<Step steps={[\n"
        '{ step: "۱", content: (<><p>ابتدا وارد شوید</p>'
        '<img src="https://media.liara.ir/a.png" alt="ورود" /></>) },\n'
        "]} />"
    )

    assert len(result.step_texts) == 1
    step = result.step_texts[0]
    assert "ابتدا وارد شوید" in step
    assert "![ورود](https://media.liara.ir/a.png)" in step
    assert step in result.markdown


def test_table_component_becomes_a_markdown_table() -> None:
    result = transform_mdx(
        '<Table headers={["تابع", "React"]} data={[["useChat", <TickBadge />]]} />'
    )

    assert "| تابع | React |" in result.markdown
    assert "| useChat | ✔ |" in result.markdown


def test_question_box_keeps_the_answer_passed_as_a_jsx_prop() -> None:
    result = transform_mdx(
        '<QuestionBox id="memory" question="آیا حافظه دارد؟" '
        "answer={<><p>خیر، به‌طور پیش‌فرض ندارد.</p></>} />"
    )

    assert "### آیا حافظه دارد؟" in result.markdown
    assert "خیر، به‌طور پیش‌فرض ندارد." in result.markdown
    assert result.sections[0].anchor == "memory"


def test_images_are_extracted_with_alt_text_and_document_wide_ordinals() -> None:
    result = transform_mdx(
        '<Section id="s" title="ت">'
        '<img src="https://media.liara.ir/a.png" alt="اول" />'
        '<img src="https://media.liara.ir/b.png" alt="دوم" /></Section>'
    )

    assert [(i.url, i.alt, i.ordinal, i.heading_anchor) for i in result.images] == [
        ("https://media.liara.ir/a.png", "اول", 0, "s"),
        ("https://media.liara.ir/b.png", "دوم", 1, "s"),
    ]
    assert "![اول](https://media.liara.ir/a.png)" in result.markdown


# --- Guardrails --------------------------------------------------------------


def test_a_clean_document_discards_nothing() -> None:
    result = transform_mdx("<Layout><p>یک متن ساده و کامل</p></Layout>")

    assert result.discarded_char_ratio == 0.0
    assert result.flagged_for_review is False


def test_documents_above_the_configured_threshold_are_flagged() -> None:
    source = "<div>" + "کوتاه" + "<Card>" + "بلند" * 100 + "</Card></div>"

    assert transform_mdx(source, discard_ratio_threshold=0.5).flagged_for_review is True
    assert transform_mdx(source, discard_ratio_threshold=0.99).flagged_for_review is False


def test_the_threshold_defaults_to_configuration_not_a_literal() -> None:
    settings = get_settings()
    source = "<div>" + "کوتاه" + "<Card>" + "بلند" * 100 + "</Card></div>"
    result = transform_mdx(source)

    assert result.flagged_for_review == (
        result.discarded_char_ratio > settings.ingest_discard_ratio_threshold
    )


def test_unrecognized_components_are_reported_rather_than_silently_unwrapped() -> None:
    result = transform_mdx("<div><BrandNewWidget>متن درون ویجت</BrandNewWidget></div>")

    assert result.unrecognized_tags == {"BrandNewWidget": 1}
    assert "متن درون ویجت" in result.markdown


def test_a_non_empty_document_that_yields_no_text_names_its_own_cause() -> None:
    with pytest.raises(RescueError) as error:
        transform_mdx("<Layout><Card>فقط ناوبری</Card></Layout>")

    assert error.value.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert error.value.message_fa


def test_an_empty_source_is_not_an_error() -> None:
    assert transform_mdx("   \n  ").markdown == ""


def test_the_transform_is_pure() -> None:
    source = read_fixture("overview__about.mdx")

    first, second = transform_mdx(source), transform_mdx(source)

    assert first == second


# --- The real corpus ---------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_no_jsx_survives_into_the_text_destined_for_embedding(name: str) -> None:
    prose = prose_of(transform_mdx(read_fixture(name)).markdown)

    assert "<" not in prose, f"{name}: JSX markup reached embedded text"
    assert "{" not in prose, f"{name}: a JSX expression reached embedded text"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_no_opening_tag_shape_survives_anywhere_in_prose(name: str) -> None:
    """The weaker invariant that must hold across the *whole* corpus.

    Four upstream documents legitimately contain a bare `<` in prose — version
    comparisons such as `redis < 7` in a tab label — so the strict assertion
    above is scoped to fixtures. What must never appear anywhere is `<` glued to
    an identifier or a slash, which is what an unstripped tag looks like.
    """
    prose = prose_of(transform_mdx(read_fixture(name)).markdown)

    assert re.search(r"<[A-Za-z/]", prose) is None


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_yields_a_title_and_text(name: str) -> None:
    result = transform_mdx(read_fixture(name))

    assert result.title
    assert len(result.markdown) > 200
    assert result.source_char_count > 0


def test_fixtures_span_several_top_level_sections() -> None:
    sections = {MANIFEST["documents"][name]["source_path"].split("/")[2] for name in FIXTURE_NAMES}

    assert len(sections) >= 5, sections
