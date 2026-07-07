from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TranslationWatchFolder(Base):
    __tablename__ = "translation_watch_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    folder_path: Mapped[str] = mapped_column(Text, unique=True)
    prompt_template: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_translate: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    monitor_initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TranslationFileState(Base):
    __tablename__ = "translation_file_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_folder_id: Mapped[int] = mapped_column(ForeignKey("translation_watch_folders.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(Text, unique=True)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    last_job_id: Mapped[int | None] = mapped_column(ForeignKey("translation_jobs.id", ondelete="SET NULL"), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="seen", index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TranslationAPISettings(Base):
    __tablename__ = "translation_api_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(80), default="openai-compatible")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(Text, default="https://api.openai.com/v1")
    model_name: Mapped[str] = mapped_column(String(120), default="gpt-4.1-mini")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TranslationJob(Base):
    __tablename__ = "translation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_folder_id: Mapped[int | None] = mapped_column(ForeignKey("translation_watch_folders.id", ondelete="SET NULL"), nullable=True)
    folder_path: Mapped[str] = mapped_column(Text)
    prompt_template: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    translated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TranslationItem(Base):
    __tablename__ = "translation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("translation_jobs.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(Text, index=True)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_plot: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_plot: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_title_field: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_plot_field: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
