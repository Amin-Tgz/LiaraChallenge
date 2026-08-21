"""Section-aware chunking of the cleaned Markdown produced by the pre-pass.

Stage two of docs/deployment.md §7. `mistune` runs in AST mode
(`create_markdown(renderer=None)`) and owns block typing — it is the component
that knows a `#` inside a fenced shell snippet is a comment and not a heading —
while a fence-aware span scanner supplies the byte offsets mistune does not
expose, so `<Step>` regions recorded by the pre-pass can be honoured.

Three rules survive from the spec into the code, in this order:

1. **Sections are the chunk unit.** Each `<Section id …/>` carries its own
   anchor, so a citation is `{source_url}#{anchor}` with nothing inferred.
2. **Semantic units are never split.** A code block stays with the prose that
   explains it; an image stays with the step it illustrates. Those pairs become
   one indivisible *unit* before any size arithmetic happens.
3. **Sizes are configuration.** `chunk_min_tokens`, `chunk_target_tokens`,
   `chunk_max_tokens`, and `chunk_overlap_tokens` come from settings; the only
   chunk permitted outside the bounds is a document too small to reach the
   floor at all, which has no neighbour to merge with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import mistune
import tiktoken

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.normalization import normalize_text
from src.db.models.enums import ChunkContentType
from src.services.ingestion.mdx import MdxDocument

#: Public documentation origin. The repository path under `src/pages` is the URL
#: path, so `paas/django/getting-started.mdx` serves at
#: `https://docs.liara.ir/paas/django/getting-started`.
DOCS_BASE_URL = "https://docs.liara.ir"

#: Directory names under `src/pages/paas` that name a language runtime rather
#: than a framework. Taxonomy of the corpus itself, not a tunable threshold —
#: it changes only when upstream adds a platform directory.
_RUNTIMES = frozenset({"docker", "dotnet", "go", "java", "nodejs", "php", "python", "static"})
_FRAMEWORKS = frozenset(
    {"angular", "django", "flask", "laravel", "nextjs", "react", "vue", "netcore"}
)
#: Sections whose second path segment names a managed service.
_SERVICE_SECTIONS = frozenset(
    {
        "ai",
        "dbaas",
        "dns-management-system",
        "email-server",
        "iaas",
        "mirrors",
        "object-storage",
        "one-click-apps",
        "tv",
    }
)

_FENCE = re.compile(r"^(`{3,}|~{3,})")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_PERSIAN = re.compile(r"[؀-ۿ]")
#: A block that is nothing but an image is bound to whatever it illustrates.
_IMAGE_ONLY = re.compile(r"^(?:!\[[^\]]*\]\([^)\s]+\)\s*)+$")


@lru_cache(maxsize=1)
def _encoder() -> Any:
    # The embedding model is an OpenAI-compatible `text-embedding-3-large`, so
    # its tokenizer is the right ruler for the chunk bounds.
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


# --- Blocks ------------------------------------------------------------------


@dataclass(slots=True)
class _Block:
    start: int
    end: int
    text: str
    kind: str
    #: Heading level when ``kind == "heading"``, else 0.
    level: int = 0
    code_language: str = ""


def _split_blocks(markdown: str) -> list[_Block]:
    """Blank-line separated blocks with their offsets, respecting code fences."""
    blocks: list[_Block] = []
    lines = markdown.split("\n")
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1

    fence: str | None = None
    start_index: int | None = None
    for index, line in enumerate(lines):
        match = _FENCE.match(line.strip()) if fence is None else None
        if fence is None and match is not None:
            if start_index is None:
                start_index = index
            fence = match.group(1)[0] * 3
            continue
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        if not line.strip():
            if start_index is not None:
                blocks.append(_make_block(markdown, offsets, lines, start_index, index - 1))
                start_index = None
            continue
        if start_index is None:
            start_index = index
    if start_index is not None:
        blocks.append(_make_block(markdown, offsets, lines, start_index, len(lines) - 1))
    return blocks


def _make_block(
    markdown: str, offsets: list[int], lines: list[str], first: int, last: int
) -> _Block:
    start = offsets[first]
    end = offsets[last] + len(lines[last])
    return _Block(start=start, end=end, text=markdown[start:end], kind="paragraph")


def _apply_ast(markdown: str, blocks: list[_Block]) -> bool:
    """Type each block from mistune's AST. Returns whether the AST lined up.

    mistune decides what a block *is* — crucially, that a `#` line inside a
    fenced snippet is a shell comment and not a heading. When the token stream
    and the span scan disagree the caller falls back to regex typing and records
    the disagreement, because guessing silently is how a corpus change becomes a
    retrieval regression nobody sees.
    """
    tokens = [
        token
        for token in mistune.create_markdown(renderer=None)(markdown)
        if token.get("type") != "blank_line"
    ]
    if len(tokens) != len(blocks):
        _type_by_regex(blocks)
        return False
    for token, block in zip(tokens, blocks, strict=True):
        kind = token.get("type", "paragraph")
        attrs = token.get("attrs") or {}
        if kind == "heading":
            heading = _HEADING.match(block.text.strip())
            if heading is None:
                _type_by_regex(blocks)
                return False
            block.kind = "heading"
            block.level = int(attrs.get("level", 1))
        elif kind == "block_code":
            block.kind = "code"
            info = str(attrs.get("info") or "").strip().split()
            block.code_language = info[0] if info else ""
        elif kind == "block_quote":
            block.kind = "quote"
        elif kind == "list":
            block.kind = "list"
        elif kind == "thematic_break":
            block.kind = "rule"
        else:
            block.kind = "image" if _IMAGE_ONLY.match(block.text.strip()) else "paragraph"
            if block.text.lstrip().startswith("|"):
                block.kind = "table"
    return True


def _type_by_regex(blocks: list[_Block]) -> None:
    for block in blocks:
        stripped = block.text.strip()
        heading = _HEADING.match(stripped)
        if heading is not None:
            block.kind = "heading"
            block.level = len(heading.group(1))
        elif _FENCE.match(stripped):
            block.kind = "code"
            block.code_language = stripped.split("\n", 1)[0].lstrip("`~").strip()
        elif stripped.startswith(">"):
            block.kind = "quote"
        elif stripped.startswith("|"):
            block.kind = "table"
        elif _IMAGE_ONLY.match(stripped):
            block.kind = "image"
        elif stripped in {"---", "***", "___"}:
            block.kind = "rule"
        else:
            block.kind = "paragraph"


# --- Results -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable unit of evidence.

    Field names mirror `src.db.models.corpus.DocumentChunk` so persistence —
    task 6, not this one — is a field-for-field copy with no translation layer
    where a citation could drift.
    """

    ordinal: int
    text: str
    text_normalized: str
    token_count: int
    source_path: str
    source_url: str
    heading_anchor: str | None
    section_title: str | None
    breadcrumbs: list[str]
    content_type: str
    code_languages: list[str]
    images: list[dict[str, Any]]
    service: str | None
    runtime: str | None
    framework: str | None
    language: str
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def citation_url(self) -> str:
        """The deep link a citation resolves to: `{source_url}#{anchor}`."""
        if not self.heading_anchor:
            return self.source_url
        return f"{self.source_url}#{self.heading_anchor}"


# --- Path metadata -----------------------------------------------------------


def source_url_for(source_path: str, base_url: str = DOCS_BASE_URL) -> str:
    """Public URL of a repository path such as `src/pages/paas/about.mdx`."""
    path = source_path.replace("\\", "/").removeprefix("./")
    path = path.split("src/pages/", 1)[-1]
    path = re.sub(r"\.mdx?$", "", path)
    path = re.sub(r"/index$", "", path)
    return f"{base_url.rstrip('/')}/{path.strip('/')}"


def _path_metadata(source_path: str) -> tuple[list[str], str | None, str | None, str | None]:
    """Breadcrumbs plus the service, runtime, and framework a path implies."""
    path = source_path.replace("\\", "/").split("src/pages/", 1)[-1]
    segments = [part for part in re.sub(r"\.mdx?$", "", path).split("/") if part]
    section = segments[0] if segments else None
    second = segments[1] if len(segments) > 1 else None
    service = runtime = framework = None
    if section == "paas" and second is not None:
        if second in _RUNTIMES:
            runtime = second
        elif second in _FRAMEWORKS:
            framework = second
        service = "paas"
    elif section in _SERVICE_SECTIONS:
        service = second or section
    elif section is not None:
        service = section
    return segments, service, runtime, framework


def _language_of(text: str) -> str:
    persian = len(_PERSIAN.findall(text))
    letters = sum(1 for char in text if char.isalpha())
    return "fa" if letters and persian / letters >= 0.2 else "en"


# --- Units -------------------------------------------------------------------


@dataclass(slots=True)
class _Unit:
    """Blocks that must never be separated, with their combined token cost."""

    blocks: list[_Block]
    tokens: int
    is_step: bool = False


def _bind_units(blocks: list[_Block], step_spans: tuple[tuple[int, int], ...]) -> list[_Unit]:
    """Group a section's blocks into indivisible units.

    Code binds to the prose that introduces it (or, when the code opens the
    section, to the prose that follows). An image binds to whatever precedes it.
    Every block inside one `<Step>` region binds to the rest of that step.
    """
    units: list[_Unit] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind == "rule":
            index += 1
            continue
        region = next(
            (span for span in step_spans if span[0] <= block.start < span[1]),
            None,
        )
        if region is not None:
            group = []
            while index < len(blocks) and region[0] <= blocks[index].start < region[1]:
                group.append(blocks[index])
                index += 1
            units.append(_Unit(blocks=group, tokens=_tokens_of(group), is_step=True))
            continue

        group = [block]
        index += 1
        # Pull in the code and images that belong to this prose.
        while index < len(blocks) and blocks[index].kind in {"code", "image"}:
            group.append(blocks[index])
            index += 1
        if group[0].kind in {"code", "image"} and units:
            # The block opened the section, or followed another bound group:
            # attach it backwards so it is never stranded from its explanation.
            units[-1].blocks.extend(group)
            units[-1].tokens = _tokens_of(units[-1].blocks)
            continue
        units.append(_Unit(blocks=group, tokens=_tokens_of(group)))

    # A section that opens with code has no preceding prose to bind to, so the
    # explanation that follows is bound forward instead. The spec requires code
    # to stay with adjacent prose in either direction.
    if len(units) > 1 and all(block.kind in {"code", "image"} for block in units[0].blocks):
        units[1].blocks = units[0].blocks + units[1].blocks
        units[1].tokens = _tokens_of(units[1].blocks)
        units[1].is_step = units[0].is_step or units[1].is_step
        del units[0]
    return units


def _tokens_of(blocks: list[_Block]) -> int:
    return count_tokens("\n\n".join(block.text for block in blocks))


# --- Chunking ----------------------------------------------------------------


@dataclass(slots=True)
class _Section:
    title: str | None
    anchor: str | None
    level: int
    breadcrumbs: list[str]
    blocks: list[_Block]


def _sections_of(document: MdxDocument, blocks: list[_Block], title: str | None) -> list[_Section]:
    """Split blocks at heading boundaries, carrying each heading's anchor."""
    anchors = [section.anchor for section in document.sections]
    titles = [section.title for section in document.sections]
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    heading_index = 0
    current = _Section(title=title, anchor=None, level=0, breadcrumbs=[], blocks=[])
    for block in blocks:
        if block.kind != "heading":
            current.blocks.append(block)
            continue
        heading = _HEADING.match(block.text.strip())
        text = heading.group(2).strip() if heading else block.text.strip("# ").strip()
        anchor: str | None = None
        if heading_index < len(anchors) and titles[heading_index] == text:
            anchor = anchors[heading_index]
        elif text in titles:
            anchor = anchors[titles.index(text)]
        heading_index += 1
        while stack and stack[-1][0] >= block.level:
            stack.pop()
        breadcrumbs = [name for _, name in stack]
        stack.append((block.level, text))
        if current.blocks or current.title is None:
            sections.append(current)
        current = _Section(
            title=text,
            anchor=anchor,
            level=block.level,
            breadcrumbs=breadcrumbs,
            blocks=[],
        )
    sections.append(current)
    return [section for section in sections if section.blocks or section.title]


def _split_oversized(unit: _Unit, settings: Settings) -> list[list[_Block]]:
    """Split a single unit that cannot fit, keeping whole lines and overlapping."""
    text = "\n\n".join(block.text for block in unit.blocks)
    lines = text.split("\n")
    pieces: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        candidate = current + [line]
        if current and count_tokens("\n".join(candidate)) > settings.chunk_max_tokens:
            pieces.append(current)
            overlap: list[str] = []
            while current and count_tokens("\n".join(overlap)) < settings.chunk_overlap_tokens:
                overlap.insert(0, current.pop())
            current = overlap + [line]
        else:
            current = candidate
    if current:
        pieces.append(current)
    template = unit.blocks[0]
    return [
        [
            _Block(
                start=template.start,
                end=template.end,
                text="\n".join(piece),
                kind=template.kind,
                code_language=template.code_language,
            )
        ]
        for piece in pieces
        if "\n".join(piece).strip()
    ]


@dataclass(slots=True)
class _Candidate:
    """A chunk before the document-wide merge pass decides it is big enough."""

    blocks: list[_Block]
    section: _Section
    is_step: bool
    truncated_start: bool = False
    truncated_end: bool = False


def _body(blocks: list[_Block]) -> str:
    return "\n\n".join(block.text for block in blocks).strip()


def _chunk_text(doc_title: str | None, section: _Section, body: str) -> str:
    """Prefix the body with its breadcrumb so a chunk reads standalone."""
    line = " › ".join(part for part in (doc_title, section.title) if part)
    return f"{line}\n\n{body}" if line else body


def _pack(units: list[_Unit], section: _Section, settings: Settings) -> list[_Candidate]:
    """Greedily fill chunks to the configured target, splitting anything too big."""
    packed: list[_Candidate] = []
    current: list[_Block] = []
    current_step = False

    def flush() -> None:
        nonlocal current, current_step
        if current:
            packed.append(_Candidate(blocks=current, section=section, is_step=current_step))
            current = []
            current_step = False

    for unit in units:
        if unit.tokens > settings.chunk_max_tokens:
            flush()
            pieces = _split_oversized(unit, settings)
            packed.extend(
                _Candidate(
                    blocks=piece,
                    section=section,
                    is_step=unit.is_step,
                    truncated_start=index > 0,
                    truncated_end=index < len(pieces) - 1,
                )
                for index, piece in enumerate(pieces)
            )
            continue
        if current and _tokens_of(current) + unit.tokens > settings.chunk_target_tokens:
            flush()
        current.extend(unit.blocks)
        current_step = current_step or unit.is_step
    flush()
    return packed


def _merge_undersized(
    candidates: list[_Candidate], doc_title: str | None, settings: Settings
) -> list[_Candidate]:
    """Fold every below-floor chunk into a neighbour, across section boundaries.

    A trailing «همچنین بخوانید» section of thirty tokens is not independently
    meaningful, and merging only within its own section would leave it stored
    alone. The surviving citation belongs to whichever section contributes more
    text, so the anchor still points where most of the evidence came from.
    """

    def tokens(candidate: _Candidate) -> int:
        return count_tokens(_chunk_text(doc_title, candidate.section, _body(candidate.blocks)))

    def combined(left: _Candidate, right: _Candidate) -> int:
        section = left.section if tokens(left) >= tokens(right) else right.section
        return count_tokens(_chunk_text(doc_title, section, _body(left.blocks + right.blocks)))

    merged = list(candidates)
    while len(merged) > 1:
        target = next(
            (index for index, c in enumerate(merged) if tokens(c) < settings.chunk_min_tokens),
            None,
        )
        if target is None:
            break
        neighbours = [
            index
            for index in (target - 1, target + 1)
            if 0 <= index < len(merged)
            and combined(merged[min(index, target)], merged[max(index, target)])
            <= settings.chunk_max_tokens
        ]
        if not neighbours:
            break
        choice = min(neighbours, key=lambda index: tokens(merged[index]))
        first, second = merged[min(choice, target)], merged[max(choice, target)]
        merged[min(choice, target)] = _Candidate(
            blocks=first.blocks + second.blocks,
            section=first.section if tokens(first) >= tokens(second) else second.section,
            is_step=first.is_step or second.is_step,
            truncated_start=first.truncated_start,
            truncated_end=second.truncated_end,
        )
        del merged[max(choice, target)]
    return merged


def _step_spans(markdown: str, step_texts: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    """Locate each `<Step>` block's verbatim Markdown inside the document."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for text in step_texts:
        if not text:
            continue
        start = markdown.find(text, cursor)
        if start < 0:
            start = markdown.find(text)
        if start < 0:
            continue
        spans.append((start, start + len(text)))
        cursor = start + len(text)
    return tuple(spans)


def _content_type(blocks: list[_Block], is_step: bool) -> str:
    kinds = {block.kind for block in blocks}
    if is_step:
        return ChunkContentType.STEP
    if kinds == {"code"}:
        return ChunkContentType.CODE
    if kinds <= {"table"}:
        return ChunkContentType.TABLE
    if "code" in kinds and kinds - {"code", "image"}:
        return ChunkContentType.MIXED
    if "table" in kinds and len(kinds) > 1:
        return ChunkContentType.MIXED
    return ChunkContentType.PROSE


def chunk_document(
    document: MdxDocument,
    *,
    source_path: str,
    source_url: str | None = None,
    settings: Settings | None = None,
) -> list[Chunk]:
    """Split one pre-passed document into retrievable, citable chunks.

    Raises `RescueError(DOCUMENT_PARSE_FAILED)` when a document with text yields
    no chunk: an empty list here would be indistinguishable from a legitimately
    empty page, and the ingestion pipeline must be able to tell those apart.
    """
    settings = settings or get_settings()
    url = source_url or source_url_for(source_path, settings.docs_base_url)
    breadcrumb_path, service, runtime, framework = _path_metadata(source_path)

    blocks = _split_blocks(document.markdown)
    ast_aligned = _apply_ast(document.markdown, blocks)
    sections = _sections_of(document, blocks, document.title)
    steps = _step_spans(document.markdown, document.step_texts)
    images_by_url = {image.url: image for image in document.images}

    candidates: list[_Candidate] = []
    for section in sections:
        units = _bind_units(section.blocks, steps)
        if not units:
            if not section.title:
                continue
            # A heading with no body is still content — an FAQ page is a list of
            # questions. Emit it so the merge pass can fold it into a neighbour
            # rather than drop the only text on the page.
            heading = _Block(
                start=0,
                end=0,
                text="#" * max(section.level, 1) + " " + section.title,
                kind="heading",
                level=section.level,
            )
            units = [_Unit(blocks=[heading], tokens=count_tokens(heading.text))]
        candidates.extend(_pack(units, section, settings))

    chunks: list[Chunk] = []
    for candidate in _merge_undersized(candidates, document.title, settings):
        section = candidate.section
        body = _body(candidate.blocks)
        if not body:
            continue
        crumbs = [*breadcrumb_path[:-1]]
        if document.title:
            crumbs.append(document.title)
        crumbs.extend(section.breadcrumbs)
        if section.title and section.title not in crumbs:
            crumbs.append(section.title)
        text = _chunk_text(document.title, section, body)
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                text=text,
                text_normalized=normalize_text(text),
                token_count=count_tokens(text),
                source_path=source_path,
                source_url=url,
                heading_anchor=section.anchor,
                section_title=section.title,
                breadcrumbs=crumbs,
                content_type=str(_content_type(candidate.blocks, candidate.is_step)),
                code_languages=sorted(
                    {block.code_language for block in candidate.blocks if block.code_language}
                ),
                images=[
                    {
                        "url": image_url,
                        "alt": alt,
                        "ordinal": images_by_url[image_url].ordinal
                        if image_url in images_by_url
                        else index,
                        "heading_anchor": images_by_url[image_url].heading_anchor
                        if image_url in images_by_url
                        else section.anchor,
                    }
                    for index, (alt, image_url) in enumerate(_IMAGE.findall(body))
                ],
                service=service,
                runtime=runtime,
                framework=framework,
                language=_language_of(body),
                extra_metadata={
                    "heading_level": section.level,
                    "block_kinds": sorted({block.kind for block in candidate.blocks}),
                    "truncated_start": candidate.truncated_start,
                    "truncated_end": candidate.truncated_end,
                    # False means mistune's token stream and the span scan
                    # disagreed and block typing fell back to regex — a signal
                    # that the shape of the pre-pass output has moved.
                    "ast_aligned": ast_aligned,
                },
            )
        )

    if document.markdown.strip() and not chunks:
        raise RescueError(
            ErrorCode.DOCUMENT_PARSE_FAILED,
            detail="chunking produced no chunks from a document that has cleaned text",
            context={"source_path": source_path, "markdown_chars": len(document.markdown)},
        )
    return chunks
