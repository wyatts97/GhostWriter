"""In-memory tracker for article generation progress.

Allows the UI to poll for status while a generation runs in the background.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from structlog import get_logger

logger = get_logger(__name__)

# ── In-memory store ──────────────────────────────────────────────────────────
_tasks: dict[str, "GenerationTask"] = {}


class GenerationTask:
    """Tracks progress of a single article generation."""

    __slots__ = (
        "task_id",
        "schedule_id",
        "status",
        "progress_pct",
        "stage",
        "article_id",
        "title",
        "error",
        "created_at",
        "updated_at",
    )

    def __init__(self, schedule_id: int = 0) -> None:
        self.task_id: str = uuid4().hex[:12]
        self.schedule_id: int = schedule_id
        self.status: str = "queued"  # queued → generating → done / failed
        self.progress_pct: int = 0
        self.stage: str = "Waiting…"
        self.article_id: int | None = None
        self.title: str | None = None
        self.error: str | None = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at

    def update(
        self,
        status: str | None = None,
        progress_pct: int | None = None,
        stage: str | None = None,
        article_id: int | None = None,
        title: str | None = None,
        error: str | None = None,
    ) -> None:
        if status is not None:
            self.status = status
        if progress_pct is not None:
            self.progress_pct = min(progress_pct, 100)
        if stage is not None:
            self.stage = stage
        if article_id is not None:
            self.article_id = article_id
        if title is not None:
            self.title = title
        if error is not None:
            self.error = error
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "schedule_id": self.schedule_id,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "stage": self.stage,
            "article_id": self.article_id,
            "title": self.title,
            "error": self.error,
        }


# ── Public API ───────────────────────────────────────────────────────────────


def create_task(schedule_id: int = 0) -> GenerationTask:
    """Create a new generation task and store it in the registry."""
    task = GenerationTask(schedule_id=schedule_id)
    _tasks[task.task_id] = task
    # Evict stale tasks older than 30 minutes
    _evict_stale()
    logger.info("generation_task_created", task_id=task.task_id)
    return task


def get_task(task_id: str) -> GenerationTask | None:
    return _tasks.get(task_id)


def _evict_stale() -> None:
    """Remove tasks older than 30 minutes to prevent memory leaks."""
    cutoff = datetime.now(timezone.utc)
    stale = [
        tid
        for tid, t in _tasks.items()
        if (cutoff - t.updated_at).total_seconds() > 1800
    ]
    for tid in stale:
        _tasks.pop(tid, None)
