"""Article generation engine: assembles context, calls LLM, creates articles."""

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.models.articles import GeneratedArticle
from app.models.prompts import Prompt
from app.models.rss import FeedEntry
from app.services.ghost_client import GhostClient
from app.services.llm_client import LlmApiError, LlmClient
from app.services.rss_fetcher import get_recent_entries
from app.utils import seo as seo_utils

logger = get_logger(__name__)

ARTICLE_SCHEMA = {
    "type": "json_object",
    "schema": {
        "title": "string (SEO-optimized, under 70 characters, compelling)",
        "excerpt": "string (compelling summary, 150-160 characters, includes primary keyword)",
        "content": "string (full article in markdown format, 1500-2500 words, proper heading hierarchy)",
        "tags": "array of strings (3-5 relevant tags for categorization)",
        "seo_title": "string (under 60 characters, optimized for search engines)",
        "seo_description": "string (under 160 characters, includes keyword and CTA)",
        "og_title": "string (optimized for social sharing, under 60 characters)",
        "og_description": "string (optimized for social sharing, under 160 characters)",
        "twitter_title": "string (optimized for Twitter/X sharing, under 60 characters)",
        "twitter_description": "string (optimized for Twitter/X sharing, under 160 characters)",
    },
}


async def generate_article(
    prompt_id: int,
    feed_ids: list[int],
    schedule_id: int | None = None,
    publish_mode: str = "draft",
    session: AsyncSession | None = None,
    llm_client: LlmClient | None = None,
    ghost_client: GhostClient | None = None,
) -> GeneratedArticle:
    """Run the full article generation pipeline.

    1. Load prompt + context from RSS feeds
    2. Call LLM with structured output
    3. Post-process (SEO validation)
    4. Save to database
    5. Send to Ghost if publish_mode dictates
    """
    # ── 1. Load prompt ────────────────────────────────────────────────────
    result = await session.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()

    if not prompt:
        raise ValueError(f"Prompt with id {prompt_id} not found")

    # ── 2. Get recent RSS entries for context ─────────────────────────────
    entries: list[FeedEntry] = []
    if feed_ids:
        entries = await get_recent_entries(feed_ids, limit=10, session=session)

    # ── 3. Build context digest ───────────────────────────────────────────
    context_digest = _build_context_digest(entries)

    # ── 4. Resolve template variables in prompt ───────────────────────────
    from app.utils.prompt_variables import resolve_prompt_variables

    resolved_content = await resolve_prompt_variables(
        prompt.content,
        feed_ids=feed_ids,
        session=session,
    )

    # ── 5. Assemble messages ──────────────────────────────────────────────
    system_prompt = resolved_content
    if seo_instructions := seo_utils.build_seo_prompt_instructions():
        system_prompt = f"{system_prompt}\n\n{seo_instructions}"

    system_prompt += f"\n\nToday's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Write a high-quality, SEO-optimized article based on the following source material:\n\n{context_digest}",
        },
    ]

    # ── 6. Call LLM ───────────────────────────────────────────────────────
    if not llm_client:
        # Load from runtime config (DB settings + .env fallback)
        from app.services.runtime_config import RuntimeConfig

        runtime = await RuntimeConfig.load(session)
        llm_cfg = runtime.resolve_llm_config()
        llm_client = LlmClient(
            base_url=llm_cfg["base_url"],
            api_key=llm_cfg["api_key"],
            default_model=llm_cfg["model"],
        )

    model = prompt.model_override or None

    try:
        llm_response = await llm_client.generate_structured(
            messages=messages,
            output_schema=ARTICLE_SCHEMA,
            model=model,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
        )
    except LlmApiError as exc:
        logger.warning(
            "article_generation_fallback_to_chat",
            prompt_id=prompt_id,
            error=str(exc),
        )
        # Structured JSON call failed → fall back to plain-text generation
        # and parse the article fields from delimited format.
        try:
            llm_response = await _fallback_generate_article(
                llm_client, messages, model, prompt, context_digest
            )
        except Exception as fallback_exc:
            logger.error(
                "article_generation_failed",
                prompt_id=prompt_id,
                error=str(fallback_exc),
            )
            article = GeneratedArticle(
                prompt_id=prompt_id,
                schedule_id=schedule_id,
                feed_entry_ids=json.dumps(feed_ids),
                title="Generation Failed",
                content="",
                status="failed",
                error_message=str(fallback_exc),
            )
            session.add(article)
            await session.commit()
            return article

    # ── 7. Parse and validate ─────────────────────────────────────────────
    title = llm_response.get("title", "Untitled Article")
    excerpt = llm_response.get("excerpt", "")
    content = llm_response.get("content", "")
    tags = llm_response.get("tags", [])

    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = [tags]

    # SEO post-processing
    seo_title = seo_utils.optimize_title(llm_response.get("seo_title", title), 60)
    seo_description = seo_utils.optimize_meta_description(
        llm_response.get("seo_description", excerpt), 160
    )
    og_title = seo_utils.optimize_title(llm_response.get("og_title", title), 60)
    og_description = seo_utils.optimize_meta_description(
        llm_response.get("og_description", excerpt), 160
    )
    twitter_title = seo_utils.optimize_title(
        llm_response.get("twitter_title", title), 60
    )
    twitter_description = seo_utils.optimize_meta_description(
        llm_response.get("twitter_description", excerpt), 160
    )

    # ── 8. Save to database ───────────────────────────────────────────────
    article = GeneratedArticle(
        prompt_id=prompt_id,
        schedule_id=schedule_id,
        feed_entry_ids=json.dumps(feed_ids),
        title=title,
        content=content,
        excerpt=excerpt[:300] if excerpt else None,
        tags=json.dumps(tags),
        seo_title=seo_title,
        seo_description=seo_description,
        og_title=og_title,
        og_description=og_description,
        twitter_title=twitter_title,
        twitter_description=twitter_description,
        status="draft",
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)

    # ── 9. Send to Ghost ──────────────────────────────────────────────────
    if ghost_client and ghost_client.admin_url and ghost_client.admin_api_key:
        try:
            # Convert markdown to HTML
            import markdown as md_lib

            content_html = md_lib.markdown(content, extensions=["fenced_code", "tables"])

            ghost_post = await ghost_client.create_post(
                title=title,
                content_html=content_html,
                status=publish_mode,
                excerpt=excerpt[:300] if excerpt else None,
                tags=tags if isinstance(tags, list) else json.loads(tags),
                meta_title=seo_title,
                meta_description=seo_description,
                og_title=og_title,
                og_description=og_description,
                twitter_title=twitter_title,
                twitter_description=twitter_description,
            )

            article.ghost_post_id = ghost_post.get("id")
            article.ghost_url = ghost_post.get("url")

            if publish_mode == "publish":
                article.status = "published"
            else:
                article.status = "draft_sent"

            await session.commit()

        except Exception as exc:
            logger.error(
                "ghost_publish_failed",
                article_id=article.id,
                error=str(exc),
            )
            article.error_message = f"Ghost publish failed: {exc}"
            article.status = "draft"  # Keep as draft, content saved locally
            await session.commit()

    # Mark feed entries as used
    if entries:
        for entry in entries:
            entry.is_used = True
        await session.commit()

    logger.info(
        "article_generated",
        article_id=article.id,
        title=title,
        status=article.status,
    )

    return article


async def _fallback_generate_article(
    llm_client: LlmClient,
    messages: list[dict[str, str]],
    model: str | None,
    prompt: Prompt,
    context_digest: str,
) -> dict[str, Any]:
    """Fallback: call LLM without JSON mode and parse the text response."""
    # Append format instructions to the user message
    text_instructions = (
        "\n\n---\n"
        "IMPORTANT: Output your article using the following delimited text format "
        "(do NOT use JSON):\n\n"
        "---TITLE---\n"
        "Your article title here\n\n"
        "---EXCERPT---\n"
        "Your excerpt here\n\n"
        "---TAGS---\n"
        "tag1, tag2, tag3\n\n"
        "---CONTENT---\n"
        "Full article in markdown here"
    )
    fallback_msgs = list(messages)
    fallback_msgs[-1]["content"] += text_instructions

    response = await llm_client.generate_chat(
        messages=fallback_msgs,
        model=model,
        temperature=prompt.temperature,
        max_tokens=prompt.max_tokens,
    )
    raw = response["choices"][0]["message"]["content"]
    return _parse_text_article(raw)


def _parse_text_article(raw: str) -> dict[str, Any]:
    """Extract article fields from delimited text format."""
    result: dict[str, Any] = {
        "title": "Untitled Article",
        "excerpt": "",
        "content": "",
        "tags": [],
        "seo_title": "",
        "seo_description": "",
        "og_title": "",
        "og_description": "",
        "twitter_title": "",
        "twitter_description": "",
    }

    def _extract(label: str) -> str | None:
        m = re.search(
            rf"^---{label}---\s*\n(.+?)(?=\n---|\Z)",
            raw,
            re.DOTALL | re.MULTILINE,
        )
        if m:
            return m.group(1).strip()
        return None

    title = _extract("TITLE")
    if title:
        result["title"] = title

    excerpt = _extract("EXCERPT")
    if excerpt:
        result["excerpt"] = excerpt

    tags_raw = _extract("TAGS")
    if tags_raw:
        result["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    content = _extract("CONTENT")
    if content:
        result["content"] = content

    # Use title / excerpt as SEO defaults
    result["seo_title"] = result["title"]
    result["seo_description"] = result["excerpt"]
    result["og_title"] = result["title"]
    result["og_description"] = result["excerpt"]
    result["twitter_title"] = result["title"]
    result["twitter_description"] = result["excerpt"]

    return result


def _build_context_digest(entries: list[FeedEntry]) -> str:
    """Build a formatted context digest from RSS entries for the LLM."""
    if not entries:
        return "No specific source material provided. Write a general article on the assigned topic."

    parts = []
    for i, entry in enumerate(entries, 1):
        source = f"--- Source {i} ---\n"
        source += f"Title: {entry.title}\n"
        if entry.summary:
            source += f"Summary: {entry.summary[:500]}\n"
        if entry.content:
            # Strip HTML tags for the LLM context
            import re

            clean = re.sub(r"<[^>]+>", "", entry.content)[:2000]
            source += f"Content: {clean}\n"
        parts.append(source)

    return "\n\n".join(parts)
