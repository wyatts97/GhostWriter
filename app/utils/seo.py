"""SEO optimization utilities for generated articles."""

import re
from typing import Optional


def optimize_title(title: str, max_length: int = 70) -> str:
    """Clean and truncate a title to SEO-friendly length.

    Ensures the title is under max_length chars, strips quotes
    and special characters that hurt SEO.
    """
    # Strip leading/trailing whitespace and quotes
    title = title.strip().strip('"').strip("'").strip()

    # Remove excessive special characters
    title = re.sub(r'[{}[\]()<>]', '', title)

    # Truncate at word boundary
    if len(title) <= max_length:
        return title

    truncated = title[:max_length]
    # Cut at last space to avoid word splitting
    last_space = truncated.rfind(' ')
    if last_space > 30:  # Only cut if we have enough context
        truncated = truncated[:last_space]

    return truncated.strip().rstrip(',.!') + ''


def optimize_meta_description(description: str, max_length: int = 160) -> str:
    """Clean and truncate meta description to optimal length."""
    if not description:
        return ""

    description = description.strip().strip('"').strip("'").strip()

    if len(description) <= max_length:
        return description

    truncated = description[:max_length]
    last_space = truncated.rfind(' ')
    if last_space > 80:
        truncated = truncated[:last_space]

    return truncated.strip().rstrip(',.!') + ''


def generate_slug(title: str) -> str:
    """Generate a URL-friendly slug from a title."""
    # Lowercase
    slug = title.lower()
    # Remove special chars
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    # Replace spaces with hyphens
    slug = re.sub(r'[\s]+', '-', slug.strip())
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    return slug[:100]  # Limit length


def validate_headings(html_content: str) -> list[str]:
    """Check heading hierarchy in HTML content.

    Returns a list of warnings about heading structure.
    """
    warnings = []
    h1_count = len(re.findall(r'<h1[^>]*>', html_content, re.IGNORECASE))
    h2_tags = re.findall(r'<h2[^>]*>', html_content, re.IGNORECASE)
    h3_tags = re.findall(r'<h3[^>]*>', html_content, re.IGNORECASE)

    if h1_count == 0:
        warnings.append("Content has no H1 heading")
    elif h1_count > 1:
        warnings.append(f"Content has {h1_count} H1 headings (should be exactly 1)")

    if h2_tags and h3_tags:
        # Check that H3s come after at least one H2
        pass  # Basic hierarchy check

    if not h2_tags and len(html_content) > 500:
        warnings.append("Long content has no H2 subheadings")

    return warnings


def estimate_keyword_density(text: str, keyword: str) -> float:
    """Calculate the percentage density of a keyword in text."""
    words = text.lower().split()
    if not words:
        return 0.0

    keyword_lower = keyword.lower()
    keyword_count = sum(1 for w in words if keyword_lower in w)
    return (keyword_count / len(words)) * 100


def build_seo_prompt_instructions() -> str:
    """Returns a system prompt fragment that instructs the LLM on SEO best practices.

    Embed this in the system prompt for article generation.
    """
    return """SEO REQUIREMENTS for the article:
- Title: under 70 characters, include primary keyword near the beginning, compelling
- Meta description: 150-160 characters, include primary keyword + call to action
- Content: use proper heading hierarchy (H1 title, H2 sections, H3 subsections)
- First paragraph: hook the reader, include primary keyword naturally
- Article length: 1500-2500 words, comprehensive coverage
- Include 3-5 relevant tags
- Write in a professional but engaging tone
- Use short paragraphs (2-4 sentences)
- Include transitional phrases between sections
- Avoid keyword stuffing - use natural language
"""
