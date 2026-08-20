"""Acquiring the documentation corpus and deciding what is in scope.

The corpus is someone else's repository. Everything here is therefore built
around a single question the rest of the pipeline needs answered exactly: *which
commit is this, and which files does it contain that we care about?* The commit
SHA is recorded on the index version, which is what makes a later "has anything
changed?" a cheap comparison instead of a full re-embed.
"""

from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger

logger = get_logger(__name__)

#: Content lives under this prefix in the upstream repository.
CONTENT_ROOT = "src/pages"
#: Only MDX carries documentation prose; `.js` files under the same tree are
#: Next.js plumbing.
CONTENT_SUFFIX = ".mdx"

_GIT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One in-scope file, with the hash that drives change detection."""

    #: Repository-relative, POSIX separators — the identity used across index
    #: versions, so it must not vary with the host filesystem.
    source_path: str
    #: Top-level section: `paas`, `dbaas`, `references`, …
    section: str
    text: str
    content_hash: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class Checkout:
    """A materialized corpus at one commit."""

    path: Path
    commit: str
    repo_url: str
    branch: str


def _run_git(*args: str, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 — fixed executable, no shell
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as err:
        raise RescueError(
            ErrorCode.INGESTION_SOURCE_UNAVAILABLE,
            detail="git is not installed on this host",
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RescueError(
            ErrorCode.INGESTION_SOURCE_UNAVAILABLE,
            detail=f"git {args[0]} exceeded {_GIT_TIMEOUT_SECONDS}s",
        ) from err
    if completed.returncode != 0:
        # The stderr is operator context, never user-facing text.
        raise RescueError(
            ErrorCode.INGESTION_SOURCE_UNAVAILABLE,
            detail=f"git {args[0]} failed: {completed.stderr.strip()[:500]}",
        )
    return completed.stdout.strip()


def fetch_corpus(settings: Settings | None = None) -> Checkout:
    """Clone or update the configured repository and pin its commit.

    Kept as a cache between runs: the common case is that nothing upstream
    changed, and that case should cost a fetch, not a clone.
    """
    settings = settings or get_settings()
    destination = Path(settings.docs_cache_dir).expanduser().resolve()

    if (destination / ".git").is_dir():
        _run_git("remote", "set-url", "origin", settings.docs_repo_url, cwd=destination)
        _run_git("fetch", "--depth", "1", "origin", settings.docs_repo_branch, cwd=destination)
        _run_git("checkout", "--force", "FETCH_HEAD", cwd=destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            "clone",
            "--depth",
            "1",
            "--branch",
            settings.docs_repo_branch,
            settings.docs_repo_url,
            str(destination),
        )

    commit = _run_git("rev-parse", "HEAD", cwd=destination)
    logger.info(
        "corpus checked out",
        extra={
            "repo": settings.docs_repo_url,
            "branch": settings.docs_repo_branch,
            "commit": commit,
        },
    )
    return Checkout(
        path=destination,
        commit=commit,
        repo_url=settings.docs_repo_url,
        branch=settings.docs_repo_branch,
    )


def content_hash(text: str) -> str:
    """Identity of a document's content, independent of where it came from."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def in_scope(source_path: str, settings: Settings | None = None) -> bool:
    """Whether a repository-relative path should be indexed.

    Scope is configuration: narrowing `INGEST_SECTIONS` or adding an exclude
    glob changes what is indexed with no code change, which is what makes scope
    the schedule's pressure valve rather than a refactor.
    """
    settings = settings or get_settings()
    if not source_path.startswith(f"{CONTENT_ROOT}/") or not source_path.endswith(CONTENT_SUFFIX):
        return False

    relative = source_path[len(CONTENT_ROOT) + 1 :]
    sections = settings.ingest_section_list
    if sections:
        section = relative.split("/", 1)[0]
        if section not in sections:
            return False

    return all(
        not fnmatch.fnmatch(source_path, glob) and not fnmatch.fnmatch(relative, glob)
        for glob in settings.ingest_exclude_glob_list
    )


def section_of(source_path: str) -> str:
    """Top-level section of an in-scope path.

    A file directly under the content root (`src/pages/index.mdx`) belongs to no
    section; it is reported as `overview` rather than silently taking the file
    name as a section.
    """
    relative = source_path[len(CONTENT_ROOT) + 1 :]
    head, _, tail = relative.partition("/")
    return head if tail else "overview"


def discover_documents(
    checkout: Checkout, settings: Settings | None = None
) -> list[SourceDocument]:
    """Read every in-scope document at this checkout.

    Files are read one at a time and returned as text rather than handles: the
    worker has 1 GB and the corpus has over a thousand files, so nothing here
    may hold the whole tree open at once.
    """
    settings = settings or get_settings()
    root = checkout.path / CONTENT_ROOT
    if not root.is_dir():
        raise RescueError(
            ErrorCode.INGESTION_SOURCE_UNAVAILABLE,
            detail=f"{CONTENT_ROOT} does not exist in {checkout.repo_url}@{checkout.commit}",
        )

    documents: list[SourceDocument] = []
    for path in sorted(root.rglob(f"*{CONTENT_SUFFIX}")):
        source_path = path.relative_to(checkout.path).as_posix()
        if not in_scope(source_path, settings):
            continue
        text = path.read_text(encoding="utf-8")
        documents.append(
            SourceDocument(
                source_path=source_path,
                section=section_of(source_path),
                text=text,
                content_hash=content_hash(text),
            )
        )

    if not documents:
        # An empty corpus is never a legitimate outcome — it means the scope
        # configuration excludes everything, and silently building an empty
        # index would pass every downstream check.
        raise RescueError(
            ErrorCode.INGESTION_SOURCE_UNAVAILABLE,
            detail=(
                f"no documents matched INGEST_SECTIONS={settings.ingest_sections!r} "
                f"with INGEST_EXCLUDE_GLOBS={settings.ingest_exclude_globs!r}"
            ),
        )
    logger.info(
        "documents discovered",
        extra={"count": len(documents), "commit": checkout.commit},
    )
    return documents
