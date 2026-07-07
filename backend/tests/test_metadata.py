from tests.test_api import wait_for_scan


def test_csv_import_search_detail_and_file_association(client, media_root):
    (media_root / "SSIS-001 sample.mp4").write_bytes(b"fake")
    source = client.post("/api/v1/sources", json={
        "name": "Metadata library",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    }).json()
    scan = client.post(f"/api/v1/sources/{source['id']}/scans").json()
    assert wait_for_scan(client, scan["id"])["status"] == "success"

    csv_content = (
        "identifier,title,actors,studio,series,release_date,cover_url\n"
        'ssis001,Manual title,"Actor A|Actor B",Studio One,Series One,2025-01-02,/covers/ssis001.jpg\n'
        "ipzz_123,Second title,Actor C,Studio Two,,,\n"
    )
    imported = client.post(
        "/api/v1/metadata/import/csv",
        content=csv_content.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json() == {"created": 2, "updated": 0, "skipped": 0, "errors": []}

    actor_results = client.get("/api/v1/metadata", params={"actor": "Actor B"}).json()
    assert actor_results["total"] == 1
    assert actor_results["items"][0]["identifier"] == "SSIS-001"

    studio_results = client.get("/api/v1/metadata", params={"studio": "Studio Two"}).json()
    assert studio_results["total"] == 1
    assert studio_results["items"][0]["identifier"] == "IPZZ-123"

    detail = client.get("/api/v1/metadata/ssis001")
    assert detail.status_code == 200
    assert detail.json()["actors"] == ["Actor A", "Actor B"]
    assert detail.json()["files"][0]["filename"] == "SSIS-001 sample.mp4"

    files = client.get("/api/v1/files", params={"q": "SSIS-001"}).json()
    assert files["items"][0]["metadata"]["title"] == "Manual title"
    assert files["items"][0]["metadata"]["studio"] == "Studio One"


def test_csv_upsert_validation_and_mock(client):
    invalid = client.post(
        "/api/v1/metadata/import/csv",
        content=b"identifier,title\nSSIS-001,title\n",
        headers={"Content-Type": "text/csv"},
    )
    assert invalid.status_code == 400
    assert "CSV" in invalid.json()["detail"]

    mock = client.post("/api/v1/metadata/cawd456/lookup")
    assert mock.status_code == 200
    assert mock.json()["identifier"] == "CAWD-456"
    assert mock.json()["source"] == "mock"
    assert mock.json()["confidence"] == 0.1

    csv_content = (
        "identifier,title,actors,studio,series,release_date,cover_url\n"
        "cawd456,CSV override,Actor D,Studio D,,,,\n"
    )
    updated = client.post("/api/v1/metadata/import/csv", content=csv_content.encode())
    assert updated.status_code == 200
    assert updated.json()["updated"] == 1
    assert client.get("/api/v1/metadata/CAWD-456").json()["source"] == "manual_csv"
