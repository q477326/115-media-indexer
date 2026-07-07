from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaMetadata(Base):
    __tablename__ = "metadata"

    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    plot: Mapped[str | None] = mapped_column(Text, nullable=True)
    actors: Mapped[list[str]] = mapped_column(JSON, default=list)
    studio: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    series: Mapped[str | None] = mapped_column(String(255), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_locked: Mapped[bool] = mapped_column(default=False)
    plot_locked: Mapped[bool] = mapped_column(default=False)
    actors_locked: Mapped[bool] = mapped_column(default=False)
    studio_locked: Mapped[bool] = mapped_column(default=False)
    series_locked: Mapped[bool] = mapped_column(default=False)
    release_date_locked: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(50), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
