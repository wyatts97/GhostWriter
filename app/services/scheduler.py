"""APScheduler integration for automated article generation."""

import json
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from structlog import get_logger

from app.database import async_session_factory
from app.models.schedules import Schedule
from app.services.article_generator import generate_article
from app.services.ghost_client import GhostClient
from app.services.llm_client import LlmClient

logger = get_logger(__name__)

scheduler = AsyncIOScheduler()


async def start_scheduler() -> AsyncIOScheduler:
    """Initialize and start the scheduler, loading all active schedules from DB."""
    from app.config import settings

    # Load all active schedules
    async with async_session_factory() as session:
        result = await session.execute(
            select(Schedule).where(Schedule.active == True)  # noqa: E712
        )
        schedules = result.scalars().all()

        for schedule in schedules:
            _add_schedule_job(schedule)

    # Start the scheduler
    scheduler.start()

    logger.info("scheduler_started", active_schedules=len(schedules) if schedules else 0)

    return scheduler


async def add_schedule(schedule: Schedule) -> None:
    """Add or update a schedule job."""
    job_id = f"schedule_{schedule.id}"

    # Remove existing job if it exists
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if schedule.active:
        _add_schedule_job(schedule)
        logger.info("schedule_job_added", schedule_id=schedule.id, cron=schedule.cron_expression)


async def remove_schedule(schedule_id: int) -> None:
    """Remove a schedule job."""
    job_id = f"schedule_{schedule_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("schedule_job_removed", schedule_id=schedule_id)


def _add_schedule_job(schedule: Schedule) -> None:
    """Internal: add a job to the scheduler for a given schedule."""
    job_id = f"schedule_{schedule.id}"

    try:
        trigger = CronTrigger.from_crontab(schedule.cron_expression)
    except (ValueError, AttributeError) as exc:
        logger.error(
            "schedule_invalid_cron",
            schedule_id=schedule.id,
            cron=schedule.cron_expression,
            error=str(exc),
        )
        return

    scheduler.add_job(
        _run_schedule_job,
        trigger=trigger,
        id=job_id,
        args=[schedule.id],
        name=schedule.name,
        replace_existing=True,
        misfire_grace_time=300,  # 5 minutes grace
    )


async def _run_schedule_job(schedule_id: int) -> None:
    """Execute a schedule: generate articles and send to Ghost."""
    from app.services.runtime_config import RuntimeConfig

    logger.info("schedule_job_running", schedule_id=schedule_id)

    async with async_session_factory() as session:
        # Reload schedule from DB
        result = await session.execute(
            select(Schedule).where(Schedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()

        if not schedule or not schedule.active:
            logger.info("schedule_job_skipped", schedule_id=schedule_id)
            return

        if not schedule.prompt_id:
            logger.warning("schedule_no_prompt", schedule_id=schedule_id)
            return

        # Parse feed IDs
        try:
            feed_ids = json.loads(schedule.feed_ids) if schedule.feed_ids else []
        except (json.JSONDecodeError, TypeError):
            feed_ids = []

        # Load runtime config — respects DB settings, falls back to .env
        runtime = await RuntimeConfig.load(session)
        llm_cfg = runtime.resolve_llm_config()

        # Initialize clients
        llm_client = LlmClient(
            base_url=llm_cfg["base_url"],
            api_key=llm_cfg["api_key"],
            default_model=llm_cfg["model"],
        )

        ghost_client = GhostClient(
            admin_url=runtime.ghost_admin_url,
            admin_api_key=runtime.ghost_admin_api_key,
        )

        # Generate articles
        success_count = 0
        fail_count = 0

        for i in range(schedule.max_articles_per_run):
            try:
                article = await generate_article(
                    prompt_id=schedule.prompt_id,
                    feed_ids=feed_ids,
                    schedule_id=schedule.id,
                    publish_mode=schedule.publish_mode,
                    session=session,
                    llm_client=llm_client,
                    ghost_client=ghost_client,
                )

                if article.status == "failed":
                    fail_count += 1
                else:
                    success_count += 1

            except Exception as exc:
                fail_count += 1
                logger.error(
                    "schedule_job_article_failed",
                    schedule_id=schedule_id,
                    error=str(exc),
                )

        logger.info(
            "schedule_job_completed",
            schedule_id=schedule_id,
            success=success_count,
            failed=fail_count,
        )


async def run_schedule_now(
    schedule_id: int,
    tracker: Any | None = None,
) -> dict:
    """Manually trigger a schedule run. Returns a summary dict.

    If *tracker* is provided (a ``GenerationTask`` instance) its progress
    fields are updated throughout the generation lifecycle so the UI can poll.
    """
    from app.services.runtime_config import RuntimeConfig

    if tracker:
        tracker.update(progress_pct=10, stage="Loading schedule…")

    async with async_session_factory() as session:
        result = await session.execute(
            select(Schedule).where(Schedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()

        if not schedule:
            return {"success": False, "error": "Schedule not found"}

        if not schedule.prompt_id:
            return {"success": False, "error": "Schedule has no prompt assigned"}

        try:
            feed_ids = json.loads(schedule.feed_ids) if schedule.feed_ids else []
        except (json.JSONDecodeError, TypeError):
            feed_ids = []

        if tracker:
            tracker.update(progress_pct=20, stage="Loading configuration…")

        runtime = await RuntimeConfig.load(session)
        llm_cfg = runtime.resolve_llm_config()

        if tracker:
            tracker.update(progress_pct=30, stage="Connecting to LLM…")

        llm_client = LlmClient(
            base_url=llm_cfg["base_url"],
            api_key=llm_cfg["api_key"],
            default_model=llm_cfg["model"],
        )

        ghost_client = GhostClient(
            admin_url=runtime.ghost_admin_url,
            admin_api_key=runtime.ghost_admin_api_key,
        )

        if tracker:
            tracker.update(progress_pct=40, stage="Generating article…")

        article = await generate_article(
            prompt_id=schedule.prompt_id,
            feed_ids=feed_ids,
            schedule_id=schedule.id,
            publish_mode=schedule.publish_mode,
            session=session,
            llm_client=llm_client,
            ghost_client=ghost_client,
        )

        if tracker:
            tracker.update(
                progress_pct=95,
                stage="Finalizing…",
                article_id=article.id,
                title=article.title,
            )

        result_data: dict[str, Any] = {
            "success": article.status != "failed",
            "article_id": article.id,
            "title": article.title,
            "status": article.status,
        }
        if article.error_message:
            result_data["error"] = article.error_message
        return result_data
