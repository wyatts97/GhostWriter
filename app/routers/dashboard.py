"""Dashboard router — overview stats and activity."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.articles import GeneratedArticle
from app.models.rss import RSSFeed
from app.models.schedules import Schedule

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    """Render the dashboard with summary statistics."""

    # Count stats
    articles_today = await session.execute(
        select(func.count(GeneratedArticle.id)).where(
            func.date(GeneratedArticle.created_at) == func.date("now")
        )
    )
    articles_published = await session.execute(
        select(func.count(GeneratedArticle.id)).where(
            GeneratedArticle.status == "published"
        )
    )
    active_schedules = await session.execute(
        select(func.count(Schedule.id)).where(Schedule.active == True)  # noqa: E712
    )
    total_feeds = await session.execute(select(func.count(RSSFeed.id)))

    # Recent activity
    recent_articles = await session.execute(
        select(GeneratedArticle)
        .order_by(GeneratedArticle.created_at.desc())
        .limit(10)
    )
    recent = recent_articles.scalars().all()

    context = {
        "request": request,
        "stats": {
            "articles_today": articles_today.scalar() or 0,
            "articles_published": articles_published.scalar() or 0,
            "active_schedules": active_schedules.scalar() or 0,
            "total_feeds": total_feeds.scalar() or 0,
        },
        "recent_articles": recent,
        "active_page": "dashboard",
    }

    return templates.TemplateResponse(request, "dashboard.html", context)
