"""Ingestion services: MDX pre-pass and section-aware chunking.

The corpus is Next.js MDX whose section headings are `<Section id title />` JSX
components rather than Markdown headings, and whose **entire code content**
lives inside `<Highlight className="…">{`…`}</Highlight>` — there is not a
single Markdown fence in the upstream repository. Both facts make a
Markdown-only parser produce an undifferentiated, code-free blob per file.

Two stages, per docs/deployment.md §7:

1. `mdx.transform_mdx` — a pure JSX pre-pass producing clean Markdown plus the
   structure a citation needs, and a discarded-character ratio that turns
   upstream component drift into a metric change rather than silent decay.
2. `chunking.chunk_document` — `mistune` in AST mode, section-aware chunking,
   merge/split against configured bounds, metadata extraction.
"""

from __future__ import annotations

from src.services.ingestion.chunking import Chunk, chunk_document
from src.services.ingestion.mdx import (
    MdxDocument,
    MdxImage,
    MdxSection,
    transform_mdx,
)

__all__ = [
    "Chunk",
    "MdxDocument",
    "MdxImage",
    "MdxSection",
    "chunk_document",
    "transform_mdx",
]
