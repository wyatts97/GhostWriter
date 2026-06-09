from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    feed_ids: Mapped[str] = mapped_column(
        Text, default="[]"
    )  # JSON list of feed IDs
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    publish_mode: Mapped[str] = mapped_column(
        String(10), default="draft"
    )  # "draft" or "publish"
    max_articles_per_run: Mapped[int] = mapped_column(Integer, default=1)

    # Relationships for eager loading
    prompt: Mapped[Optional["Prompt"]] = relationship("Prompt", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Schedule id={self.id} name={self.name!r} active={self.active}>"
