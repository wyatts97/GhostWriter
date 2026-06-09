"""RSS/Atom feed fetcher with content extraction and dedup."""

import asyncio
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.models.rss import FeedEntry, RSSFeed

logger = get_logger(__name__)

USER_AGENT = (
    "GhostWriter/1.0 (RSS Feed Reader; +https://github.com/yourusername/ghostwriter)"
)


async def fetch_feed(feed_id: int, session: AsyncSession) -> int:
    """Fetch a single RSS feed by ID, parse entries, and persist new ones.

    Returns the number of new entries added.
    """
    result = await session.execute(select(RSSFeed).where(RSSFeed.id == feed_id))
    feed = result.scalar_one_or_none()

    if not feed:
        logger.warning("rss_feed_not_found", feed_id=feed_id)
        return 0

    if not feed.active:
        logger.info("rss_feed_skipped_inactive", feed_name=feed.name)
        return 0

    try:
        raw_xml = await _fetch_url(feed.url)
    except Exception as exc:
        logger.error("rss_feed_fetch_error", feed_name=feed.name, url=feed.url, error=str(exc))
        return 0

    parsed = feedparser.parse(raw_xml)

    if parsed.bozo and not parsed.entries:
        logger.error(
            "rss_feed_parse_error",
            feed_name=feed.name,
            error=str(parsed.bozo_exception),
        )
        return 0

    new_count = 0

    for entry in parsed.entries:
        entry_url = _get_entry_url(entry)
        if not entry_url:
            continue

        # Dedup: check if URL already exists for this feed
        existing = await session.execute(
            select(FeedEntry).where(
                FeedEntry.feed_id == feed_id,
                FeedEntry.url == entry_url,
            )
        )
        if existing.scalar_one_or_none():
            continue

        # Extract content
        content = _extract_content(entry)
        summary = _extract_summary(entry)
        published = _parse_date(entry)

        feed_entry = FeedEntry(
            feed_id=feed_id,
            title=entry.get("title", "Untitled"),
            url=entry_url,
            content=content,
            summary=summary,
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
        )
        session.add(feed_entry)
        new_count += 1

    # Update last_fetched_at
    feed.last_fetched_at = datetime.now(timezone.utc)
    await session.commit()

    logger.info(
        "rss_feed_fetched",
        feed_name=feed.name,
        feed_entries=len(parsed.entries),
        new_entries=new_count,
    )

    return new_count


async def fetch_all_feeds(
    session: AsyncSession,
    max_concurrent: int = 5,
) -> dict[int, int]:
    """Fetch all active RSS feeds concurrently.

    Uses asyncio.gather with a semaphore to limit concurrent fetches.
    Returns a dict mapping feed_id -> new_entries_count.
    """
    result = await session.execute(select(RSSFeed).where(RSSFeed.active == True))  # noqa: E712
    feeds = result.scalars().all()

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _fetch_one(feed_id: int) -> tuple[int, int]:
        async with semaphore:
            count = await fetch_feed(feed_id, session)
            return feed_id, count

    tasks = [_fetch_one(f.id) for f in feeds]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[int, int] = {}
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.error("rss_concurrent_fetch_error", error=str(outcome))
        else:
            feed_id, count = outcome
            results[feed_id] = count

    return results


async def test_feed_url(url: str) -> dict[str, Any]:
    """Fetch and parse a feed URL without persisting.

    Returns a dict with feed metadata and the first 10 entries for preview.
    """
    try:
        raw_xml = await _fetch_url(url)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    parsed = feedparser.parse(raw_xml)

    if parsed.bozo and not parsed.entries:
        return {
            "success": False,
            "error": str(parsed.bozo_exception),
        }

    entries = []
    for entry in parsed.entries[:10]:
        entries.append(
            {
                "title": entry.get("title", "Untitled"),
                "url": _get_entry_url(entry),
                "summary": _extract_summary(entry)[:300] if _extract_summary(entry) else "",
                "published_at": (
                    _parse_date(entry).isoformat() if _parse_date(entry) else None
                ),
            }
        )

    feed_meta = {
        "title": parsed.feed.get("title", ""),
        "description": parsed.feed.get("subtitle", ""),
        "link": parsed.feed.get("link", ""),
    }

    return {
        "success": True,
        "feed": feed_meta,
        "entries": entries,
        "total_entries": len(parsed.entries),
    }


async def get_recent_entries(
    feed_ids: list[int],
    limit: int = 10,
    session: AsyncSession | None = None,
) -> list[FeedEntry]:
    """Get the most recent unused entries from specified feeds."""
    if not feed_ids:
        return []

    stmt = (
        select(FeedEntry)
        .where(FeedEntry.feed_id.in_(feed_ids))
        .where(FeedEntry.is_used == False)  # noqa: E712
        .order_by(FeedEntry.published_at.desc().nulls_last())
        .limit(limit)
    )

    if session:
        result = await session.execute(stmt)
        return list(result.scalars().all())

    return []


async def _fetch_url(url: str) -> str:
    """Fetch a URL and return the text content."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text


def _get_entry_url(entry: feedparser.FeedParserDict) -> str | None:
    """Extract the best URL from a feed entry."""
    if hasattr(entry, "link") and entry.link:
        return entry.link
    if hasattr(entry, "links") and entry.links:
        for link in entry.links:
            if link.get("rel") == "alternate" or link.get("rel") == "via":
                return link.get("href", "")
        return entry.links[0].get("href")
    return None


def _extract_content(entry: feedparser.FeedParserDict) -> str | None:
    """Extract the main content from a feed entry."""
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    if hasattr(entry, "summary") and entry.summary:
        return entry.summary
    if hasattr(entry, "description") and entry.description:
        return entry.description
    return None


def _extract_summary(entry: feedparser.FeedParserDict) -> str | None:
    """Extract a summary/description from a feed entry."""
    if hasattr(entry, "summary") and entry.summary:
        return entry.summary
    if hasattr(entry, "description") and entry.description:
        return entry.description
    if hasattr(entry, "content") and entry.content:
        text = entry.content[0].get("value", "")
        return text[:500] if text else None
    return None


def _parse_date(entry: feedparser.FeedParserDict) -> datetime | None:
    """Parse the published/updated date from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        time_tuple = getattr(entry, attr, None)
        if time_tuple:
            try:
                import calendar

                timestamp = calendar.timegm(time_tuple)
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                continue
    return None
