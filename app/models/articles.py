from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class GeneratedArticle(TimestampMixin, Base):
    __tablename__ = "generated_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True)
    feed_entry_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list

    # Article content
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feature_image_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON list

    # SEO metadata
    seo_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seo_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    og_image: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    og_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    og_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    twitter_image: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    twitter_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    twitter_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Ghost integration
    ghost_post_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ghost_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)

    # Relationships for eager loading
    prompt: Mapped[Optional["Prompt"]] = relationship("Prompt", lazy="selectin")

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )  # draft, draft_sent, published, failed, skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<GeneratedArticle id={self.id} status={self.status!r} title={self.title!r}>"
