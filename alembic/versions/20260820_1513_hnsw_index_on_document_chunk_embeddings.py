"""hnsw index on document chunk embeddings

Cosine similarity is the exposed unit everywhere, so the index uses
`vector_cosine_ops` — an index built for a different operator class is simply
not used by the planner, and the query silently degrades to a sequential scan
over every chunk in every index version.

Written by hand: Alembic autogenerate has no notion of HNSW access methods or
their build parameters.

Revision ID: dbd77a4b7a1e
Revises: 4add8674d4f0
Create Date: 2026-08-20 15:13:27.693875
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "dbd77a4b7a1e"
down_revision: str | None = "4add8674d4f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# pgvector defaults. Final values are a measurement, not a guess — they get
# revisited once the first full ingestion establishes the real chunk count.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


def upgrade() -> None:
    op.execute(
        f"""
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
        """
    )
    # FAQ questions live in their own embedding space and are matched on every
    # request through the fast path; leaving that column unindexed would put a
    # sequential scan in front of the cheapest route in the product.
    op.execute(
        f"""
        CREATE INDEX ix_faq_items_embedding_hnsw
        ON faq_items
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_faq_items_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
