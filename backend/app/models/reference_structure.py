from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReferenceSource(Base):
    __tablename__ = "reference_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    provider_type: Mapped[str] = mapped_column(String(30), default="local_strm", index=True)
    root_path: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    items = relationship("ReferenceItem", back_populates="source", cascade="all, delete-orphan")


class ReferenceItem(Base):
    __tablename__ = "reference_items"
    __table_args__ = (
        UniqueConstraint("source_id", "reference_path", name="uq_reference_source_path"),
        Index("ix_reference_items_source_identifier", "source_id", "identifier"),
        Index("ix_reference_items_source_status", "source_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("reference_sources.id", ondelete="CASCADE"), index=True)
    identifier: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    reference_path: Mapped[str] = mapped_column(Text)
    reference_dir: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    ext: Mapped[str] = mapped_column(String(20))
    size: Mapped[int] = mapped_column(Integer, default=0)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="identified", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source = relationship("ReferenceSource", back_populates="items")
