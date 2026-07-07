from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizerJob(Base):
    __tablename__ = "organizer_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_template: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(30), index=True)
    mode: Mapped[str] = mapped_column(String(30), default="template_based", index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reference_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reference_scope_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename_strategy: Mapped[str] = mapped_column(String(80), default="preserve_source_filename")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    status_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items = relationship("OrganizerItem", back_populates="job", cascade="all, delete-orphan")


class OrganizerItem(Base):
    __tablename__ = "organizer_items"
    __table_args__ = (
        UniqueConstraint("job_id", "media_file_id", name="uq_organizer_job_file"),
        Index("ix_organizer_items_job_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("organizer_jobs.id", ondelete="CASCADE"), index=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    identifier: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    rule_template: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job = relationship("OrganizerJob", back_populates="items")
