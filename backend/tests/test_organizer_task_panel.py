from app.core.database import SessionLocal
from app.core.config import settings
from app.models import ReferenceItem, ReferenceSource
from tests.test_api import wait_for_scan
from tests.test_organizer import wait_for_organizer


def test_organizer_task_scan_create_summary_and_logs(client, media_root):
    video = media_root / "hhd800.com@ABW-249.mp4"
    video.write_bytes(b"video")

    with SessionLocal() as db:
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add(reference_source)
        db.flush()
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
        reference_source_id = reference_source.id

    scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    assert scan_response.status_code == 202, scan_response.text
    scan_body = scan_response.json()
    assert scan_body["source"]["root_path"] == str(media_root).replace("\\", "/")
    scan_job = wait_for_scan(client, scan_body["scan_job"]["id"])
    assert scan_job["status"] == "success"
    assert scan_job["scanned_count"] == 1

    create_job = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/吴猛/小姐姐/骑兵",
        "reference_scope_prefix": "骑兵/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    assert create_job.status_code == 202, create_job.text
    job = wait_for_organizer(client, create_job.json()["id"])
    assert job["status"] == "success"
    assert job["filename_strategy"] == "match_reference_filename_with_source_suffix"

    summary = client.get(f"/api/v1/organizer/task/jobs/{job['id']}/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["organizer_job_id"] == job["id"]
    assert body["source_root"] == str(media_root).replace("\\", "/")
    assert body["output_root"] == "/mnt/clouddrive/吴猛/小姐姐/骑兵"
    assert body["scanned_count"] == 1
    assert body["identified_count"] == 1
    assert body["ready_count"] == 1
    assert body["remaining_ready_count"] == 1

    logs = client.get(f"/api/v1/organizer/jobs/{job['id']}/executions")
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] == 0


def test_incremental_scan_and_organizer_only_process_changed_files(client, media_root):
    first = media_root / "ABW-249.mp4"
    first.write_bytes(b"video-1")

    with SessionLocal() as db:
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add(reference_source)
        db.flush()
        db.add_all([
            ReferenceItem(
                source_id=reference_source.id,
                identifier="ABW-249",
                reference_path="楠戝叺/A/ABW-249/ABW-249.strm",
                reference_dir="楠戝叺/A/ABW-249",
                filename="ABW-249.strm",
                ext="strm",
                size=1,
                status="identified",
            ),
            ReferenceItem(
                source_id=reference_source.id,
                identifier="CAWD-985",
                reference_path="楠戝叺/B/CAWD-985/CAWD-985.strm",
                reference_dir="楠戝叺/B/CAWD-985",
                filename="CAWD-985.strm",
                ext="strm",
                size=1,
                status="identified",
            ),
        ])
        db.commit()
        reference_source_id = reference_source.id

    scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    first_scan = wait_for_scan(client, scan_response.json()["scan_job"]["id"])
    assert first_scan["status"] == "success"
    assert first_scan["scanned_count"] == 1

    first_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/楠戝叺",
        "reference_scope_prefix": "楠戝叺/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    first_job = wait_for_organizer(client, first_job_response.json()["id"])
    first_summary = client.get(f"/api/v1/organizer/task/jobs/{first_job['id']}/summary").json()
    assert first_summary["ready_count"] == 1

    second_scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    second_scan = wait_for_scan(client, second_scan_response.json()["scan_job"]["id"])
    assert second_scan["status"] == "success"
    assert second_scan["scanned_count"] == 0

    unchanged_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/楠戝叺",
        "reference_scope_prefix": "楠戝叺/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    unchanged_job = wait_for_organizer(client, unchanged_job_response.json()["id"])
    unchanged_summary = client.get(f"/api/v1/organizer/task/jobs/{unchanged_job['id']}/summary").json()
    assert unchanged_summary["ready_count"] == 0

    second = media_root / "4k2.me@cawd-985.mp4"
    second.write_bytes(b"video-2")
    third_scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    third_scan = wait_for_scan(client, third_scan_response.json()["scan_job"]["id"])
    assert third_scan["status"] == "success"
    assert third_scan["scanned_count"] == 1

    delta_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/楠戝叺",
        "reference_scope_prefix": "楠戝叺/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    delta_job = wait_for_organizer(client, delta_job_response.json()["id"])
    delta_summary = client.get(f"/api/v1/organizer/task/jobs/{delta_job['id']}/summary").json()
    assert delta_summary["ready_count"] == 1

    items = client.get(f"/api/v1/organizer/jobs/{delta_job['id']}/items").json()["items"]
    assert len(items) == 1
    assert items[0]["identifier"] == "CAWD-985"


def test_reference_retry_picks_up_previous_missing_reference_after_reference_added(client, media_root):
    video = media_root / "DVMM-414.mp4"
    video.write_bytes(b"video")

    with SessionLocal() as db:
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add(reference_source)
        db.commit()
        reference_source_id = reference_source.id

    scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    first_scan = wait_for_scan(client, scan_response.json()["scan_job"]["id"])
    assert first_scan["status"] == "success"
    assert first_scan["scanned_count"] == 1

    first_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/楠戝叺",
        "reference_scope_prefix": "楠戝叺/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    first_job = wait_for_organizer(client, first_job_response.json()["id"])
    first_summary = client.get(f"/api/v1/organizer/task/jobs/{first_job['id']}/summary").json()
    assert first_summary["missing_reference_count"] == 1
    assert first_summary["ready_count"] == 0

    with SessionLocal() as db:
        db.add(ReferenceItem(
            source_id=reference_source_id,
            identifier="DVMM-414",
            reference_path="楠戝叺/A/DVMM-414/DVMM-414.strm",
            reference_dir="楠戝叺/A/DVMM-414",
            filename="DVMM-414.strm",
            ext="strm",
            size=1,
            status="identified",
        ))
        db.commit()

    second_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/楠戝叺",
        "reference_scope_prefix": "楠戝叺/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    second_job = wait_for_organizer(client, second_job_response.json()["id"])
    second_summary = client.get(f"/api/v1/organizer/task/jobs/{second_job['id']}/summary").json()
    assert second_summary["ready_count"] == 1
    assert second_summary["missing_reference_count"] == 0


def test_organizer_task_auto_syncs_reference_source_before_planning(client, media_root, tmp_path):
    video = media_root / "FNS-218.mp4"
    video.write_bytes(b"video")

    reference_root = tmp_path / "reference"
    target_dir = reference_root / "kibin" / "A" / "FNS-218"
    target_dir.mkdir(parents=True)
    (target_dir / "FNS-218.strm").write_text("", encoding="utf-8")

    with SessionLocal() as db:
        reference_source = ReferenceSource(
            name="STRM",
            provider_type="local_strm",
            root_path=str(reference_root),
        )
        db.add(reference_source)
        db.commit()
        reference_source_id = reference_source.id

    scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    first_scan = wait_for_scan(client, scan_response.json()["scan_job"]["id"])
    assert first_scan["status"] == "success"
    assert first_scan["scanned_count"] == 1

    job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/kibin",
        "reference_scope_prefix": "kibin/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    assert job_response.status_code == 202, job_response.text
    job = wait_for_organizer(client, job_response.json()["id"])
    summary = client.get(f"/api/v1/organizer/task/jobs/{job['id']}/summary").json()
    assert summary["ready_count"] == 1
    assert summary["missing_reference_count"] == 0


def test_reference_job_skips_item_when_target_already_exists(client, media_root):
    video = media_root / "CAWD-991.mp4"
    video.write_bytes(b"video")

    with SessionLocal() as db:
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add(reference_source)
        db.flush()
        db.add(ReferenceItem(
            source_id=reference_source.id,
            identifier="CAWD-991",
            reference_path="楠戝叺/A/CAWD-991/CAWD-991.strm",
            reference_dir="楠戝叺/A/CAWD-991",
            filename="CAWD-991.strm",
            ext="strm",
            size=1,
            status="identified",
        ))
        db.commit()
        reference_source_id = reference_source.id

    scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    first_scan = wait_for_scan(client, scan_response.json()["scan_job"]["id"])
    assert first_scan["status"] == "success"

    original_container_root = settings.clouddrive_container_root
    original_host_root = settings.clouddrive_host_root
    settings.clouddrive_container_root = str(media_root).replace("\\", "/")
    settings.clouddrive_host_root = str(media_root).replace("\\", "/")

    output_root = media_root / "output"
    target_dir = output_root / "A" / "CAWD-991"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "CAWD-991.mp4").write_bytes(b"already-moved")

    try:
        job_response = client.post("/api/v1/organizer/task/jobs", json={
            "source_root": str(media_root),
            "output_root": str(output_root).replace("\\", "/"),
            "reference_scope_prefix": "楠戝叺/",
            "reference_source_id": reference_source_id,
            "batch_limit": 100,
        })
        job = wait_for_organizer(client, job_response.json()["id"])
        summary = client.get(f"/api/v1/organizer/task/jobs/{job['id']}/summary").json()
        assert summary["ready_count"] == 0

        items = client.get(f"/api/v1/organizer/jobs/{job['id']}/items").json()["items"]
        assert len(items) == 1
        assert items[0]["status"] != "ready"
    finally:
        settings.clouddrive_container_root = original_container_root
        settings.clouddrive_host_root = original_host_root


def test_reference_retry_skips_item_when_source_file_no_longer_exists(client, media_root):
    video = media_root / "DVMM-414.mp4"
    video.write_bytes(b"video")

    with SessionLocal() as db:
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add(reference_source)
        db.commit()
        reference_source_id = reference_source.id

    scan_response = client.post("/api/v1/organizer/task/scan", json={
        "source_root": str(media_root),
        "name": "Task Source",
    })
    first_scan = wait_for_scan(client, scan_response.json()["scan_job"]["id"])
    assert first_scan["status"] == "success"

    first_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/retry",
        "reference_scope_prefix": "retry/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    first_job = wait_for_organizer(client, first_job_response.json()["id"])
    first_summary = client.get(f"/api/v1/organizer/task/jobs/{first_job['id']}/summary").json()
    assert first_summary["missing_reference_count"] == 1

    video.unlink()

    with SessionLocal() as db:
        db.add(ReferenceItem(
            source_id=reference_source_id,
            identifier="DVMM-414",
            reference_path="retry/A/DVMM-414/DVMM-414.strm",
            reference_dir="retry/A/DVMM-414",
            filename="DVMM-414.strm",
            ext="strm",
            size=1,
            status="identified",
        ))
        db.commit()

    second_job_response = client.post("/api/v1/organizer/task/jobs", json={
        "source_root": str(media_root),
        "output_root": "/mnt/clouddrive/test/retry",
        "reference_scope_prefix": "retry/",
        "reference_source_id": reference_source_id,
        "batch_limit": 100,
    })
    second_job = wait_for_organizer(client, second_job_response.json()["id"])
    second_summary = client.get(f"/api/v1/organizer/task/jobs/{second_job['id']}/summary").json()
    assert second_summary["ready_count"] == 0

    items = client.get(f"/api/v1/organizer/jobs/{second_job['id']}/items").json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "skipped"
    assert items[0]["error_message"] == "source_path does not exist on disk"
