import os
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from app.core.config import validate_safety_flags
from app.metadata_providers import ManualCSVProvider
from tests.test_api import wait_for_scan


def test_safety_flags_reject_unsafe_startup():
    validate_safety_flags(SimpleNamespace(
        read_only_mode=True,
        enable_remote_write=False,
        enable_external_metadata=False,
        enable_real_move=False,
    ))
    validate_safety_flags(SimpleNamespace(
        read_only_mode=False,
        enable_remote_write=True,
        enable_external_metadata=False,
        enable_real_move=False,
    ))
    with pytest.raises(RuntimeError, match="ENABLE_REMOTE_WRITE"):
        validate_safety_flags(SimpleNamespace(
            read_only_mode=False,
            enable_remote_write=False,
            enable_external_metadata=False,
            enable_real_move=True,
        ))
    with pytest.raises(RuntimeError, match="READ_ONLY_MODE"):
        validate_safety_flags(SimpleNamespace(
            read_only_mode=True,
            enable_remote_write=False,
            enable_external_metadata=False,
            enable_real_move=True,
        ))
    with pytest.raises(RuntimeError, match="ENABLE_EXTERNAL_METADATA"):
        validate_safety_flags(SimpleNamespace(
            read_only_mode=True,
            enable_remote_write=False,
            enable_external_metadata=True,
            enable_real_move=False,
        ))


@pytest.mark.parametrize("environment_overrides", [
    {"ENABLE_EXTERNAL_METADATA": "true"},
    {"ENABLE_REAL_MOVE": "true"},
    {"READ_ONLY_MODE": "true", "ENABLE_REMOTE_WRITE": "true", "ENABLE_REAL_MOVE": "true"},
])
def test_application_import_refuses_unsafe_environment(environment_overrides):
    environment = os.environ.copy()
    environment.update(environment_overrides)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert any(name in result.stderr for name in ("ENABLE_EXTERNAL_METADATA", "ENABLE_REAL_MOVE", "READ_ONLY_MODE", "ENABLE_REMOTE_WRITE"))


def test_system_status(client, media_root):
    source = client.post("/api/v1/sources", json={
        "name": "Health source",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    })
    assert source.status_code == 201

    status = client.get("/api/v1/system/status")
    assert status.status_code == 200
    body = status.json()
    assert body["backend_status"] == "ok"
    assert body["sqlite_status"] == "ok"
    assert body["mount_readable"] is True
    assert body["source_count"] == 1
    assert body["read_only_mode"] is True
    assert body["enable_remote_write"] is False
    assert body["enable_external_metadata"] is False
    assert body["enable_real_move"] is False
    assert body["cms_sync_configured"] is False


def test_cms_sync_success(client, monkeypatch):
    class DummyResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self):
            return self.payload

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.services.cms_sync.settings.cms_sync_url", "http://example.test/sync")
    monkeypatch.setattr(
        "app.services.cms_sync.request.urlopen",
        lambda req, timeout=0: DummyResponse(b'{"ok":true}')
    )
    response = client.post("/api/v1/cms/sync")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["status_code"] == 200


def test_cms_sync_failure_returns_502(client, monkeypatch):
    monkeypatch.setattr("app.services.cms_sync.settings.cms_sync_url", "http://example.test/sync")

    def raise_error(req, timeout=0):
        raise HTTPError(req.full_url, 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr("app.services.cms_sync.request.urlopen", raise_error)
    response = client.post("/api/v1/cms/sync")
    assert response.status_code == 502, response.text
    assert "CMS 同步返回 HTTP 500" in response.text


def test_database_and_csv_backups(client, media_root):
    (media_root / "SSIS-001 backup.mp4").write_bytes(b"fake")
    source = client.post("/api/v1/sources", json={
        "name": "Backup source",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    }).json()
    job = client.post(f"/api/v1/sources/{source['id']}/scans").json()
    assert wait_for_scan(client, job["id"])["status"] == "success"

    csv_content = (
        "identifier,title,actors,studio,series,release_date,cover_url\n"
        "ssis001,Backup title,Actor A,Studio A,Series A,2025-01-01,/cover.jpg\n"
    )
    assert client.post("/api/v1/metadata/import/csv", content=csv_content.encode()).status_code == 200

    database = client.get("/api/v1/backups/index.db")
    assert database.status_code == 200
    assert database.content.startswith(b"SQLite format 3\x00")
    assert "index.db" in database.headers["content-disposition"]

    metadata = client.get("/api/v1/backups/metadata.csv")
    assert metadata.status_code == 200
    assert "SSIS-001" in metadata.text
    assert '[""Actor A""]' in metadata.text
    provider, errors = ManualCSVProvider.from_csv(metadata.text)
    assert errors == []
    assert provider.lookup("SSIS-001").title == "Backup title"

    files = client.get("/api/v1/backups/files.csv")
    assert files.status_code == 200
    assert "SSIS-001 backup.mp4" in files.text
