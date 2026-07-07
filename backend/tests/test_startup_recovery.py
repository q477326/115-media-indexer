from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.organizer import OrganizerJob
from app.models.scan_job import ScanJob
from app.models.source import Source
from app.services.startup_recovery import recover_orphaned_jobs


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_recover_orphaned_jobs_marks_running_scan_and_organizer_failed():
    db = SessionLocal()
    source = Source(name="test", provider_type="local_fs", root_path="/tmp", enabled=True)
    db.add(source)
    db.flush()

    scan = ScanJob(source_id=source.id, status="running", started_at=utcnow())
    organizer = OrganizerJob(
        rule_template="{identifier}",
        scope="all",
        mode="reference_based",
        status="running",
        started_at=utcnow(),
    )
    db.add_all([scan, organizer])
    db.commit()
    db.close()

    result = recover_orphaned_jobs()
    assert result.recovered_scan_jobs == 1
    assert result.recovered_organizer_jobs == 1

    db = SessionLocal()
    recovered_scan = db.get(ScanJob, scan.id)
    recovered_organizer = db.get(OrganizerJob, organizer.id)

    assert recovered_scan is not None
    assert recovered_scan.status == "failed"
    assert recovered_scan.finished_at is not None
    assert recovered_scan.error_message == "Recovered orphaned running scan after application restart."

    assert recovered_organizer is not None
    assert recovered_organizer.status == "failed"
    assert recovered_organizer.finished_at is not None
    assert recovered_organizer.error_message == "Recovered orphaned organizer job after application restart."
    db.close()
