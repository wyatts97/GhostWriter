"""Generation router — async article generation with progress tracking."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.database import get_session
from app.models.schedules import Schedule
from app.services.generation_tracker import create_task, get_task

logger = get_logger(__name__)

router = APIRouter(prefix="/generation", tags=["generation"])


@router.post("/run")
async def run_generation(
    request: Request,
    schedule_id: int = Form(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Start article generation in the background and return a task ID to poll."""
    # Verify schedule exists
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return JSONResponse(
            {"success": False, "error": "Schedule not found"}, status_code=404
        )
    if not schedule.prompt_id:
        return JSONResponse(
            {"success": False, "error": "Schedule has no prompt assigned"},
            status_code=400,
        )

    # Create a tracked task — the actual generation runs in a background
    # task via FastAPI's BackgroundTasks mechanism.
    task = create_task(schedule_id=schedule_id)

    async def _run() -> None:
        from app.services.scheduler import run_schedule_now

        task.update(status="generating", progress_pct=5, stage="Initializing…")
        try:
            result_data = await run_schedule_now(schedule_id, tracker=task)
            if result_data.get("success"):
                task.update(
                    status="done",
                    progress_pct=100,
                    stage="Complete",
                    article_id=result_data.get("article_id"),
                    title=result_data.get("title"),
                )
            else:
                task.update(
                    status="failed",
                    error=result_data.get("error", "Unknown error"),
                )
        except Exception as exc:
            logger.error(
                "generation_background_failed",
                task_id=task.task_id,
                error=str(exc),
            )
            task.update(status="failed", error=str(exc))

    background_tasks.add_task(_run)

    return JSONResponse({
        "success": True,
        "task_id": task.task_id,
    })


@router.get("/status/{task_id}")
async def generation_status(task_id: str) -> JSONResponse:
    """Poll the progress of an article generation task."""
    gtask = get_task(task_id)
    if gtask is None:
        return JSONResponse(
            {"success": False, "error": "Task not found or expired"}, status_code=404
        )
    return JSONResponse({"success": True, **gtask.to_dict()})
