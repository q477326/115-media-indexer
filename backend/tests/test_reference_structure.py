def test_reference_strm_scan_uses_relative_paths_and_keeps_media_files_empty(client, tmp_path):
    root = tmp_path / "小姐姐"
    target_dir = root / "骑兵" / "阿由叶亚美" / "PRED-107"
    target_dir.mkdir(parents=True)
    strm_file = target_dir / "PRED-107.strm"
    strm_file.write_text("/some/virtual/media/path", encoding="utf-8")
    (target_dir / "PRED-107.jpg").write_bytes(b"not indexed")

    created = client.post("/api/v1/reference-sources", json={
        "name": "STRM Reference",
        "provider_type": "local_strm",
        "root_path": str(root),
    })
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    scanned = client.post(f"/api/v1/reference-sources/{source_id}/scan")
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["scanned_count"] == 1
    assert scanned.json()["identified_count"] == 1

    items = client.get("/api/v1/reference-items", params={"q": "PRED-107"}).json()
    assert items["total"] == 1
    item = items["items"][0]
    assert item["identifier"] == "PRED-107"
    assert item["reference_path"] == "骑兵/阿由叶亚美/PRED-107/PRED-107.strm"
    assert item["reference_dir"] == "骑兵/阿由叶亚美/PRED-107"
    assert item["filename"] == "PRED-107.strm"
    assert item["ext"] == "strm"
    assert item["status"] == "identified"
    assert "/mnt/reference-strm" not in item["reference_path"]
    assert str(root) not in item["reference_path"]

    files = client.get("/api/v1/files").json()
    assert files["total"] == 0


def test_reference_strm_scan_marks_duplicate_identifiers(client, tmp_path):
    root = tmp_path / "reference"
    (root / "A" / "PRED-107").mkdir(parents=True)
    (root / "B" / "PRED-107").mkdir(parents=True)
    (root / "A" / "PRED-107" / "PRED-107.strm").write_text("", encoding="utf-8")
    (root / "B" / "PRED-107" / "98T@PRED-107.strm").write_text("", encoding="utf-8")

    source = client.post("/api/v1/reference-sources", json={
        "name": "Duplicate Reference",
        "provider_type": "local_strm",
        "root_path": str(root),
    }).json()
    result = client.post(f"/api/v1/reference-sources/{source['id']}/scan")
    assert result.status_code == 200, result.text
    assert result.json()["duplicate_count"] == 2

    duplicates = client.get("/api/v1/reference-items", params={"status": "duplicate"}).json()
    assert duplicates["total"] == 2
    assert {item["identifier"] for item in duplicates["items"]} == {"PRED-107"}


def test_reference_source_rejects_missing_root(client, tmp_path):
    response = client.post("/api/v1/reference-sources", json={
        "name": "Missing",
        "provider_type": "local_strm",
        "root_path": str(tmp_path / "missing"),
    })
    assert response.status_code == 400


def test_reference_strm_scan_identifies_numeric_prefix_kibin_codes(client, tmp_path):
    root = tmp_path / "reference"
    (root / "骑兵" / "なみ26歳コーヒーショップ勤務" / "348NTR-102").mkdir(parents=True)
    (root / "骑兵" / "なみ26歳コーヒーショップ勤務" / "348NTR-102" / "348NTR-102.strm").write_text("", encoding="utf-8")
    (root / "FC2" / "[RED]" / "FC2-1650265").mkdir(parents=True)
    (root / "FC2" / "[RED]" / "FC2-1650265" / "FC2-1650265.strm").write_text("", encoding="utf-8")

    source = client.post("/api/v1/reference-sources", json={
        "name": "Numeric Prefix",
        "provider_type": "local_strm",
        "root_path": str(root),
    }).json()
    result = client.post(f"/api/v1/reference-sources/{source['id']}/scan")
    assert result.status_code == 200, result.text
    assert result.json()["identified_count"] == 1
    assert result.json()["unidentified_count"] == 1

    identified = client.get("/api/v1/reference-items", params={"q": "348NTR"}).json()
    assert identified["total"] == 1
    assert identified["items"][0]["identifier"] == "348NTR-102"
    assert identified["items"][0]["reference_dir"] == "骑兵/なみ26歳コーヒーショップ勤務/348NTR-102"

    fc2 = client.get("/api/v1/reference-items", params={"q": "FC2-1650265"}).json()
    assert fc2["total"] == 1
    assert fc2["items"][0]["identifier"] is None
    assert fc2["items"][0]["status"] == "unidentified"
