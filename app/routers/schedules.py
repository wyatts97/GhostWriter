"""Schedules router — CRUD for generation schedules."""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.prompts import Prompt
from app.models.rss import RSSFeed
from app.models.schedules import Schedule
from app.services.scheduler import add_schedule, remove_schedule, run_schedule_now

router = APIRouter(tags=["schedules"])


@router.get("/", response_class=HTMLResponse)
async def list_schedules(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Show all schedules."""
    result = await session.execute(select(Schedule).order_by(Schedule.name))
    schedules = result.scalars().all()

    # Build display names for linked prompt and feeds (batch queries, no N+1)
    # Collect all unique feed IDs across all schedules
    all_feed_ids: set[int] = set()
    for s in schedules:
        if s.feed_ids:
            try:
                ids = json.loads(s.feed_ids)
                all_feed_ids.update(ids)
            except (json.JSONDecodeError, TypeError):
                pass

    # Batch load feed names
    feed_name_map: dict[int, str] = {}
    if all_feed_ids:
        f_result = await session.execute(
            select(RSSFeed).where(RSSFeed.id.in_(list(all_feed_ids)))
        )
        for f in f_result.scalars().all():
            feed_name_map[f.id] = f.name

    schedule_data = []
    for s in schedules:
        prompt_name = s.prompt.name if s.prompt else "Deleted Prompt"

        feed_names = []
        if s.feed_ids:
            try:
                ids = json.loads(s.feed_ids)
                feed_names = [feed_name_map.get(fid, "Deleted") for fid in ids]
            except (json.JSONDecodeError, TypeError):
                pass

        schedule_data.append(
            {
                "schedule": s,
                "prompt_name": prompt_name,
                "feed_names": feed_names,
            }
        )

    return templates.TemplateResponse(
        request,
        "schedules/list.html",
        {
            "request": request,
            "schedules": schedule_data,
            "active_page": "schedules",
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_schedule_form(
    request: Request,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Show the create schedule form."""
    prompts_result = await session.execute(select(Prompt).order_by(Prompt.name))
    prompts = prompts_result.scalars().all()
    prompt_options = [{"value": "", "label": "— Select a prompt —"}] + [
        {"value": str(p.id), "label": p.name} for p in prompts
    ]

    feeds_result = await session.execute(select(RSSFeed).order_by(RSSFeed.name))
    feeds = feeds_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "schedules/form.html",
        {
            "request": request,
            "schedule": None,
            "prompts": prompts,
            "prompt_options": prompt_options,
            "feeds": feeds,
            "action": "create",
            "error": error or "",
            "active_page": "schedules",
        },
    )


@router.post("/new")
async def create_schedule(
    request: Request,
    name: str = Form(""),
    cron_expression: str = Form(...),
    prompt_id: str = Form(""),
    feed_ids: str = Form("[]"),
    publish_mode: str = Form("draft"),
    max_articles_per_run: int = Form(1),
    active: bool = Form(False),
    session: AsyncSession = Depends(get_session),
):
    """Create a new schedule."""
    if not name:
        return RedirectResponse(url="/schedules/new", status_code=303)

    # Validate cron expression
    from apscheduler.triggers.cron import CronTrigger
    try:
        CronTrigger.from_crontab(cron_expression)
    except (ValueError, AttributeError) as exc:
        return RedirectResponse(
            url=f"/schedules/new?error=Invalid+cron+expression:+{exc}",
            status_code=303,
        )

    schedule = Schedule(
        name=name,
        cron_expression=cron_expression,
        prompt_id=int(prompt_id) if prompt_id else None,
        feed_ids=feed_ids,
        publish_mode=publish_mode,
        max_articles_per_run=max_articles_per_run,
        active=active,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    # Register with APScheduler
    await add_schedule(schedule)

    return RedirectResponse(url="/schedules", status_code=303)


@router.get("/{schedule_id}/edit", response_class=HTMLResponse)
async def edit_schedule_form(
    schedule_id: int,
    request: Request,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Show the edit schedule form."""
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        return RedirectResponse(url="/schedules", status_code=303)

    prompts_result = await session.execute(select(Prompt).order_by(Prompt.name))
    prompts = prompts_result.scalars().all()
    prompt_options = [{"value": "", "label": "— Select a prompt —"}] + [
        {"value": str(p.id), "label": p.name} for p in prompts
    ]

    feeds_result = await session.execute(select(RSSFeed).order_by(RSSFeed.name))
    feeds = feeds_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "schedules/form.html",
        {
            "request": request,
            "schedule": schedule,
            "prompts": prompts,
            "prompt_options": prompt_options,
            "feeds": feeds,
            "action": "edit",
            "error": error or "",
            "active_page": "schedules",
        },
    )


@router.post("/{schedule_id}/edit")
async def update_schedule(
    schedule_id: int,
    request: Request,
    name: str = Form(""),
    cron_expression: str = Form(...),
    prompt_id: str = Form(""),
    feed_ids: str = Form("[]"),
    publish_mode: str = Form("draft"),
    max_articles_per_run: int = Form(1),
    active: bool = Form(False),
    session: AsyncSession = Depends(get_session),
):
    """Update an existing schedule."""
    if not name:
        return RedirectResponse(url=f"/schedules/{schedule_id}/edit", status_code=303)

    # Validate cron expression
    from apscheduler.triggers.cron import CronTrigger
    try:
        CronTrigger.from_crontab(cron_expression)
    except (ValueError, AttributeError) as exc:
        return RedirectResponse(
            url=f"/schedules/{schedule_id}/edit?error=Invalid+cron+expression:+{exc}",
            status_code=303,
        )

    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if schedule:
        schedule.name = name
        schedule.cron_expression = cron_expression
        schedule.prompt_id = int(prompt_id) if prompt_id else None
        schedule.feed_ids = feed_ids
        schedule.publish_mode = publish_mode
        schedule.max_articles_per_run = max_articles_per_run
        schedule.active = active
        await session.commit()

        # Re-register with APScheduler
        await add_schedule(schedule)

    return RedirectResponse(url="/schedules", status_code=303)


@router.post("/{schedule_id}/delete")
async def delete_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a schedule."""
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if schedule:
        await session.delete(schedule)
        await session.commit()
        await remove_schedule(schedule_id)

    return RedirectResponse(url="/schedules", status_code=303)


@router.post("/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Toggle schedule active/inactive."""
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if schedule:
        schedule.active = not schedule.active
        await session.commit()
        if schedule.active:
            await add_schedule(schedule)
        else:
            await remove_schedule(schedule_id)

    return RedirectResponse(url="/schedules", status_code=303)


@router.post("/{schedule_id}/run")
async def run_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Manually trigger a schedule run."""
    result = await run_schedule_now(schedule_id)
    return JSONResponse(result)
