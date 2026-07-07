from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.organizer import OrganizerJob
from app.models.scan_job import ScanJob


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StartupRecoveryResult:
    recovered_scan_jobs: int = 0
    recovered_organizer_jobs: int = 0


def recover_orphaned_jobs() -> StartupRecoveryResult:
    result = StartupRecoveryResult()
    db: Session = SessionLocal()
    try:
        now = utcnow()

        running_scans = db.scalars(select(ScanJob).where(ScanJob.status == "running")).all()
        for scan in running_scans:
            scan.status = "failed"
            scan.finished_at = now
            scan.error_message = "Recovered orphaned running scan after application restart."
        result.recovered_scan_jobs = len(running_scans)

        running_organizer_jobs = db.scalars(
            select(OrganizerJob).where(OrganizerJob.status.in_(["running", "pending"]))
        ).all()
        for job in running_organizer_jobs:
            job.status = "failed"
            job.finished_at = now
            if not job.error_message:
                job.error_message = "Recovered orphaned organizer job after application restart."
        result.recovered_organizer_jobs = len(running_organizer_jobs)

        db.commit()
        return result
    finally:
        db.close()
