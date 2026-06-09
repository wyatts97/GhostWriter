"""Articles router — view, manage, and publish generated articles."""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.articles import GeneratedArticle
from app.models.prompts import Prompt

router = APIRouter(tags=["articles"])


@router.get("/", response_class=HTMLResponse)
async def list_articles(
    request: Request,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Show all generated articles with optional status filter."""
    query = select(GeneratedArticle).order_by(GeneratedArticle.created_at.desc())

    if status and status != "all":
        query = query.where(GeneratedArticle.status == status)

    result = await session.execute(query)
    articles = result.scalars().all()

    # Attach prompt names (uses selectin relationship, no N+1)
    article_data = []
    for article in articles:
        prompt_name = article.prompt.name if article.prompt else ""
        article_data.append(
            {
                "article": article,
                "prompt_name": prompt_name,
            }
        )

    # Counts for filter pills
    counts = {
        "all": len(articles),
        "draft": sum(1 for a in articles if a.status == "draft"),
        "draft_sent": sum(1 for a in articles if a.status == "draft_sent"),
        "published": sum(1 for a in articles if a.status == "published"),
        "failed": sum(1 for a in articles if a.status == "failed"),
    }

    return templates.TemplateResponse(
        request,
        "articles/list.html",
        {
            "request": request,
            "articles": article_data,
            "current_status": status or "all",
            "counts": counts,
            "active_page": "articles",
        },
    )


@router.get("/{article_id}", response_class=HTMLResponse)
async def article_detail(
    article_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Show detailed view of a single article."""
    result = await session.execute(
        select(GeneratedArticle).where(GeneratedArticle.id == article_id)
    )
    article = result.scalar_one_or_none()

    if not article:
        return RedirectResponse(url="/articles", status_code=303)

    prompt_name = article.prompt.name if article.prompt else "Deleted"

    # Parse JSON fields for display
    tags = []
    if article.tags:
        try:
            tags = json.loads(article.tags)
        except (json.JSONDecodeError, TypeError):
            tags = [article.tags] if article.tags else []

    return templates.TemplateResponse(
        request,
        "articles/detail.html",
        {
            "request": request,
            "article": article,
            "prompt_name": prompt_name,
            "tags": tags,
            "active_page": "articles",
        },
    )


@router.post("/{article_id}/publish")
async def publish_article(
    article_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Publish a draft article to Ghost."""
    from app.services.ghost_client import GhostClient
    from app.services.runtime_config import RuntimeConfig

    import markdown as md_lib

    result = await session.execute(
        select(GeneratedArticle).where(GeneratedArticle.id == article_id)
    )
    article = result.scalar_one_or_none()

    if not article:
        return JSONResponse({"success": False, "error": "Article not found"})

    if article.status not in ("draft", "draft_sent"):
        return JSONResponse(
            {"success": False, "error": f"Article is already {article.status}"}
        )

    runtime = await RuntimeConfig.load(session)
    ghost = GhostClient(
        admin_url=runtime.ghost_admin_url,
        admin_api_key=runtime.ghost_admin_api_key,
    )

    try:
        content_html = md_lib.markdown(
            article.content, extensions=["fenced_code", "tables"]
        )

        tags = []
        if article.tags:
            try:
                tags = json.loads(article.tags)
            except (json.JSONDecodeError, TypeError):
                tags = [article.tags] if article.tags else []

        ghost_post = await ghost.create_post(
            title=article.title,
            content_html=content_html,
            status="published",
            excerpt=article.excerpt,
            feature_image=article.feature_image_url,
            tags=tags if isinstance(tags, list) else [tags],
            meta_title=article.seo_title,
            meta_description=article.seo_description,
            og_title=article.og_title,
            og_description=article.og_description,
            twitter_title=article.twitter_title,
            twitter_description=article.twitter_description,
        )

        article.ghost_post_id = ghost_post.get("id")
        article.ghost_url = ghost_post.get("url")
        article.status = "published"
        await session.commit()

        return JSONResponse(
            {
                "success": True,
                "ghost_url": article.ghost_url,
            }
        )

    except Exception as exc:
        article.error_message = str(exc)
        await session.commit()
        return JSONResponse({"success": False, "error": str(exc)})


@router.post("/{article_id}/regenerate")
async def regenerate_article(
    article_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Regenerate an article using the same prompt and sources."""
    from app.services.article_generator import generate_article
    from app.services.ghost_client import GhostClient
    from app.services.llm_client import LlmClient
    from app.services.runtime_config import RuntimeConfig

    result = await session.execute(
        select(GeneratedArticle).where(GeneratedArticle.id == article_id)
    )
    article = result.scalar_one_or_none()

    if not article:
        return JSONResponse({"success": False, "error": "Article not found"})

    runtime = await RuntimeConfig.load(session)
    llm_cfg = runtime.resolve_llm_config()
    llm = LlmClient(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
        default_model=llm_cfg["model"],
    )

    ghost = GhostClient(
        admin_url=runtime.ghost_admin_url,
        admin_api_key=runtime.ghost_admin_api_key,
    )

    try:
        feed_ids = json.loads(article.feed_entry_ids) if article.feed_entry_ids else []

        new_article = await generate_article(
            prompt_id=article.prompt_id,
            feed_ids=feed_ids,
            schedule_id=article.schedule_id,
            publish_mode="draft",
            session=session,
            llm_client=llm,
            ghost_client=ghost,
        )

        return JSONResponse(
            {
                "success": True,
                "article_id": new_article.id,
                "title": new_article.title,
            }
        )

    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)})


@router.post("/{article_id}/delete")
async def delete_article(
    article_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete an article from local storage."""
    result = await session.execute(
        select(GeneratedArticle).where(GeneratedArticle.id == article_id)
    )
    article = result.scalar_one_or_none()

    if article:
        await session.delete(article)
        await session.commit()

    return RedirectResponse(url="/articles", status_code=303)
