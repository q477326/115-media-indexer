import time

from app.providers.local_fs import LocalFSProvider


def wait_for_scan(client, job_id, terminal=("success", "failed", "stopped"), timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/scans/{job_id}").json()
        if job["status"] in terminal:
            return job
        time.sleep(0.02)
    raise AssertionError(f"扫描任务 {job_id} 未在规定时间内结束")


def test_local_scan_search_and_csv(client, media_root):
    (media_root / "SSIS-001 sample.mp4").write_bytes(b"fake")
    (media_root / "notes.txt").write_text("metadata only", encoding="utf-8")
    (media_root / "cover.jpg").write_bytes(b"fake image")

    created = client.post("/api/v1/sources", json={
        "name": "CloudDrive2",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    })
    assert created.status_code == 201
    source_id = created.json()["id"]

    scan = client.post(f"/api/v1/sources/{source_id}/scans")
    assert scan.status_code == 202, scan.text
    completed = wait_for_scan(client, scan.json()["id"])
    assert completed["status"] == "success"
    assert completed["scanned_count"] == 1

    files = client.get("/api/v1/files", params={"q": "SSIS-001"}).json()
    assert files["total"] == 1
    assert files["items"][0]["identifier"] == "SSIS-001"

    exported = client.get("/api/v1/exports/files.csv", params={"q": "SSIS"})
    assert exported.status_code == 200
    assert "SSIS-001" in exported.text


def test_p115_is_mock_only(client):
    source = client.post("/api/v1/sources", json={
        "name": "Future 115",
        "provider_type": "p115",
        "root_file_id": "0",
    }).json()
    scan = client.post(f"/api/v1/sources/{source['id']}/scans")
    assert scan.status_code == 202
    completed = wait_for_scan(client, scan.json()["id"])
    assert completed["status"] == "failed"
    assert "仅保留接口" in completed["error_message"]


def test_scan_can_be_stopped_and_reports_progress(client, media_root, monkeypatch):
    for index in range(80):
        (media_root / f"MIDV-{index + 100:03}.mp4").write_bytes(b"fake")

    original = LocalFSProvider.get_file_metadata

    def slow_metadata(self, file):
        time.sleep(0.01)
        return original(self, file)

    monkeypatch.setattr(LocalFSProvider, "get_file_metadata", slow_metadata)
    source = client.post("/api/v1/sources", json={
        "name": "Stoppable",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    }).json()
    started = client.post(f"/api/v1/sources/{source['id']}/scans")
    assert started.status_code == 202
    job_id = started.json()["id"]

    deadline = time.time() + 3
    progress = None
    while time.time() < deadline:
        progress = client.get(f"/api/v1/scans/{job_id}").json()
        if progress["scanned_count"] > 0:
            break
        time.sleep(0.02)
    assert progress["scanned_count"] > 0
    assert progress["identified_count"] == progress["scanned_count"]

    stopped = client.post(f"/api/v1/scans/{job_id}/stop")
    assert stopped.status_code == 202
    completed = wait_for_scan(client, job_id)
    assert completed["status"] == "stopped"
    assert completed["scanned_count"] < 80
