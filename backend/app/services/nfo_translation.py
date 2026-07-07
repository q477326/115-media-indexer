from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.translation import TranslationItem, TranslationJob, TranslationWatchFolder
from app.services.ai_translation import ensure_translation_write_enabled, translate_title_and_plot

FINAL_JOB_STATUSES = {"success", "failed", "stopped"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_translation_root(folder_path: str) -> Path:
    candidate = Path(folder_path).resolve()
    allowed = settings.allowed_translation_roots
    if not any(candidate == root or root in candidate.parents for root in allowed):
        allowed_display = ", ".join(str(root) for root in allowed)
        raise ValueError(f"folder_path 必须位于允许的翻译目录下：{allowed_display}")
    if not candidate.exists():
        raise OSError(f"目录不存在：{candidate}")
    if not candidate.is_dir():
        raise OSError(f"不是目录：{candidate}")
    return candidate


def list_nfo_files(folder_path: str) -> list[Path]:
    root = validate_translation_root(folder_path)
    return sorted(path for path in root.rglob("*.nfo") if path.is_file())


def read_nfo_fields(path: Path) -> tuple[ET.ElementTree, ET.Element, dict[str, str | None]]:
    tree = ET.parse(path)
    root = tree.getroot()

    def find_text(tag: str) -> str | None:
        node = root.find(tag)
        if node is None or node.text is None:
            return None
        value = node.text.strip()
        return value or None

    return tree, root, {
        "title": find_text("title"),
        "originaltitle": find_text("originaltitle"),
        "plot": find_text("plot"),
        "originalplot": find_text("originalplot"),
    }


def choose_source_texts(fields: dict[str, str | None]) -> tuple[str | None, str | None, str | None, str | None]:
    source_title_field = "originaltitle" if fields.get("originaltitle") else "title" if fields.get("title") else None
    source_plot_field = "originalplot" if fields.get("originalplot") else "plot" if fields.get("plot") else None
    source_title = fields.get(source_title_field) if source_title_field else None
    source_plot = fields.get(source_plot_field) if source_plot_field else None
    return source_title, source_plot, source_title_field, source_plot_field


def _ensure_child(root: ET.Element, tag: str) -> ET.Element:
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    return node


def _normalize_plot_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def write_translated_nfo(path: Path, *, title: str | None, plot: str | None) -> None:
    tree, root, fields = read_nfo_fields(path)
    changed = False
    if title and title != (fields.get("title") or ""):
        _ensure_child(root, "title").text = title
        changed = True
    plot = _normalize_plot_text(plot)
    if plot and plot != (fields.get("plot") or ""):
        _ensure_child(root, "plot").text = plot
        changed = True
    if not changed:
        return
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _create_item(
    db: Session,
    *,
    job_id: int,
    file_path: str,
    source_title: str | None,
    source_plot: str | None,
    source_title_field: str | None,
    source_plot_field: str | None,
    status: str,
    translated_title: str | None = None,
    translated_plot: str | None = None,
    error_message: str | None = None,
) -> TranslationItem:
    item = TranslationItem(
        job_id=job_id,
        file_path=file_path,
        source_title=source_title,
        source_plot=source_plot,
        source_title_field=source_title_field,
        source_plot_field=source_plot_field,
        translated_title=translated_title,
        translated_plot=translated_plot,
        status=status,
        error_message=error_message,
    )
    db.add(item)
    return item


def _clean_ai_result(result: dict[str, str], fields: dict[str, str | None]) -> tuple[str | None, str | None]:
    title = (result.get("title") or "").strip()
    plot = _normalize_plot_text(result.get("plot"))
    if not title:
        title = fields.get("title") or fields.get("originaltitle")
    if not plot:
        plot = _normalize_plot_text(fields.get("plot") or fields.get("originalplot"))
    return title or None, plot or None


def refresh_translation_job_counts(db: Session, job_id: int) -> TranslationJob:
    job = db.get(TranslationJob, job_id)
    if not job:
        raise ValueError("translation job not found")

    total = db.scalar(select(func.count()).select_from(TranslationItem).where(TranslationItem.job_id == job_id)) or 0
    translated = db.scalar(
        select(func.count()).select_from(TranslationItem).where(
            TranslationItem.job_id == job_id,
            TranslationItem.status == "translated",
        )
    ) or 0
    skipped = db.scalar(
        select(func.count()).select_from(TranslationItem).where(
            TranslationItem.job_id == job_id,
            TranslationItem.status == "skipped",
        )
    ) or 0
    failed = db.scalar(
        select(func.count()).select_from(TranslationItem).where(
            TranslationItem.job_id == job_id,
            TranslationItem.status == "failed",
        )
    ) or 0

    job.total_count = total
    job.processed_count = total
    job.translated_count = translated
    job.skipped_count = skipped
    job.failed_count = failed
    job.status = "success" if failed == 0 else "partial"
    if job.started_at is None:
        job.started_at = utcnow()
    job.finished_at = utcnow()
    return job


def retry_translation_item(db: Session, item_id: int) -> TranslationItem:
    item = db.get(TranslationItem, item_id)
    if not item:
        raise ValueError("translation item not found")
    job = db.get(TranslationJob, item.job_id)
    if not job:
        raise ValueError("translation job not found")

    file_path = Path(item.file_path)
    if not file_path.exists() or not file_path.is_file():
        item.status = "failed"
        item.error_message = f"文件不存在：{file_path}"
        refresh_translation_job_counts(db, item.job_id)
        db.commit()
        db.refresh(item)
        return item

    try:
        if job.mode == "translate":
            ensure_translation_write_enabled(db)

        tree, root_node, fields = read_nfo_fields(file_path)
        del tree, root_node
        source_title, source_plot, source_title_field, source_plot_field = choose_source_texts(fields)

        item.source_title = source_title
        item.source_plot = source_plot
        item.source_title_field = source_title_field
        item.source_plot_field = source_plot_field
        item.error_message = None

        if not source_title and not source_plot:
            item.translated_title = None
            item.translated_plot = None
            item.status = "skipped"
            item.error_message = "未找到可用的 title / plot 源字段"
        elif job.mode == "analyze":
            item.translated_title = None
            item.translated_plot = None
            item.status = "candidate"
        else:
            result = translate_title_and_plot(
                db,
                prompt_template=job.prompt_template,
                source_title=source_title,
                source_plot=source_plot,
                current_title=fields.get("title"),
                current_plot=fields.get("plot"),
            )
            translated_title, translated_plot = _clean_ai_result(result, fields)
            write_translated_nfo(file_path, title=translated_title, plot=translated_plot)
            item.translated_title = translated_title
            item.translated_plot = translated_plot
            item.status = "translated"

    except Exception as exc:
        item.status = "failed"
        item.error_message = str(exc)

    refresh_translation_job_counts(db, item.job_id)
    db.commit()
    db.refresh(item)
    return item


def run_translation_job(db: Session, job_id: int, stop_event: Event | None = None) -> None:
    job = db.get(TranslationJob, job_id)
    if not job:
        raise ValueError("translation job not found")
    if job.status in FINAL_JOB_STATUSES:
        return

    try:
        root = validate_translation_root(job.folder_path)
        files = sorted(path for path in root.rglob("*.nfo") if path.is_file())
        job.status = "running"
        job.started_at = utcnow()
        job.total_count = len(files)
        job.processed_count = 0
        job.translated_count = 0
        job.skipped_count = 0
        job.failed_count = 0
        job.error_message = None
        db.query(TranslationItem).filter(TranslationItem.job_id == job.id).delete()
        db.commit()

        if job.mode == "translate":
            ensure_translation_write_enabled(db)

        for file_path in files:
            if stop_event and stop_event.is_set():
                job.status = "stopped"
                break
            try:
                tree, root_node, fields = read_nfo_fields(file_path)
                del tree, root_node
                source_title, source_plot, source_title_field, source_plot_field = choose_source_texts(fields)
                if not source_title and not source_plot:
                    _create_item(
                        db,
                        job_id=job.id,
                        file_path=str(file_path),
                        source_title=None,
                        source_plot=None,
                        source_title_field=None,
                        source_plot_field=None,
                        status="skipped",
                        error_message="未找到可用的 title / plot 源字段",
                    )
                    job.skipped_count += 1
                elif job.mode == "analyze":
                    _create_item(
                        db,
                        job_id=job.id,
                        file_path=str(file_path),
                        source_title=source_title,
                        source_plot=source_plot,
                        source_title_field=source_title_field,
                        source_plot_field=source_plot_field,
                        status="candidate",
                    )
                    job.translated_count += 1
                else:
                    result = translate_title_and_plot(
                        db,
                        prompt_template=job.prompt_template,
                        source_title=source_title,
                        source_plot=source_plot,
                        current_title=fields.get("title"),
                        current_plot=fields.get("plot"),
                    )
                    translated_title, translated_plot = _clean_ai_result(result, fields)
                    write_translated_nfo(file_path, title=translated_title, plot=translated_plot)
                    _create_item(
                        db,
                        job_id=job.id,
                        file_path=str(file_path),
                        source_title=source_title,
                        source_plot=source_plot,
                        source_title_field=source_title_field,
                        source_plot_field=source_plot_field,
                        translated_title=translated_title,
                        translated_plot=translated_plot,
                        status="translated",
                    )
                    job.translated_count += 1
                job.processed_count += 1
                db.commit()
            except Exception as exc:
                _create_item(
                    db,
                    job_id=job.id,
                    file_path=str(file_path),
                    source_title=None,
                    source_plot=None,
                    source_title_field=None,
                    source_plot_field=None,
                    status="failed",
                    error_message=str(exc),
                )
                job.processed_count += 1
                job.failed_count += 1
                db.commit()

        if job.status != "stopped":
            job.status = "success" if job.failed_count == 0 else "partial"
        job.finished_at = utcnow()
        db.commit()
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = utcnow()
        db.commit()


def run_translation_file_job(db: Session, job_id: int, file_path: str, stop_event: Event | None = None) -> None:
    job = db.get(TranslationJob, job_id)
    if not job:
        raise ValueError("translation job not found")
    if job.status in FINAL_JOB_STATUSES:
        return

    try:
        target = Path(file_path).resolve()
        root = validate_translation_root(str(target.parent))
        if target.parent != root:
            raise ValueError("single translation file must be directly inside the target folder")
        if not target.exists() or not target.is_file() or target.suffix.lower() != ".nfo":
            raise FileNotFoundError(f"NFO file not found: {target}")

        job.status = "running"
        job.started_at = utcnow()
        job.total_count = 1
        job.processed_count = 0
        job.translated_count = 0
        job.skipped_count = 0
        job.failed_count = 0
        job.error_message = None
        db.query(TranslationItem).filter(TranslationItem.job_id == job.id).delete()
        db.commit()

        if job.mode == "translate":
            ensure_translation_write_enabled(db)

        if stop_event and stop_event.is_set():
            job.status = "stopped"
        else:
            try:
                tree, root_node, fields = read_nfo_fields(target)
                del tree, root_node
                source_title, source_plot, source_title_field, source_plot_field = choose_source_texts(fields)
                if not source_title and not source_plot:
                    _create_item(
                        db,
                        job_id=job.id,
                        file_path=str(target),
                        source_title=None,
                        source_plot=None,
                        source_title_field=None,
                        source_plot_field=None,
                        status="skipped",
                        error_message="未找到可用的 title / plot 源字段",
                    )
                    job.skipped_count += 1
                elif job.mode == "analyze":
                    _create_item(
                        db,
                        job_id=job.id,
                        file_path=str(target),
                        source_title=source_title,
                        source_plot=source_plot,
                        source_title_field=source_title_field,
                        source_plot_field=source_plot_field,
                        status="candidate",
                    )
                    job.translated_count += 1
                else:
                    result = translate_title_and_plot(
                        db,
                        prompt_template=job.prompt_template,
                        source_title=source_title,
                        source_plot=source_plot,
                        current_title=fields.get("title"),
                        current_plot=fields.get("plot"),
                    )
                    translated_title, translated_plot = _clean_ai_result(result, fields)
                    write_translated_nfo(target, title=translated_title, plot=translated_plot)
                    _create_item(
                        db,
                        job_id=job.id,
                        file_path=str(target),
                        source_title=source_title,
                        source_plot=source_plot,
                        source_title_field=source_title_field,
                        source_plot_field=source_plot_field,
                        translated_title=translated_title,
                        translated_plot=translated_plot,
                        status="translated",
                    )
                    job.translated_count += 1
                job.processed_count = 1
                db.commit()
            except Exception as exc:
                _create_item(
                    db,
                    job_id=job.id,
                    file_path=str(target),
                    source_title=None,
                    source_plot=None,
                    source_title_field=None,
                    source_plot_field=None,
                    status="failed",
                    error_message=str(exc),
                )
                job.processed_count = 1
                job.failed_count = 1
                db.commit()

        if job.status != "stopped":
            job.status = "success" if job.failed_count == 0 else "partial"
        job.finished_at = utcnow()
        db.commit()
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = utcnow()
        db.commit()


def create_or_update_watch_folder(
    db: Session,
    *,
    name: str,
    folder_path: str,
    prompt_template: str,
    enabled: bool,
    recursive: bool = True,
    auto_translate: bool = False,
) -> TranslationWatchFolder:
    normalized = str(validate_translation_root(folder_path))
    existing = db.scalar(select(TranslationWatchFolder).where(TranslationWatchFolder.folder_path == normalized))
    if existing:
        existing.name = name.strip()
        existing.prompt_template = prompt_template.strip()
        existing.enabled = enabled
        existing.recursive = recursive
        existing.auto_translate = auto_translate
        if not auto_translate:
            existing.monitor_initialized = False
        db.commit()
        db.refresh(existing)
        return existing
    item = TranslationWatchFolder(
        name=name.strip(),
        folder_path=normalized,
        prompt_template=prompt_template.strip(),
        enabled=enabled,
        recursive=recursive,
        auto_translate=auto_translate,
        monitor_initialized=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
