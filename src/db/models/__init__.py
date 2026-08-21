"""Model registry.

Alembic autogenerate sees only what this module imports, so every model module
must be re-exported here or its table silently vanishes from migrations.
"""

from src.db.models.analytics import UsageEvent
from src.db.models.base import Base, TimestampMixin
from src.db.models.conversation import (
    AnonymousSession,
    Conversation,
    Feedback,
    Message,
    RequestJob,
)
from src.db.models.corpus import (
    EMBEDDING_DIM,
    Document,
    DocumentChunk,
    ImageAsset,
    IndexVersion,
)
from src.db.models.faq import FaqItem
from src.db.models.settings import RuntimeSetting

__all__ = [
    "EMBEDDING_DIM",
    "AnonymousSession",
    "Base",
    "Conversation",
    "Document",
    "DocumentChunk",
    "FaqItem",
    "Feedback",
    "ImageAsset",
    "IndexVersion",
    "Message",
    "RequestJob",
    "RuntimeSetting",
    "TimestampMixin",
    "UsageEvent",
]
