"""The JSX pre-pass: MDX in, clean Markdown plus structure out.

Everything here is a pure function of the source string. Nothing is printed and
nothing is logged — the guardrail metrics (`discarded_char_ratio`,
`unrecognized_tags`) are returned so the caller decides what to record.

**Matching is on JSX tag names, never import paths.** The upstream repository is
internally inconsistent: `paas/about.mdx` imports `Tabs` from
`@/components/Common/tabs` while `paas/django/getting-started.mdx` imports the
same component from `@/components/Common/tab`. Tag names are stable; paths are
not.

Dispatch follows JSX's own rule — a capitalized tag is a component, a lowercase
tag is an HTML element — so `<Section …>` (a heading) and `<section>` (a plain
wrapper) cannot be confused.

Two corpus facts the transform table in docs/deployment.md §7 does not state,
both verified across all 1,143 upstream documents:

* The repository contains **zero** Markdown code fences. All 3,731 code blocks
  are ``<Highlight className="…">{`…`}</Highlight>``, so the code lives inside a
  JSX expression container. Dropping expression blocks wholesale — which §7
  prescribes — would discard every command and snippet in the corpus.
* `<Important>` is an inline badge (8,666 uses) and `<Highlight>` is a
  syntax-highlighted code block, not the blockquote-worthy callouts §7 groups
  them with. Only `<Alert>` is a callout.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from src.core.config import get_settings
from src.core.errors import ErrorCode, RescueError

# --- Source scanning ---------------------------------------------------------

_TAG_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$-]*")
_ATTR_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_.:$-]*")
#: Object-literal keys. Deliberately excludes `:` — which `_ATTR_NAME` allows
#: for namespaced JSX attributes — because a key regex that swallows its own
#: separator silently returns an empty object and drops every `<Tabs>` label,
#: every `<HighlightTabs>` snippet, and every `<Step>`.
_JS_KEY = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_STATEMENT = re.compile(r"[ \t]*(?:import|export)\b")
_QUOTES = "'\"`"

#: Markdown constructs that must keep their own line when a JSX text run is
#: reflowed. Everything else in a text run is soft-wrapped prose.
_BLOCK_LINE = re.compile(r"^(?:#{1,6} |[-*+] |\d+[.)] |> |\||```|---|===)")

#: Punctuation that must not be pushed away from the word it follows when an
#: inline component (a link, an `<Important>` badge) is stitched back into prose.
_CLINGING = re.compile(r"^[\s.,;:!?)\]}»،؛؟‌]")


def _skip_string(src: str, i: int) -> int:
    """Index just past the string or template literal starting at ``src[i]``."""
    quote = src[i]
    i += 1
    n = len(src)
    while i < n:
        char = src[i]
        if char == "\\":
            i += 2
            continue
        if quote == "`" and char == "$" and src.startswith("${", i):
            i = _skip_expression(src, i + 1)
            continue
        if char == quote:
            return i + 1
        i += 1
    return n


def _skip_expression(src: str, i: int) -> int:
    """Index just past the balanced ``{…}`` starting at ``src[i]``.

    Strings and template literals are skipped whole, so braces inside a shell
    snippet (``${LIARA_API_KEY}``) or a style object never unbalance the scan.
    """
    depth = 0
    n = len(src)
    while i < n:
        char = src[i]
        if char in _QUOTES:
            i = _skip_string(src, i)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _strip_statements(source: str) -> str:
    """Remove top-level ``import`` / ``export`` statements.

    Scanned rather than matched line-wise: several documents use multi-line
    brace imports (``import {\\n  GoContainer,\\n} from "react-icons/go"``).
    """
    out: list[str] = []
    i = 0
    n = len(source)
    at_line_start = True
    while i < n:
        if at_line_start:
            match = _STATEMENT.match(source, i)
            if match is not None:
                j = match.end()
                while j < n:
                    char = source[j]
                    if char in _QUOTES:
                        j = _skip_string(source, j)
                        continue
                    if char == "{":
                        j = _skip_expression(source, j)
                        continue
                    if char == "\n":
                        break
                    j += 1
                i = j + 1
                continue
        out.append(source[i])
        at_line_start = source[i] == "\n"
        i += 1
    return "".join(out)


# --- Node tree ---------------------------------------------------------------


@dataclass(slots=True)
class _Text:
    start: int
    end: int


@dataclass(slots=True)
class _Expr:
    """A ``{…}`` JSX expression container; ``start``/``end`` include the braces."""

    start: int
    end: int


@dataclass(slots=True)
class _Attr:
    start: int
    end: int
    #: ``"str"`` for a quoted value, ``"expr"`` for ``{…}``, ``"bare"`` otherwise.
    kind: str


@dataclass(slots=True)
class _Element:
    name: str
    attrs: dict[str, _Attr | None]
    children: list[_Node]
    start: int
    end: int


_Node = _Text | _Expr | _Element

#: HTML elements that never carry a closing tag.
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)


def _is_void(name: str) -> bool:
    """Void elements are HTML, so the test is case-sensitive.

    `<link>` closes itself; `<Link>` — next/link, 808 uses — does not. Folding
    case here silently emptied every `<Link>` in the corpus.
    """
    return name[:1].islower() and name in _VOID


def _parse_attrs(src: str, i: int) -> tuple[dict[str, _Attr | None], bool, int]:
    """Parse attributes up to ``>`` or ``/>``; returns (attrs, self_closing, end)."""
    attrs: dict[str, _Attr | None] = {}
    n = len(src)
    while i < n:
        while i < n and src[i].isspace():
            i += 1
        if i >= n:
            break
        if src.startswith("/>", i):
            return attrs, True, i + 2
        if src[i] == ">":
            return attrs, False, i + 1
        if src[i] == "{":  # spread attribute — carries no documentation text
            i = _skip_expression(src, i)
            continue
        match = _ATTR_NAME.match(src, i)
        if match is None:
            i += 1
            continue
        name = match.group(0)
        i = match.end()
        while i < n and src[i].isspace():
            i += 1
        if i >= n or src[i] != "=":
            attrs[name] = None
            continue
        i += 1
        while i < n and src[i].isspace():
            i += 1
        if i < n and src[i] in "'\"":
            end = _skip_string(src, i)
            attrs[name] = _Attr(i + 1, end - 1, "str")
            i = end
        elif i < n and src[i] == "{":
            end = _skip_expression(src, i)
            attrs[name] = _Attr(i + 1, end - 1, "expr")
            i = end
        else:
            start = i
            while i < n and not src[i].isspace() and src[i] not in ">/":
                i += 1
            attrs[name] = _Attr(start, i, "bare")
    return attrs, False, n


def _parse_children(src: str, i: int, stop: str | None) -> tuple[list[_Node], int]:
    """Parse nodes until the closing tag named ``stop``, or until end of input."""
    nodes: list[_Node] = []
    text_start = i
    n = len(src)

    def flush(upto: int) -> None:
        if upto > text_start:
            nodes.append(_Text(text_start, upto))

    while i < n:
        char = src[i]
        if char == "{":
            flush(i)
            end = _skip_expression(src, i)
            nodes.append(_Expr(i, end))
            i = text_start = end
            continue
        if char != "<":
            i += 1
            continue

        if src.startswith("<!--", i):
            flush(i)
            close = src.find("-->", i)
            i = text_start = n if close < 0 else close + 3
            continue
        if src.startswith("</", i):
            match = _TAG_NAME.match(src, i + 2)
            name = match.group(0) if match else ""
            close = src.find(">", i)
            end = n if close < 0 else close + 1
            flush(i)
            if stop is not None and name in (stop, ""):
                return nodes, end
            i = text_start = end  # a stray close tag for something we are not in
            continue
        if src.startswith("<>", i):
            flush(i)
            children, end = _parse_children(src, i + 2, "")
            nodes.append(_Element("", {}, children, i, end))
            i = text_start = end
            continue

        match = _TAG_NAME.match(src, i + 1)
        if match is None:
            i += 1  # a literal `<` in prose ("if x < y"), not markup
            continue
        name = match.group(0)
        attrs, self_closing, end = _parse_attrs(src, match.end())
        flush(i)
        if self_closing or _is_void(name):
            nodes.append(_Element(name, attrs, [], i, end))
            i = text_start = end
            continue
        children, end = _parse_children(src, end, name)
        nodes.append(_Element(name, attrs, children, i, end))
        i = text_start = end

    flush(n)
    return nodes, n


# --- JavaScript literal values ----------------------------------------------
#
# Four components carry their content in props rather than in children — `Tabs`,
# `HighlightTabs`, `Step`, and `Table` — so array and object literals have to be
# read rather than skipped. One small reader serves all four.


def _split_list(src: str, start: int, end: int, opener: str, closer: str) -> list[tuple[int, int]]:
    """Split the comma-separated items of a ``[…]`` or ``{…}`` literal."""
    i = start
    while i < end and src[i].isspace():
        i += 1
    if i >= end or src[i] != opener:
        return []
    i += 1
    items: list[tuple[int, int]] = []
    item_start = i
    depth = 0
    while i < end:
        char = src[i]
        if char in _QUOTES:
            i = _skip_string(src, i)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0 and char == closer:
                break
            depth -= 1
        elif char == "<" and depth == 0:
            match = _TAG_NAME.match(src, i + 1)
            if match is not None:
                _, closed, tag_end = _parse_attrs(src, match.end())
                if closed or _is_void(match.group(0)):
                    i = tag_end
                else:
                    _, i = _parse_children(src, tag_end, match.group(0))
                continue
            if src.startswith("<>", i):
                _, i = _parse_children(src, i + 2, "")
                continue
        elif char == "," and depth == 0:
            if src[item_start:i].strip():
                items.append((item_start, i))
            item_start = i + 1
        i += 1
    if src[item_start:i].strip():
        items.append((item_start, i))
    return items


def _object_keys(src: str, start: int, end: int) -> dict[str, tuple[int, int]]:
    """Read an object literal into ``key -> value span``."""
    keys: dict[str, tuple[int, int]] = {}
    for item_start, item_end in _split_list(src, start, end, "{", "}"):
        i = item_start
        while i < item_end and src[i].isspace():
            i += 1
        if i < item_end and src[i] in "'\"":
            key_end = _skip_string(src, i)
            key = src[i + 1 : key_end - 1]
            i = key_end
        else:
            match = _JS_KEY.match(src, i)
            if match is None or match.end() > item_end:
                continue
            key = match.group(0)
            i = match.end()
        while i < item_end and src[i].isspace():
            i += 1
        if i < item_end and src[i] == ":":
            keys[key] = (i + 1, item_end)
    return keys


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "`": "`", "$": "$", "\\": "\\", "'": "'", '"': '"'}


def _literal(src: str, start: int, end: int) -> str | None:
    """The text of the string or template literal spanning ``[start, end)``.

    ``None`` when the span is not a bare literal — an identifier, a call, a JSX
    element — which is how callers tell content apart from computed markup.
    """
    i = start
    while i < end and src[i].isspace():
        i += 1
    j = end
    while j > i and src[j - 1].isspace():
        j -= 1
    if j - i < 2 or src[i] not in _QUOTES or _skip_string(src, i) != j:
        return None
    raw = src[i + 1 : j - 1]
    out: list[str] = []
    k = 0
    while k < len(raw):
        if raw[k] == "\\" and k + 1 < len(raw):
            out.append(_ESCAPES.get(raw[k + 1], raw[k + 1]))
            k += 2
            continue
        out.append(raw[k])
        k += 1
    return "".join(out)


def _unwrap_parens(src: str) -> str:
    """Strip the parentheses JSX props wrap multi-line elements in."""
    text = src.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        balanced = True
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(text) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        text = text[1:-1].strip()
    return text


# --- Tag classification ------------------------------------------------------

#: Components that exist to navigate or decorate. Their text is a label, never
#: documentation, so it is dropped and counted as discarded.
_DROP_COMPONENTS = frozenset(
    {
        "Card",
        "Button",
        "PlatformIcon",
        "ThemePlatformIcon",
        "Asciinema",
        "IconContainer",
        "PageActionButtons",
        "EditOnGitHubLink",
        "NextPage",
        "Lightbox",
    }
)

#: Rendered as a check mark rather than dropped: in `<Table>` support matrices
#: these components *are* the cell value, and an empty cell inverts the meaning.
_TICK_COMPONENTS = frozenset({"TickIcon", "TickBadge"})

#: Page metadata rather than content: dropped, and excluded from the ratio so a
#: short document is not flagged merely for carrying a `<Head>`.
_METADATA_TAGS = frozenset({"head", "style", "script", "meta", "title", "link", "noscript"})

#: react-icons components, e.g. `GoArrowLeft`. Matched by shape, not import path.
_ICON_COMPONENT = re.compile(r"^(?:Go|Fa|Md|Ai|Bi|Bs|Fi|Hi|Io|Ri|Si|Ti|Vsc)[A-Z0-9]")

#: Media elements: no text of their own, and no alt attribute to salvage.
_MEDIA_TAGS = frozenset({"video", "audio", "iframe", "canvas", "svg", "path", "object", "embed"})

_BLOCK_HTML = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "aside",
        "header",
        "footer",
        "figure",
        "figcaption",
        "details",
        "summary",
        "form",
        "fieldset",
        "nav",
        "dl",
        "dd",
        "dt",
    }
)
_INLINE_HTML = frozenset(
    {
        "span",
        "b",
        "strong",
        "i",
        "em",
        "u",
        "small",
        "sub",
        "sup",
        "mark",
        "abbr",
        "font",
        "label",
        "cite",
        "kbd",
        "samp",
        "var",
        "s",
        "q",
        "time",
        "big",
        "center",
    }
)
_HEADING_HTML = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


# --- Output ------------------------------------------------------------------


class _Writer:
    """Appends Markdown while owning its own blank-line discipline.

    No post-processing pass runs over the finished string, so offsets recorded
    during rendering — the `<Step>` regions — stay valid.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._pending_block = False

    @property
    def length(self) -> int:
        return len(self._buf)

    def block(self) -> None:
        """Request a paragraph break before whatever is written next."""
        if self._buf:
            self._pending_block = True

    def _settle(self) -> None:
        if self._pending_block and self._buf:
            self._buf = self._buf.rstrip("\n") + "\n\n"
        self._pending_block = False

    def text(self, value: str) -> None:
        if not value:
            return
        self._settle()
        if self._buf and not self._buf[-1].isspace() and not _CLINGING.match(value):
            self._buf += " "
        self._buf += value

    def raw_block(self, value: str) -> None:
        """Emit ``value`` verbatim as a block of its own."""
        value = value.strip()
        if not value:
            return
        self.block()
        self._settle()
        self._buf += value
        self.block()

    def newline(self) -> None:
        if self._buf and not self._buf.endswith("\n"):
            self._buf += "\n"

    def slice(self, start: int, end: int) -> str:
        return self._buf[start:end]

    def result(self) -> str:
        return self._buf.rstrip()


# --- Results -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MdxSection:
    """One emitted heading, in document order.

    ``anchor`` is present only for headings that came from ``<Section id …/>``;
    a plain Markdown heading has none, and its chunks cite the page itself.
    """

    title: str
    level: int
    anchor: str | None = None


@dataclass(frozen=True, slots=True)
class MdxImage:
    url: str
    alt: str
    ordinal: int
    heading_anchor: str | None = None


@dataclass(frozen=True, slots=True)
class MdxDocument:
    markdown: str
    title: str | None
    sections: tuple[MdxSection, ...]
    images: tuple[MdxImage, ...]
    code_languages: tuple[str, ...]
    #: The exact Markdown of each `<Step>` block, in document order. Identified
    #: by text rather than by offset because most steps are rendered inside a
    #: `<Tabs content={…}>` prop, whose buffer is private; the text is emitted
    #: verbatim into `markdown`, so chunking can locate it and keep the step
    #: whole with its images and its code.
    step_texts: tuple[str, ...]
    source_char_count: int
    content_char_count: int
    discarded_char_count: int
    discarded_char_ratio: float
    flagged_for_review: bool
    #: JSX tags the transform has no rule for, by frequency. A new upstream
    #: component appears here before it appears as a retrieval regression.
    unrecognized_tags: Mapping[str, int]


@dataclass(slots=True)
class _State:
    src: str
    writer: _Writer = field(default_factory=_Writer)
    sections: list[MdxSection] = field(default_factory=list)
    images: list[MdxImage] = field(default_factory=list)
    code_languages: list[str] = field(default_factory=list)
    step_texts: list[str] = field(default_factory=list)
    unrecognized: Counter[str] = field(default_factory=Counter)
    title: str | None = None
    kept: int = 0
    discarded: int = 0
    current_anchor: str | None = None

    def absorb(self, other: _State) -> None:
        """Fold a nested render's structure and counters back into this one."""
        self.sections.extend(other.sections)
        self.images.extend(other.images)
        self.code_languages.extend(other.code_languages)
        self.unrecognized.update(other.unrecognized)
        self.step_texts.extend(other.step_texts)
        self.kept += other.kept
        self.discarded += other.discarded


# --- Transform ---------------------------------------------------------------


def _content_len(src: str, nodes: list[_Node]) -> int:
    """Content characters inside ``nodes``, ignoring tag markup and attributes."""
    total = 0
    for node in nodes:
        if isinstance(node, _Text):
            total += len(src[node.start : node.end].strip())
        elif isinstance(node, _Expr):
            total += len(src[node.start + 1 : node.end - 1].strip())
        else:
            total += _content_len(src, node.children)
    return total


def _flow(text: str) -> str:
    """Reflow a JSX text run into Markdown.

    JSX wraps prose at arbitrary columns and indents it inside markup. Soft
    wraps are joined, blank lines stay paragraph breaks, and a line opening a
    Markdown block construct keeps its own line.
    """
    rendered_paragraphs: list[str] = []
    for paragraph in re.split(r"\n[ \t]*\n", text):
        lines = [line.strip() for line in paragraph.split("\n")]
        lines = [line for line in lines if line]
        if not lines:
            continue
        buffer: list[str] = []
        rendered: list[str] = []
        for line in lines:
            if _BLOCK_LINE.match(line):
                if buffer:
                    rendered.append(" ".join(buffer))
                    buffer = []
                rendered.append(line)
            else:
                buffer.append(line)
        if buffer:
            rendered.append(" ".join(buffer))
        rendered_paragraphs.append("\n".join(rendered))
    return "\n\n".join(rendered_paragraphs)


def _fence(code: str, language: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", code)), default=0)
    ticks = "`" * max(3, longest + 1)
    return ticks + language + "\n" + code.strip("\n") + "\n" + ticks


def _attr_text(state: _State, attr: _Attr | None) -> str:
    """An attribute value as plain text; a computed expression yields ``""``."""
    if attr is None:
        return ""
    if attr.kind == "str":
        return state.src[attr.start : attr.end].strip()
    if attr.kind == "bare":
        return state.src[attr.start : attr.end].strip()
    literal = _literal(state.src, attr.start, attr.end)
    return literal.strip() if literal is not None else ""


def _emit_heading(state: _State, title: str, level: int, anchor: str | None) -> None:
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return
    state.sections.append(MdxSection(title=title, level=level, anchor=anchor))
    state.writer.raw_block("#" * min(level, 6) + " " + title)
    state.kept += len(title)


_MD_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def _record_markdown_headings(state: _State, flowed: str) -> None:
    """Register plain Markdown headings alongside `<Section>`-derived ones.

    Most pages open with a Markdown `# title` and several use `<h3>` inline, so
    the anchor sequence would otherwise have holes and chunking could not line
    headings up with their anchors positionally.
    """
    for match in _MD_HEADING.finditer(flowed):
        state.sections.append(
            MdxSection(title=match.group(2).strip(), level=len(match.group(1)), anchor=None)
        )


def _render(state: _State, nodes: list[_Node]) -> None:
    for node in nodes:
        if isinstance(node, _Text):
            raw = state.src[node.start : node.end]
            flowed = _flow(raw)
            if flowed:
                _record_markdown_headings(state, flowed)
                if "\n" in flowed or _BLOCK_LINE.match(flowed):
                    state.writer.raw_block(flowed)
                else:
                    state.writer.text(flowed)
                state.kept += len(raw.strip())
            continue
        if isinstance(node, _Expr):
            _render_expr(state, node)
            continue
        _render_element(state, node)


def _render_expr(state: _State, node: _Expr) -> None:
    inner_start, inner_end = node.start + 1, node.end - 1
    value = _literal(state.src, inner_start, inner_end)
    if value is not None:
        flowed = _flow(value)
        if flowed:
            if "\n" in flowed:
                state.writer.raw_block(flowed)
            else:
                state.writer.text(flowed)
        state.kept += len(value.strip())
        return
    body = state.src[inner_start:inner_end].strip()
    if body.startswith("/*") and body.endswith("*/"):
        # A JSX comment: content upstream deliberately disabled. Dropping it is
        # correct and must not count against the ratio, or a page with one large
        # commented-out block reads as catastrophic content loss.
        return
    # A computed expression: the `.map()` grids that render navigation cards,
    # icon props, conditionals. No documentation text survives evaluation.
    state.discarded += len(body)


def _render_isolated(state: _State, source: str, nodes: list[_Node]) -> str:
    """Render ``nodes`` into a private buffer, folding structure back into ``state``."""
    nested = _State(src=source)
    nested.current_anchor = state.current_anchor
    _render(nested, nodes)
    state.absorb(nested)
    return nested.writer.result()


def _inner_text(state: _State, node: _Element) -> str:
    return _render_isolated(state, state.src, node.children)


def _render_element(state: _State, node: _Element) -> None:  # noqa: C901 - one rule per tag
    name = node.name

    if name == "":  # `<>…</>` fragment
        _render(state, node.children)
        return
    if name[0].isupper():
        _render_component(state, node)
        return

    lowered = name.lower()
    if lowered in _MEDIA_TAGS:
        state.discarded += _content_len(state.src, node.children)
        return
    if lowered in _METADATA_TAGS:
        if lowered == "head":
            match = re.search(r"<title>(.*?)</title>", state.src[node.start : node.end], re.S)
            if match and state.title is None:
                state.title = re.sub(r"\s+", " ", match.group(1)).strip()
        return  # metadata: dropped, and deliberately outside the ratio

    if lowered == "br":
        state.writer.newline()
        return
    if lowered == "hr":
        state.writer.raw_block("---")
        return
    if lowered == "img":
        _emit_image(
            state,
            _attr_text(state, node.attrs.get("src")),
            _attr_text(state, node.attrs.get("alt")),
        )
        return
    if lowered in _HEADING_HTML:
        _emit_heading(state, _inner_text(state, node), _HEADING_HTML[lowered], None)
        return
    if lowered == "a":
        _emit_link(state, _attr_text(state, node.attrs.get("href")), node)
        return
    if lowered == "blockquote":
        _emit_quote(state, _inner_text(state, node))
        return
    if lowered in {"pre", "code"}:
        body = _inner_text(state, node)
        if "\n" in body:
            state.writer.raw_block(_fence(body, ""))
        elif body:
            state.writer.text("`" + body + "`")
        return
    if lowered in {"ul", "ol"}:
        _emit_list(state, node, ordered=lowered == "ol")
        return
    if lowered == "li":
        body = _inner_text(state, node).replace("\n", " ").strip()
        if body:
            state.writer.raw_block("- " + body)
        return
    if lowered in {"table", "thead", "tbody", "tfoot"}:
        _render(state, node.children)
        return
    if lowered == "tr":
        cells = [
            _inner_text(state, cell).replace("\n", " ").strip()
            for cell in node.children
            if isinstance(cell, _Element) and cell.name.lower() in {"td", "th"}
        ]
        if cells:
            state.writer.raw_block("| " + " | ".join(cells) + " |")
        return
    if lowered in {"td", "th"}:
        state.writer.text(_inner_text(state, node))
        return
    if lowered in _BLOCK_HTML:
        state.writer.block()
        _render(state, node.children)
        state.writer.block()
        return
    if lowered in _INLINE_HTML:
        _render(state, node.children)
        return

    state.unrecognized[name] += 1
    _render(state, node.children)


def _render_component(state: _State, node: _Element) -> None:  # noqa: C901 - one rule per tag
    name = node.name

    if name in _TICK_COMPONENTS:
        state.writer.text("✔")
        return
    if name in _DROP_COMPONENTS or _ICON_COMPONENT.match(name):
        state.discarded += _content_len(state.src, node.children)
        return
    if name in {"Layout", "Fragment", "React.Fragment"}:
        _render(state, node.children)
        return

    if name == "Head":
        # next/head. Page metadata, not content: the `<title>` is the document
        # title and everything else is Open Graph markup. Excluded from the
        # discard ratio so a short page is not flagged for having a head.
        match = re.search(r"<title>(.*?)</title>", state.src[node.start : node.end], re.S)
        if match and state.title is None:
            state.title = re.sub(r"\s+", " ", match.group(1)).strip()
        return

    if name == "Section":
        anchor = _attr_text(state, node.attrs.get("id")) or None
        heading_tag = _attr_text(state, node.attrs.get("headingTag")).lower()
        _emit_heading(
            state,
            _attr_text(state, node.attrs.get("title")),
            _HEADING_HTML.get(heading_tag, 2),
            anchor,
        )
        previous, state.current_anchor = state.current_anchor, anchor
        _render(state, node.children)
        state.current_anchor = previous
        return

    if name == "Highlight":
        _emit_highlight(state, node)
        return
    if name == "HighlightTabs":
        _emit_highlight_tabs(state, node)
        return
    if name == "Tabs":
        _emit_tabs(state, node)
        return
    if name == "Step":
        _emit_steps(state, node)
        return
    if name == "Table":
        _emit_table(state, node)
        return
    if name == "Alert":
        _emit_quote(state, _inner_text(state, node))
        return

    if name == "Important":
        body = _inner_text(state, node).strip()
        if not body:
            return
        state.writer.text(body if "\n" in body or "`" in body else "`" + body + "`")
        return

    if name == "Link":
        _emit_link(state, _attr_text(state, node.attrs.get("href")), node)
        return
    if name in {"LightboxImage", "Image"}:
        _emit_image(
            state,
            _attr_text(state, node.attrs.get("src")),
            _attr_text(state, node.attrs.get("alt")),
        )
        return

    if name == "QuestionBox":
        # The answer is a JSX fragment passed as a prop, not children, so it has
        # to be rendered rather than read as an attribute string.
        question = _attr_text(state, node.attrs.get("question"))
        answer_attr = node.attrs.get("answer")
        answer = (
            _read_value(state, (answer_attr.start, answer_attr.end))
            if answer_attr is not None
            else ""
        )
        if question:
            _emit_heading(state, question, 3, _attr_text(state, node.attrs.get("id")) or None)
        if answer.strip():
            state.writer.raw_block(answer)
        return

    state.unrecognized[name] += 1
    _render(state, node.children)


# --- Component emitters ------------------------------------------------------


def _emit_link(state: _State, href: str, node: _Element) -> None:
    label = _inner_text(state, node).replace("\n", " ").strip()
    if not label:
        return
    state.writer.text("[" + label + "](" + href + ")" if href else label)


def _emit_image(state: _State, url: str, alt: str) -> None:
    if not url:
        return
    alt = re.sub(r"\s+", " ", alt).strip()
    state.images.append(
        MdxImage(url=url, alt=alt, ordinal=len(state.images), heading_anchor=state.current_anchor)
    )
    state.writer.raw_block("![" + alt + "](" + url + ")")
    state.kept += len(alt)


def _emit_quote(state: _State, body: str) -> None:
    body = body.strip()
    if not body:
        return
    quoted = "\n".join("> " + line if line.strip() else ">" for line in body.split("\n"))
    state.writer.raw_block(quoted)


def _emit_list(state: _State, node: _Element, *, ordered: bool) -> None:
    lines: list[str] = []
    for child in node.children:
        if not isinstance(child, _Element) or child.name.lower() != "li":
            continue
        body = _inner_text(state, child).replace("\n", " ").strip()
        if not body:
            continue
        lines.append(f"{len(lines) + 1}. {body}" if ordered else "- " + body)
    if lines:
        state.writer.raw_block("\n".join(lines))


def _code_from_children(state: _State, node: _Element) -> str | None:
    """The template literal inside `<Highlight>` — where all corpus code lives."""
    for child in node.children:
        if isinstance(child, _Expr):
            value = _literal(state.src, child.start + 1, child.end - 1)
            if value is not None:
                return value
    text = "".join(
        state.src[child.start : child.end] for child in node.children if isinstance(child, _Text)
    )
    return text if text.strip() else None


def _emit_highlight(state: _State, node: _Element) -> None:
    language = _attr_text(state, node.attrs.get("className")).strip()
    code = _code_from_children(state, node)
    if code is None or not code.strip():
        state.discarded += _content_len(state.src, node.children)
        return
    if language:
        state.code_languages.append(language)
    state.writer.raw_block(_fence(code, language))
    state.kept += len(code.strip())


def _read_value(state: _State, span: tuple[int, int] | None) -> str:
    """A JS prop value as Markdown: literals kept, JSX rendered, computation dropped."""
    if span is None:
        return ""
    literal = _literal(state.src, span[0], span[1])
    if literal is not None:
        state.kept += len(literal.strip())
        return literal
    raw = _unwrap_parens(state.src[span[0] : span[1]])
    if "<" in raw:
        nodes, _ = _parse_children(raw, 0, None)
        return _render_isolated(state, raw, nodes)
    state.discarded += len(raw.strip())
    return ""


def _emit_highlight_tabs(state: _State, node: _Element) -> None:
    attr = node.attrs.get("tabs")
    if attr is None:
        state.discarded += _content_len(state.src, node.children)
        return
    for start, end in _split_list(state.src, attr.start, attr.end, "[", "]"):
        keys = _object_keys(state.src, start, end)
        label_span = keys.get("label")
        label = (_literal(state.src, *label_span) or "").strip() if label_span else ""
        language_span = keys.get("language")
        language = (_literal(state.src, *language_span) or "").strip() if language_span else ""
        code_span = keys.get("code")
        code = _literal(state.src, *code_span) if code_span else None
        if label:
            state.writer.raw_block("**" + label + "**")
            state.kept += len(label)
        if code and code.strip():
            if language:
                state.code_languages.append(language)
            state.writer.raw_block(_fence(code, language))
            state.kept += len(code.strip())


def _emit_tabs(state: _State, node: _Element) -> None:
    tabs_attr = node.attrs.get("tabs")
    content_attr = node.attrs.get("content")
    labels: list[str] = []
    if tabs_attr is not None:
        for start, end in _split_list(state.src, tabs_attr.start, tabs_attr.end, "[", "]"):
            literal = _literal(state.src, start, end)
            if literal is not None:
                labels.append(literal.strip())
                continue
            label_span = _object_keys(state.src, start, end).get("label")
            labels.append((_literal(state.src, *label_span) or "").strip() if label_span else "")
    bodies: list[tuple[int, int]] = []
    if content_attr is not None:
        bodies = _split_list(state.src, content_attr.start, content_attr.end, "[", "]")
    if not bodies:
        # A children-style `<Tabs>…</Tabs>`, or content we could not pair: keep
        # the text rather than lose it.
        for label in labels:
            if label:
                state.writer.raw_block("**" + label + "**")
                state.kept += len(label)
        _render(state, node.children)
        return
    for index, span in enumerate(bodies):
        label = labels[index] if index < len(labels) else ""
        if label:
            state.writer.raw_block("**" + label + "**")
            state.kept += len(label)
        body = _read_value(state, span)
        if body:
            state.writer.raw_block(body)


def _emit_steps(state: _State, node: _Element) -> None:
    attr = node.attrs.get("steps")
    if attr is None:
        _render(state, node.children)
        return
    start_offset = state.writer.length
    for item_start, item_end in _split_list(state.src, attr.start, attr.end, "[", "]"):
        keys = _object_keys(state.src, item_start, item_end)
        number_span = keys.get("step")
        number = (_literal(state.src, *number_span) or "").strip() if number_span else ""
        body = _read_value(state, keys.get("content")).strip()
        if number:
            state.writer.raw_block("**" + number + "**")
            state.kept += len(number)
        if body:
            state.writer.raw_block(body)
    end_offset = state.writer.length
    step_text = state.writer.slice(start_offset, end_offset).strip()
    if step_text:
        state.step_texts.append(step_text)


def _emit_table(state: _State, node: _Element) -> None:
    headers_attr = node.attrs.get("headers")
    data_attr = node.attrs.get("data")
    headers: list[str] = []
    if headers_attr is not None:
        headers = [
            _read_value(state, span).replace("\n", " ").strip()
            for span in _split_list(state.src, headers_attr.start, headers_attr.end, "[", "]")
        ]
    rows: list[list[str]] = []
    if data_attr is not None:
        for row in _split_list(state.src, data_attr.start, data_attr.end, "[", "]"):
            rows.append(
                [
                    _read_value(state, cell).replace("\n", " ").strip() or "-"
                    for cell in _split_list(state.src, row[0], row[1], "[", "]")
                ]
            )
    if not headers and not rows:
        state.discarded += _content_len(state.src, node.children)
        return
    width = max([len(headers), *[len(row) for row in rows]])
    headers = headers + [""] * (width - len(headers))
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row + ["-"] * (width - len(row))) + " |")
    state.writer.raw_block("\n".join(lines))


# --- Entry point -------------------------------------------------------------


def transform_mdx(source: str, *, discard_ratio_threshold: float | None = None) -> MdxDocument:
    """Convert one MDX document into clean Markdown plus its citation structure.

    Pure: identical input always yields identical output, and nothing is logged
    or printed. `discarded_char_ratio` and `unrecognized_tags` are the upstream
    drift guardrail and are returned for the caller to record.

    Raises `RescueError(DOCUMENT_PARSE_FAILED)` when a non-empty source yields
    no indexable text — an empty result must never be mistaken for an empty file.
    """
    if discard_ratio_threshold is None:
        discard_ratio_threshold = get_settings().ingest_discard_ratio_threshold

    body = _strip_statements(source)
    state = _State(src=body)
    nodes, _ = _parse_children(body, 0, None)
    _render(state, nodes)

    markdown = state.writer.result()
    content_total = state.kept + state.discarded
    ratio = (state.discarded / content_total) if content_total else 0.0

    if source.strip() and not markdown:
        raise RescueError(
            ErrorCode.DOCUMENT_PARSE_FAILED,
            detail="the MDX pre-pass produced no text from a non-empty source document",
            context={
                "source_char_count": len(source),
                "unrecognized_tags": dict(state.unrecognized),
            },
        )

    # Ordinals are assigned here, not at append time: images inside a `<Tabs>`
    # or `<Step>` prop are rendered in a private state whose counter starts at
    # zero, so numbering them locally would collide across the document.
    images = tuple(
        MdxImage(url=image.url, alt=image.alt, ordinal=index, heading_anchor=image.heading_anchor)
        for index, image in enumerate(state.images)
    )

    title = state.title
    if title is None:
        heading = next((section for section in state.sections if section.level == 1), None)
        title = heading.title if heading else None

    return MdxDocument(
        markdown=markdown,
        title=title,
        sections=tuple(state.sections),
        images=images,
        code_languages=tuple(dict.fromkeys(state.code_languages)),
        step_texts=tuple(state.step_texts),
        source_char_count=len(source),
        content_char_count=content_total,
        discarded_char_count=state.discarded,
        discarded_char_ratio=round(ratio, 6),
        flagged_for_review=ratio > discard_ratio_threshold,
        unrecognized_tags=dict(state.unrecognized.most_common()),
    )
