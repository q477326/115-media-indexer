import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict
from datetime import date, datetime, timezone
from threading import Event

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.metadata_providers import MetadataRecord
from app.metadata_providers.registry import create_providers
from app.models import MediaMetadata, MetadataEnrichmentJob, MetadataProviderCache, MetadataTaskLog
from app.services.metadata import upsert_record


def score_record(record: MetadataRecord) -> float:
    score = 0.35 if record.identifier else 0.0
    score += 0.15 if record.title else 0.0
    score += 0.05 if record.plot else 0.0
    score += 0.15 if record.actors else 0.0
    score += 0.10 if record.studio else 0.0
    score += 0.10 if record.release_date else 0.0
    score += 0.05 if record.series else 0.0
    score += 0.05 if record.cover_url else 0.0
    score += min(max(record.confidence, 0.0), 1.0) * 0.05
    return round(min(score, 1.0), 4)


def record_payload(record: MetadataRecord) -> dict:
    payload = asdict(record)
    payload["release_date"] = record.release_date.isoformat() if record.release_date else None
    return payload


def record_from_payload(payload: dict) -> MetadataRecord:
    data = dict(payload)
    if data.get("release_date") and isinstance(data["release_date"], str):
        data["release_date"] = date.fromisoformat(data["release_date"])
    return MetadataRecord(**data)


def metadata_record(item: MediaMetadata | None) -> MetadataRecord | None:
    if item is None:
        return None
    return MetadataRecord(
        identifier=item.identifier,
        title=item.title,
        plot=item.plot,
        actors=list(item.actors or []),
        studio=item.studio,
        series=item.series,
        release_date=item.release_date,
        cover_url=item.cover_url,
        title_locked=item.title_locked,
        plot_locked=item.plot_locked,
        actors_locked=item.actors_locked,
        studio_locked=item.studio_locked,
        series_locked=item.series_locked,
        release_date_locked=item.release_date_locked,
        source=item.source,
        confidence=item.confidence,
        status=item.status,
    )


def merge_empty_fields(base: MetadataRecord | None, incoming: MetadataRecord) -> tuple[MetadataRecord, bool]:
    if base is None:
        return incoming, True
    values = {
        "title": base.title,
        "plot": base.plot,
        "actors": list(base.actors),
        "studio": base.studio,
        "series": base.series,
        "release_date": base.release_date,
        "cover_url": base.cover_url,
    }
    lock_fields = {
        "title": base.title_locked,
        "plot": base.plot_locked,
        "actors": base.actors_locked,
        "studio": base.studio_locked,
        "series": base.series_locked,
        "release_date": base.release_date_locked,
    }
    changed = False
    for field in values:
        if field in lock_fields and lock_fields[field]:
            continue
        current = values[field]
        candidate = getattr(incoming, field)
        if (current is None or current == [] or current == "") and candidate not in (None, [], ""):
            values[field] = candidate
            changed = True
    source = "aggregator" if changed and base.source != incoming.source else base.source
    merged = MetadataRecord(
        identifier=base.identifier,
        **values,
        title_locked=base.title_locked,
        plot_locked=base.plot_locked,
        actors_locked=base.actors_locked,
        studio_locked=base.studio_locked,
        series_locked=base.series_locked,
        release_date_locked=base.release_date_locked,
        source=source,
        confidence=max(base.confidence, incoming.confidence),
        status=base.status,
    )
    return merged, changed


def _cache_lookup(db: Session, provider_name: str, identifier: str) -> MetadataRecord | None:
    if provider_name == "local_db":
        return None
    now = datetime.now(timezone.utc)
    cached = db.scalar(select(MetadataProviderCache).where(
        MetadataProviderCache.provider == provider_name,
        MetadataProviderCache.identifier == identifier,
        MetadataProviderCache.status == "hit",
        or_(MetadataProviderCache.expires_at.is_(None), MetadataProviderCache.expires_at > now),
    ))
    return record_from_payload(cached.payload) if cached and cached.payload else None


def _cache_write(db: Session, provider_name: str, record: MetadataRecord, score: float) -> None:
    cached = db.scalar(select(MetadataProviderCache).where(
        MetadataProviderCache.provider == provider_name,
        MetadataProviderCache.identifier == record.identifier,
    ))
    if cached is None:
        cached = MetadataProviderCache(provider=provider_name, identifier=record.identifier)
        db.add(cached)
    cached.payload = record_payload(record)
    cached.confidence = score
    cached.status = "hit"
    cached.fetched_at = datetime.now(timezone.utc)


def _add_log(db, job_id, identifier, provider, status, duration_ms=0, error=None, attempt=1, score=None):
    db.add(MetadataTaskLog(
        job_id=job_id,
        identifier=identifier,
        provider=provider,
        status=status,
        duration_ms=duration_ms,
        error_message=error,
        attempt=attempt,
        score=score,
    ))


def _lookup_provider(provider, identifier):
    logs = []
    for attempt in range(1, provider.max_retries + 2):
        started = time.perf_counter()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"provider-{provider.provider_name}")
        future = executor.submit(provider.lookup, identifier)
        try:
            record = future.result(timeout=provider.timeout_seconds)
            duration = int((time.perf_counter() - started) * 1000)
            status = record.status if record and record.status == "disabled" else "hit" if record else "miss"
            logs.append((status, duration, record.error_message if record else None, attempt, record))
            executor.shutdown(wait=False, cancel_futures=True)
            return record, logs
        except FutureTimeout:
            duration = int((time.perf_counter() - started) * 1000)
            future.cancel()
            logs.append(("timeout", duration, "Provider 查询超时", attempt, None))
        except Exception as exc:
            duration = int((time.perf_counter() - started) * 1000)
            logs.append(("error", duration, str(exc), attempt, None))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if attempt <= provider.max_retries:
            time.sleep(min(2 ** (attempt - 1), 2))
    return None, logs


def run_enrichment_job(db: Session, job_id: int, stop_event: Event) -> None:
    job = db.get(MetadataEnrichmentJob, job_id)
    if job is None:
        return
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    try:
        providers = create_providers(job.provider_names)
        for identifier in job.identifiers:
            if stop_event.is_set():
                job.status = "stopped"
                break
            existing = db.scalar(select(MediaMetadata).where(MediaMetadata.identifier == identifier))
            aggregate = metadata_record(existing)
            changed = False

            for provider in providers:
                if stop_event.is_set():
                    job.status = "stopped"
                    break
                cached = _cache_lookup(db, provider.provider_name, identifier)
                if cached is not None:
                    score = score_record(cached)
                    _add_log(db, job.id, identifier, provider.provider_name, "cache_hit", score=score)
                    aggregate, did_change = merge_empty_fields(aggregate, cached)
                    changed = changed or did_change
                else:
                    result, logs = _lookup_provider(provider, identifier)
                    for status, duration, error, attempt, logged_result in logs:
                        result_score = score_record(logged_result) if logged_result and status == "hit" else None
                        _add_log(db, job.id, identifier, provider.provider_name, status, duration, error, attempt, result_score)
                    if result and result.status != "disabled":
                        score = score_record(result)
                        _cache_write(db, provider.provider_name, result, score)
                        aggregate, did_change = merge_empty_fields(aggregate, result)
                        changed = changed or did_change
                db.commit()
                if aggregate and score_record(aggregate) >= 0.70:
                    break

            if job.status == "stopped":
                db.commit()
                break
            if aggregate is None or score_record(aggregate) <= 0.35:
                job.failed_count += 1
            elif existing is None or changed:
                final_score = score_record(aggregate)
                aggregate = MetadataRecord(
                    **{**asdict(aggregate), "confidence": final_score, "status": "complete" if final_score >= 0.70 else "partial"}
                )
                upsert_record(db, aggregate)
                job.completed_count += 1
            else:
                job.unchanged_count += 1
            job.processed_count += 1
            db.commit()

        if job.status != "stopped":
            job.status = "success" if job.failed_count == 0 else "partial"
    except Exception as exc:
        db.rollback()
        job = db.get(MetadataEnrichmentJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)
    finally:
        if job:
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
