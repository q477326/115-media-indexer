from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizerExecutionLog(Base):
    __tablename__ = "organizer_execution_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_job_id: Mapped[int] = mapped_column(ForeignKey("organizer_jobs.id", ondelete="CASCADE"), index=True)
    organizer_item_id: Mapped[int] = mapped_column(ForeignKey("organizer_items.id", ondelete="CASCADE"), index=True)
    identifier: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_path: Mapped[str] = mapped_column(Text)
    display_target_path: Mapped[str] = mapped_column(Text)
    container_target_path: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
