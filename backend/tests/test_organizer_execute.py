from pathlib import Path
import shutil

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import OrganizerExecutionLog, ReferenceItem, ReferenceSource, Source
from app.models.media_file import MediaFile
from tests.test_organizer import wait_for_organizer


def seed_reference_ready_job(client, media_root):
    exec_root = Path("/mnt/exec-test")
    if exec_root.exists():
        shutil.rmtree(exec_root)
    raw_root = exec_root / "raw"
    target_root = exec_root / "output"
    raw_root.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)
    source_file = raw_root / "hhd800.com@ABW-249.mp4"
    source_file.write_bytes(b"video")
    settings.clouddrive_host_root = "/mnt/exec-test"
    settings.clouddrive_container_root = "/mnt/exec-test"

    with SessionLocal() as db:
        media_source = Source(name="CloudDrive2", provider_type="local_fs", root_path="/mnt/exec-test/raw")
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add_all([media_source, reference_source])
        db.flush()
        db.add(MediaFile(
            source_id=media_source.id,
            provider="local_fs",
            local_path=str(source_file),
            filename=source_file.name,
            path=str(source_file),
            size=source_file.stat().st_size,
            identifier="ABW-249",
            status="identified",
        ))
        db.add(ReferenceItem(
            source_id=reference_source.id,
            identifier="ABW-249",
            reference_path="骑兵/A/ABW-249/ABW-249.strm",
            reference_dir="骑兵/A/ABW-249",
            filename="ABW-249.strm",
            ext="strm",
            size=1,
            status="identified",
        ))
        db.commit()
        media_source_id = media_source.id
        reference_source_id = reference_source.id

    response = client.post("/api/v1/organizer/jobs", json={
        "mode": "reference_based",
        "source_id": media_source_id,
        "reference_source_id": reference_source_id,
        "reference_scope_prefix": "骑兵/",
        "output_root": str(target_root).replace("\\", "/"),
        "filename_strategy": "match_reference_filename_with_source_suffix",
    })
    job = wait_for_organizer(client, response.json()["id"])
    return job["id"], source_file, target_root


def test_execute_endpoint_blocked_by_default_flags(client, media_root, monkeypatch):
    job_id, _source_file, _target_root = seed_reference_ready_job(client, media_root)
    monkeypatch.setattr(settings, "clouddrive_host_root", "/mnt/exec-test")
    monkeypatch.setattr(settings, "clouddrive_container_root", "/mnt/exec-test")
    preflight = client.post(f"/api/v1/organizer/jobs/{job_id}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "preflight",
        "confirm": False,
    })
    assert preflight.status_code == 200, preflight.text
    preflight_body = preflight.json()
    assert preflight_body["requested_count"] == 1
    assert preflight_body["passed_count"] == 1
    assert preflight_body["items"][0]["source_exists"] is True
    assert preflight_body["items"][0]["target_exists"] is False

    response = client.post(f"/api/v1/organizer/jobs/{job_id}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "move",
        "confirm": True,
    })
    assert response.status_code == 409
    assert "ENABLE_REAL_MOVE" in response.json()["detail"]


def test_execute_ready_limit_move_success(client, media_root, monkeypatch):
    job_id, source_file, target_root = seed_reference_ready_job(client, media_root)
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_real_move", True)
    monkeypatch.setattr(settings, "clouddrive_host_root", "/mnt/exec-test")
    monkeypatch.setattr(settings, "clouddrive_container_root", "/mnt/exec-test")

    response = client.post(f"/api/v1/organizer/jobs/{job_id}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "move",
        "confirm": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested_count"] == 1
    assert body["moved_count"] == 1
    assert body["skipped_count"] == 0
    assert body["failed_count"] == 0

    target_file = target_root / "A" / "ABW-249" / "ABW-249.mp4"
    assert not source_file.exists()
    assert target_file.exists()

    with SessionLocal() as db:
        logs = db.query(OrganizerExecutionLog).filter(OrganizerExecutionLog.organizer_job_id == job_id).all()
        assert len(logs) == 1
        assert logs[0].status == "moved"
        assert logs[0].identifier == "ABW-249"

    api_logs = client.get(f"/api/v1/organizer/jobs/{job_id}/executions")
    assert api_logs.status_code == 200, api_logs.text
    assert api_logs.json()["items"][0]["identifier"] == "ABW-249"


def test_execute_skips_existing_target(client, media_root, monkeypatch):
    job_id, source_file, target_root = seed_reference_ready_job(client, media_root)
    target_dir = target_root / "A" / "ABW-249"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "ABW-249.mp4").write_bytes(b"existing")

    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_real_move", True)
    monkeypatch.setattr(settings, "clouddrive_host_root", "/mnt/exec-test")
    monkeypatch.setattr(settings, "clouddrive_container_root", "/mnt/exec-test")

    response = client.post(f"/api/v1/organizer/jobs/{job_id}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "move",
        "confirm": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["moved_count"] == 0
    assert body["skipped_count"] == 1
    assert body["failed_count"] == 0
    assert source_file.exists()


def test_preflight_skips_already_moved_items(client, media_root, monkeypatch):
    exec_root = Path("/mnt/exec-test")
    if exec_root.exists():
        shutil.rmtree(exec_root)
    raw_root = exec_root / "raw"
    target_root = exec_root / "output"
    raw_root.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)
    first_source = raw_root / "hhd800.com@ABW-249.mp4"
    second_source = raw_root / "ABW-250.mp4"
    first_source.write_bytes(b"video1")
    second_source.write_bytes(b"video2")
    settings.clouddrive_host_root = "/mnt/exec-test"
    settings.clouddrive_container_root = "/mnt/exec-test"

    with SessionLocal() as db:
        media_source = Source(name="CloudDrive2", provider_type="local_fs", root_path="/mnt/exec-test/raw")
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add_all([media_source, reference_source])
        db.flush()
        db.add_all([
            MediaFile(
                source_id=media_source.id,
                provider="local_fs",
                local_path=str(first_source),
                filename=first_source.name,
                path=str(first_source),
                size=first_source.stat().st_size,
                identifier="ABW-249",
                status="identified",
            ),
            MediaFile(
                source_id=media_source.id,
                provider="local_fs",
                local_path=str(second_source),
                filename=second_source.name,
                path=str(second_source),
                size=second_source.stat().st_size,
                identifier="ABW-250",
                status="identified",
            ),
        ])
        db.add_all([
            ReferenceItem(
                source_id=reference_source.id,
                identifier="ABW-249",
                reference_path="骑兵/A/ABW-249/ABW-249.strm",
                reference_dir="骑兵/A/ABW-249",
                filename="ABW-249.strm",
                ext="strm",
                size=1,
                status="identified",
            ),
            ReferenceItem(
                source_id=reference_source.id,
                identifier="ABW-250",
                reference_path="骑兵/A/ABW-250/ABW-250.strm",
                reference_dir="骑兵/A/ABW-250",
                filename="ABW-250.strm",
                ext="strm",
                size=1,
                status="identified",
            ),
        ])
        db.commit()
        media_source_id = media_source.id
        reference_source_id = reference_source.id

    response = client.post("/api/v1/organizer/jobs", json={
        "mode": "reference_based",
        "source_id": media_source_id,
        "reference_source_id": reference_source_id,
        "reference_scope_prefix": "骑兵/",
        "output_root": str(target_root).replace("\\", "/"),
        "filename_strategy": "match_reference_filename_with_source_suffix",
    })
    job_id = wait_for_organizer(client, response.json()["id"])["id"]

    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_real_move", True)
    monkeypatch.setattr(settings, "clouddrive_host_root", "/mnt/exec-test")
    monkeypatch.setattr(settings, "clouddrive_container_root", "/mnt/exec-test")

    move_response = client.post(f"/api/v1/organizer/jobs/{job_id}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "move",
        "confirm": True,
    })
    assert move_response.status_code == 200, move_response.text
    assert move_response.json()["moved_count"] == 1
    moved_item_id = move_response.json()["moved_samples"][0]["organizer_item_id"]

    preflight = client.post(f"/api/v1/organizer/jobs/{job_id}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "preflight",
        "confirm": False,
    })
    assert preflight.status_code == 200, preflight.text
    body = preflight.json()
    assert body["requested_count"] == 1
    assert body["passed_count"] == 1
    assert body["items"][0]["organizer_item_id"] != moved_item_id
