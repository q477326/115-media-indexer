import time
from datetime import datetime, timezone

import pytest

from app.core.database import SessionLocal
from app.metadata_providers.local_db import LocalDBProvider
from app.metadata_providers.base import MetadataRecord
from app.metadata_providers.registry import validate_provider_registry
from app.models import MetadataProviderCache
from app.services.metadata_aggregator import _lookup_provider, merge_empty_fields, score_record


def wait_for_enrichment(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/metadata/enrichment/jobs/{job_id}").json()
        if job["status"] in ("success", "partial", "failed", "stopped"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"补全任务 {job_id} 未及时结束")


def test_cache_first_merge_logs_and_missing_csv(client, media_root):
    (media_root / "SSIS-001 cache.mp4").write_bytes(b"fake")
    source = client.post("/api/v1/sources", json={
        "name": "Enrichment cache",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    }).json()
    scan = client.post(f"/api/v1/sources/{source['id']}/scans").json()
    from tests.test_api import wait_for_scan
    assert wait_for_scan(client, scan["id"])["status"] == "success"

    missing = client.get("/api/v1/metadata/missing.csv")
    assert missing.status_code == 200
    assert "SSIS-001" in missing.text

    with SessionLocal() as db:
        db.add(MetadataProviderCache(
            identifier="SSIS-001",
            provider="manual_csv",
            payload={
                "identifier": "SSIS-001",
                "title": "Cached title",
                "actors": ["Actor A"],
                "studio": "Cached Studio",
                "series": None,
                "release_date": None,
                "cover_url": None,
                "source": "manual_csv",
                "confidence": 1.0,
                "status": "complete",
                "error_message": None,
            },
            confidence=0.8,
            status="hit",
            fetched_at=datetime.now(timezone.utc),
        ))
        db.commit()

    created = client.post("/api/v1/metadata/enrichment/jobs", json={
        "scope": "selected",
        "identifiers": ["ssis001"],
        "providers": ["manual_csv"],
    })
    assert created.status_code == 202
    completed = wait_for_enrichment(client, created.json()["id"])
    assert completed["status"] == "success"
    assert completed["completed_count"] == 1

    detail = client.get("/api/v1/metadata/SSIS-001").json()
    assert detail["title"] == "Cached title"
    logs = client.get(f"/api/v1/metadata/enrichment/jobs/{completed['id']}/logs").json()
    assert logs["items"][0]["status"] == "cache_hit"
    assert logs["items"][0]["provider"] == "manual_csv"


def test_disabled_providers_never_fetch_and_are_logged(client):
    created = client.post("/api/v1/metadata/enrichment/jobs", json={
        "scope": "selected",
        "identifiers": ["IPZZ-123"],
        "providers": ["javbus", "jav321", "dmm", "missav", "theporndb"],
    })
    completed = wait_for_enrichment(client, created.json()["id"])
    assert completed["status"] == "partial"
    assert completed["failed_count"] == 1
    logs = client.get(f"/api/v1/metadata/enrichment/jobs/{completed['id']}/logs").json()["items"]
    assert {item["provider"] for item in logs} == {"javbus", "jav321", "dmm", "missav", "theporndb"}
    assert all(item["status"] == "disabled" for item in logs)


def test_enrichment_job_can_be_stopped(client, monkeypatch):
    original = LocalDBProvider.lookup

    def slow_lookup(self, identifier):
        time.sleep(0.03)
        return original(self, identifier)

    monkeypatch.setattr(LocalDBProvider, "lookup", slow_lookup)
    identifiers = [f"TEST-{number:03}" for number in range(100, 140)]
    created = client.post("/api/v1/metadata/enrichment/jobs", json={
        "scope": "selected",
        "identifiers": identifiers,
        "providers": ["local_db"],
    }).json()
    stopped = client.post(f"/api/v1/metadata/enrichment/jobs/{created['id']}/stop")
    assert stopped.status_code == 202
    completed = wait_for_enrichment(client, created["id"])
    assert completed["status"] == "stopped"
    assert completed["processed_count"] < completed["total_count"]


def test_registry_rejects_network_provider():
    class NetworkProvider:
        provider_name = "network-test"
        is_network_provider = True

    with pytest.raises(RuntimeError, match="network-test"):
        validate_provider_registry((NetworkProvider,))


def test_provider_timeout_and_retry_are_isolated():
    class SlowProvider:
        provider_name = "slow"
        priority = 1
        timeout_seconds = 0.01
        max_retries = 0

        def lookup(self, identifier):
            time.sleep(0.05)
            return MetadataRecord(identifier=identifier, title="Too late")

    result, logs = _lookup_provider(SlowProvider(), "SSIS-001")
    assert result is None
    assert logs[0][0] == "timeout"

    class RetryProvider:
        provider_name = "retry"
        priority = 1
        timeout_seconds = 1
        max_retries = 1

        def __init__(self):
            self.calls = 0

        def lookup(self, identifier):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary")
            return MetadataRecord(identifier=identifier, title="Recovered", confidence=1.0)

    result, logs = _lookup_provider(RetryProvider(), "SSIS-001")
    assert result.title == "Recovered"
    assert [item[0] for item in logs] == ["error", "hit"]


def test_scoring_and_merge_only_fill_empty_fields():
    base = MetadataRecord(identifier="SSIS-001", title="Keep title", actors=[], source="local_db")
    incoming = MetadataRecord(
        identifier="SSIS-001",
        title="Do not overwrite",
        plot="This is plot",
        actors=["Actor A"],
        studio="Studio A",
        source="manual_csv",
        confidence=1.0,
    )
    merged, changed = merge_empty_fields(base, incoming)
    assert changed is True
    assert merged.title == "Keep title"
    assert merged.plot == "This is plot"
    assert merged.actors == ["Actor A"]
    assert merged.studio == "Studio A"
    assert score_record(merged) >= 0.70


def test_locked_title_never_accepts_plot_or_title_replacement():
    base = MetadataRecord(
        identifier="SSIS-001",
        title="Manual title",
        plot=None,
        title_locked=True,
        source="local_db",
    )
    incoming = MetadataRecord(
        identifier="SSIS-001",
        title="Wrong provider title",
        plot="Provider plot",
        source="local_nfo",
        confidence=1.0,
    )
    merged, changed = merge_empty_fields(base, incoming)
    assert changed is True
    assert merged.title == "Manual title"
    assert merged.plot == "Provider plot"


def test_reference_metadata_and_local_nfo_providers_work_together(client, tmp_path):
    reference_root = tmp_path / "reference"
    target_dir = reference_root / "骑兵" / "小鸠麦" / "ABW-249"
    target_dir.mkdir(parents=True)
    (target_dir / "ABW-249.strm").write_text("/virtual/path", encoding="utf-8")
    (target_dir / "ABW-249.nfo").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>绝对不能把简介写进标题</title>
  <plot>这是一段简介，只能进 plot，不能进 title。</plot>
  <studio>Prestige</studio>
  <set>骑兵精选</set>
  <premiered>2025-05-20</premiered>
  <actor><name>小鸠麦</name></actor>
</movie>
""",
        encoding="utf-8",
    )

    source = client.post("/api/v1/reference-sources", json={
        "name": "Reference Metadata",
        "provider_type": "local_strm",
        "root_path": str(reference_root),
    }).json()
    scanned = client.post(f"/api/v1/reference-sources/{source['id']}/scan")
    assert scanned.status_code == 200, scanned.text

    created = client.post("/api/v1/metadata/enrichment/jobs", json={
        "scope": "selected",
        "identifiers": ["abw249"],
        "providers": ["reference_metadata", "local_nfo"],
    })
    assert created.status_code == 202, created.text
    completed = wait_for_enrichment(client, created.json()["id"])
    assert completed["status"] == "success"

    detail = client.get("/api/v1/metadata/ABW-249")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["title"] == "绝对不能把简介写进标题"
    assert body["plot"] == "这是一段简介，只能进 plot，不能进 title。"
    assert body["actors"] == ["小鸠麦"]
    assert body["studio"] == "Prestige"
    assert body["series"] == "骑兵精选"
    assert body["source"] == "aggregator"

    logs = client.get(f"/api/v1/metadata/enrichment/jobs/{completed['id']}/logs").json()["items"]
    assert {item["provider"] for item in logs} == {"reference_metadata", "local_nfo"}


def test_reference_harvest_api_creates_job_from_reference_scope(client, tmp_path):
    reference_root = tmp_path / "reference"
    target_dir = reference_root / "骑兵" / "演员A" / "SSIS-001"
    target_dir.mkdir(parents=True)
    (target_dir / "SSIS-001.strm").write_text("/virtual/path", encoding="utf-8")
    (target_dir / "SSIS-001.nfo").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>Harvest Title</title>
  <plot>Harvest Plot</plot>
  <actor><name>演员A</name></actor>
</movie>
""",
        encoding="utf-8",
    )
    other_dir = reference_root / "无码" / "演员B" / "IPZZ-123"
    other_dir.mkdir(parents=True)
    (other_dir / "IPZZ-123.strm").write_text("/virtual/path", encoding="utf-8")

    source = client.post("/api/v1/reference-sources", json={
        "name": "Harvest API",
        "provider_type": "local_strm",
        "root_path": str(reference_root),
    }).json()
    assert client.post(f"/api/v1/reference-sources/{source['id']}/scan").status_code == 200

    created = client.post("/api/v1/metadata/harvest/reference", json={
        "reference_source_id": source["id"],
        "reference_scope_prefix": "骑兵/",
        "providers": ["reference_metadata", "local_nfo"],
    })
    assert created.status_code == 202, created.text
    job = wait_for_enrichment(client, created.json()["id"])
    assert job["status"] == "success"
    assert job["total_count"] == 1
    assert job["scope"] == f"reference:{source['id']}:骑兵/"

    detail = client.get("/api/v1/metadata/SSIS-001").json()
    assert detail["title"] == "Harvest Title"
    assert detail["plot"] == "Harvest Plot"

    missing = client.get("/api/v1/metadata/IPZZ-123")
    assert missing.status_code == 404
