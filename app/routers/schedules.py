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

    # Build display names for linked prompt and feeds
    schedule_data = []
    for s in schedules:
        prompt_name = ""
        if s.prompt_id:
            p_result = await session.execute(
                select(Prompt).where(Prompt.id == s.prompt_id)
            )
            prompt = p_result.scalar_one_or_none()
            prompt_name = prompt.name if prompt else "Deleted Prompt"

        feed_names = []
        if s.feed_ids:
            try:
                feed_ids = json.loads(s.feed_ids)
                if feed_ids:
                    f_result = await session.execute(
                        select(RSSFeed).where(RSSFeed.id.in_(feed_ids))
                    )
                    feed_names = [f.name for f in f_result.scalars().all()]
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
    session: AsyncSession = Depends(get_session),
):
    """Show the create schedule form."""
    prompts_result = await session.execute(select(Prompt).order_by(Prompt.name))
    prompts = prompts_result.scalars().all()

    feeds_result = await session.execute(select(RSSFeed).order_by(RSSFeed.name))
    feeds = feeds_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "schedules/form.html",
        {
            "request": request,
            "schedule": None,
            "prompts": prompts,
            "feeds": feeds,
            "action": "create",
            "active_page": "schedules",
        },
    )


@router.post("/new")
async def create_schedule(
    request: Request,
    name: str = Form(...),
    cron_expression: str = Form(...),
    prompt_id: int = Form(...),
    feed_ids: str = Form("[]"),
    publish_mode: str = Form("draft"),
    max_articles_per_run: int = Form(1),
    active: bool = Form(True),
    session: AsyncSession = Depends(get_session),
):
    """Create a new schedule."""
    schedule = Schedule(
        name=name,
        cron_expression=cron_expression,
        prompt_id=prompt_id if prompt_id else None,
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

    feeds_result = await session.execute(select(RSSFeed).order_by(RSSFeed.name))
    feeds = feeds_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "schedules/form.html",
        {
            "request": request,
            "schedule": schedule,
            "prompts": prompts,
            "feeds": feeds,
            "action": "edit",
            "active_page": "schedules",
        },
    )


@router.post("/{schedule_id}/edit")
async def update_schedule(
    schedule_id: int,
    request: Request,
    name: str = Form(...),
    cron_expression: str = Form(...),
    prompt_id: int = Form(...),
    feed_ids: str = Form("[]"),
    publish_mode: str = Form("draft"),
    max_articles_per_run: int = Form(1),
    active: bool = Form(True),
    session: AsyncSession = Depends(get_session),
):
    """Update an existing schedule."""
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if schedule:
        schedule.name = name
        schedule.cron_expression = cron_expression
        schedule.prompt_id = prompt_id if prompt_id else None
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
