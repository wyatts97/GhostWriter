"""RSS Feeds router — CRUD for feed sources."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.rss import RSSFeed

router = APIRouter(tags=["feeds"])


@router.get("/", response_class=HTMLResponse)
async def list_feeds(request: Request, session: AsyncSession = Depends(get_session)):
    """Show all RSS feeds."""
    result = await session.execute(select(RSSFeed).order_by(RSSFeed.name))
    feeds = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "feeds/list.html",
        {"request": request, "feeds": feeds, "active_page": "feeds"},
    )


@router.post("/new")
async def create_feed(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    topic: str = Form(""),
    fetch_interval_minutes: int = Form(60),
    session: AsyncSession = Depends(get_session),
):
    """Create a new RSS feed source."""
    feed = RSSFeed(
        name=name,
        url=url,
        topic=topic,
        active=True,
        fetch_interval_minutes=fetch_interval_minutes,
    )
    session.add(feed)
    await session.commit()
    return RedirectResponse(url="/feeds", status_code=303)


@router.post("/{feed_id}/edit")
async def update_feed(
    feed_id: int,
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    topic: str = Form(""),
    fetch_interval_minutes: int = Form(60),
    active: bool = Form(True),
    session: AsyncSession = Depends(get_session),
):
    """Update an existing RSS feed."""
    result = await session.execute(select(RSSFeed).where(RSSFeed.id == feed_id))
    feed = result.scalar_one_or_none()

    if feed:
        feed.name = name
        feed.url = url
        feed.topic = topic
        feed.fetch_interval_minutes = fetch_interval_minutes
        feed.active = active
        await session.commit()

    return RedirectResponse(url="/feeds", status_code=303)


@router.post("/{feed_id}/delete")
async def delete_feed(
    feed_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete an RSS feed."""
    result = await session.execute(select(RSSFeed).where(RSSFeed.id == feed_id))
    feed = result.scalar_one_or_none()

    if feed:
        await session.delete(feed)
        await session.commit()

    return RedirectResponse(url="/feeds", status_code=303)


@router.post("/{feed_id}/toggle")
async def toggle_feed(
    feed_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Toggle feed active/inactive."""
    result = await session.execute(select(RSSFeed).where(RSSFeed.id == feed_id))
    feed = result.scalar_one_or_none()

    if feed:
        feed.active = not feed.active
        await session.commit()

    return RedirectResponse(url="/feeds", status_code=303)


@router.post("/{feed_id}/fetch")
async def fetch_single_feed(
    feed_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Manually trigger a feed fetch."""
    from app.services.rss_fetcher import fetch_feed

    await fetch_feed(feed_id, session)
    return RedirectResponse(url="/feeds", status_code=303)


@router.get("/{feed_id}/test")
async def test_feed(
    feed_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Test fetching a feed and return sample entries as JSON."""
    from app.services.rss_fetcher import test_feed_url

    result = await session.execute(select(RSSFeed).where(RSSFeed.id == feed_id))
    feed = result.scalar_one_or_none()

    if not feed:
        return JSONResponse({"success": False, "error": "Feed not found"})

    data = await test_feed_url(feed.url)
    return JSONResponse(data)
