"""Resolve template variables in prompt content.

Available variables that can be used in system prompts:
  {{ today }}          — Current date, e.g. "June 09, 2026"
  {{ date }}           — Current date in ISO format, e.g. "2026-06-09"
  {{ feed_titles }}    — Comma-separated list of RSS feed names
  {{ feed_entry_count }} — Number of recent RSS entries available
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rss import RSSFeed

VARIABLE_DEFINITIONS: dict[str, dict[str, str]] = {
    "{{ today }}": {
        "description": "Current date, e.g. 'June 09, 2026'",
    },
    "{{ date }}": {
        "description": "Current date in ISO format, e.g. '2026-06-09'",
    },
    "{{ feed_titles }}": {
        "description": "Comma-separated list of RSS feed names linked to the schedule",
    },
    "{{ feed_entry_count }}": {
        "description": "Number of recent RSS entries available as source material",
    },
}


async def resolve_prompt_variables(
    content: str,
    feed_ids: list[int] | None = None,
    session: AsyncSession | None = None,
) -> str:
    """Replace template variables in prompt content with actual values."""
    now = datetime.now(timezone.utc)

    # Simple date replacements
    content = content.replace("{{ today }}", now.strftime("%B %d, %Y"))
    content = content.replace("{{ date }}", now.strftime("%Y-%m-%d"))

    # Feed variables — only resolve if the variable is actually used
    if "{{ feed_titles }}" in content or "{{ feed_entry_count }}" in content:
        feed_names: list[str] = []
        if feed_ids and session:
            result = await session.execute(
                select(RSSFeed).where(RSSFeed.id.in_(feed_ids))
            )
            feeds = result.scalars().all()
            feed_names = [f.name for f in feeds if f.active]

        content = content.replace(
            "{{ feed_titles }}",
            ", ".join(feed_names) if feed_names else "No feeds configured",
        )
        content = content.replace(
            "{{ feed_entry_count }}",
            str(len(feed_names)),
        )

    return content
