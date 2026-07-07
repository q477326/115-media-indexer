import time

from app.core.database import SessionLocal
from app.models import MediaFile, MediaMetadata, ReferenceItem, ReferenceSource, Source


def wait_for_organizer(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/organizer/jobs/{job_id}").json()
        if job["status"] in ("success", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"整理计划 {job_id} 未及时完成")


def seed_files():
    with SessionLocal() as db:
        source = Source(name="Organizer", provider_type="local_fs", root_path="/mnt/demo")
        db.add(source)
        db.flush()
        db.add_all([
            MediaFile(source_id=source.id, provider="local_fs", local_path="/a/SSIS-001.mp4", filename="SSIS-001.mp4", path="/a/SSIS-001.mp4", size=1, identifier="SSIS-001", status="identified"),
            MediaFile(source_id=source.id, provider="local_fs", local_path="/a/IPZZ-123.mkv", filename="IPZZ-123.mkv", path="/a/IPZZ-123.mkv", size=2, identifier="IPZZ-123", status="identified"),
            MediaFile(source_id=source.id, provider="local_fs", local_path="/a/movie.mp4", filename="movie.mp4", path="/a/movie.mp4", size=3, identifier=None, status="unidentified"),
            MediaFile(source_id=source.id, provider="local_fs", local_path="/a/CAWD-456.mp4", filename="CAWD-456.mp4", path="/a/CAWD-456.mp4", size=4, identifier="CAWD-456", status="identified"),
            MediaFile(source_id=source.id, provider="local_fs", local_path="/offline/MIDV-888.mp4", filename="MIDV-888.mp4", path="/offline/MIDV-888.mp4", size=5, identifier="MIDV-888", status="missing"),
            MediaFile(source_id=source.id, provider="local_fs", local_path="/one/DUP-100.mp4", filename="DUP-100.mp4", path="/one/DUP-100.mp4", size=6, identifier="DUP-100", status="identified"),
            MediaFile(source_id=source.id, provider="local_fs", local_path="/two/DUP-100.mp4", filename="DUP-100.mp4", path="/two/DUP-100.mp4", size=7, identifier="DUP-100", status="identified"),
        ])
        db.add_all([
            MediaMetadata(identifier="SSIS-001", title="Title", actors=["Actor A", "Actor B"], studio="Good Studio", series="Series A", source="manual_csv", confidence=1.0, status="complete"),
            MediaMetadata(identifier="CAWD-456", title="Bad path", actors=["Actor C"], studio="Bad:Studio", source="manual_csv", confidence=1.0, status="complete"),
        ])
        db.commit()


def test_organizer_dry_run_statuses_and_csv(client):
    seed_files()
    response = client.post("/api/v1/organizer/jobs", json={
        "rule_template": "{studio}/{identifier}/{filename}",
        "scope": "all",
    })
    assert response.status_code == 202, response.text
    job = wait_for_organizer(client, response.json()["id"])
    assert job["status"] == "success"
    assert job["total_count"] == 7
    assert job["status_counts"]["ready"] == 1
    assert job["status_counts"]["missing_metadata"] == 3
    assert job["status_counts"]["unidentified"] == 1
    assert job["status_counts"]["invalid_path"] == 1
    assert job["status_counts"]["skipped"] == 1

    ready = client.get(f"/api/v1/organizer/jobs/{job['id']}/items", params={"status": "ready"}).json()
    assert ready["items"][0]["target_path"] == "Good Studio/SSIS-001/SSIS-001.mp4"
    assert ready["items"][0]["source_path"] == "/a/SSIS-001.mp4"

    exported = client.get(f"/api/v1/organizer/jobs/{job['id']}/export.csv")
    assert exported.status_code == 200
    assert "source_path,target_path,identifier,rule_template,status,error_message" in exported.text
    assert "Good Studio/SSIS-001/SSIS-001.mp4" in exported.text


def test_organizer_conflicts_templates_and_no_execute_endpoint(client):
    seed_files()
    response = client.post("/api/v1/organizer/jobs", json={
        "rule_template": "{prefix}/{identifier}/{filename}",
        "scope": "identified",
    })
    job = wait_for_organizer(client, response.json()["id"])
    assert job["status_counts"]["conflict"] == 2
    conflicts = client.get(
        f"/api/v1/organizer/jobs/{job['id']}/items", params={"status": "conflict"}
    ).json()
    assert conflicts["total"] == 2
    assert {item["target_path"] for item in conflicts["items"]} == {"DUP/DUP-100/DUP-100.mp4"}

    invalid = client.post("/api/v1/organizer/jobs", json={
        "rule_template": "{unknown}/{filename}",
        "scope": "all",
    })
    assert invalid.status_code == 400
    assert client.post(f"/api/v1/organizer/jobs/{job['id']}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "move",
        "confirm": True,
    }).status_code == 409


def test_reference_based_organizer_dry_run_only_uses_kibin_reference_scope(client):
    with SessionLocal() as db:
        media_source = Source(name="CloudDrive2", provider_type="local_fs", root_path="/mnt/clouddrive")
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add_all([media_source, reference_source])
        db.flush()
        db.add_all([
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/98T@PRED-107.mp4", filename="98T@PRED-107.mp4", path="/raw/98T@PRED-107.mp4", size=1, identifier="PRED-107", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/348NTR-102.mp4", filename="348NTR-102.mp4", path="/raw/348NTR-102.mp4", size=1, identifier="348NTR-102", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/FC2-1650265.mp4", filename="FC2-1650265.mp4", path="/raw/FC2-1650265.mp4", size=1, identifier=None, status="unidentified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/NOREF-001.mp4", filename="NOREF-001.mp4", path="/raw/NOREF-001.mp4", size=1, identifier="NOREF-001", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/offline/PRED-108.mp4", filename="PRED-108.mp4", path="/offline/PRED-108.mp4", size=1, identifier="PRED-108", status="missing"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/dup/a.mp4", filename="a.mp4", path="/dup/a.mp4", size=1, identifier="DUP-100", status="identified"),
        ])
        db.add_all([
            ReferenceItem(source_id=reference_source.id, identifier="PRED-107", reference_path="骑兵/阿由叶亚美/PRED-107/PRED-107.strm", reference_dir="骑兵/阿由叶亚美/PRED-107", filename="PRED-107.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="348NTR-102", reference_path="骑兵/なみ26歳コーヒーショップ勤務/348NTR-102/348NTR-102.strm", reference_dir="骑兵/なみ26歳コーヒーショップ勤務/348NTR-102", filename="348NTR-102.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="FC2-1650265", reference_path="FC2/[RED]/FC2-1650265/FC2-1650265.strm", reference_dir="FC2/[RED]/FC2-1650265", filename="FC2-1650265.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="DUP-100", reference_path="骑兵/A/DUP-100/DUP-100-cd1.strm", reference_dir="骑兵/A/DUP-100", filename="DUP-100-cd1.strm", ext="strm", size=1, status="duplicate"),
            ReferenceItem(source_id=reference_source.id, identifier="DUP-100", reference_path="骑兵/A/DUP-100/DUP-100-cd2.strm", reference_dir="骑兵/A/DUP-100", filename="DUP-100-cd2.strm", ext="strm", size=1, status="duplicate"),
        ])
        db.commit()
        media_source_id = media_source.id
        reference_source_id = reference_source.id

    response = client.post("/api/v1/organizer/jobs", json={
        "mode": "reference_based",
        "source_id": media_source_id,
        "reference_source_id": reference_source_id,
        "reference_scope_prefix": "骑兵/",
        "output_root": "/vol02/1000-1-2846ebc3/吴猛/小姐姐/骑兵",
        "filename_strategy": "preserve_source_filename",
    })
    assert response.status_code == 202, response.text
    job = wait_for_organizer(client, response.json()["id"])
    assert job["status"] == "success"
    assert job["mode"] == "reference_based"
    assert job["total_count"] == 6
    assert job["status_counts"]["ready"] == 2
    assert job["status_counts"]["unidentified"] == 1
    assert job["status_counts"]["missing_reference"] == 1
    assert job["status_counts"]["skipped"] == 1
    assert job["status_counts"]["duplicate_reference"] == 1

    ready = client.get(f"/api/v1/organizer/jobs/{job['id']}/items", params={"status": "ready"}).json()
    targets = {item["identifier"]: item["target_path"] for item in ready["items"]}
    assert targets["PRED-107"] == "/vol02/1000-1-2846ebc3/吴猛/小姐姐/骑兵/阿由叶亚美/PRED-107/98T@PRED-107.mp4"
    assert targets["348NTR-102"] == "/vol02/1000-1-2846ebc3/吴猛/小姐姐/骑兵/なみ26歳コーヒーショップ勤務/348NTR-102/348NTR-102.mp4"
    assert all("/mnt/reference-strm" not in item["target_path"] for item in ready["items"])
    assert all("/vol1/1000/media/小姐姐" not in item["target_path"] for item in ready["items"])
    assert all("骑兵/骑兵" not in item["target_path"] for item in ready["items"])

    missing = client.get(f"/api/v1/organizer/jobs/{job['id']}/items", params={"status": "missing_reference"}).json()
    assert missing["items"][0]["identifier"] == "NOREF-001"
    assert client.post(f"/api/v1/organizer/jobs/{job['id']}/execute", json={
        "status_filter": "ready",
        "limit": 1,
        "mode": "move",
        "confirm": True,
    }).status_code == 409


def test_reference_based_match_reference_filename_with_source_suffix(client):
    with SessionLocal() as db:
        media_source = Source(name="CloudDrive2", provider_type="local_fs", root_path="/mnt/clouddrive")
        reference_source = ReferenceSource(name="STRM", provider_type="local_strm", root_path="/mnt/reference-strm")
        db.add_all([media_source, reference_source])
        db.flush()
        db.add_all([
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/CAWD-956-U.mp4", filename="CAWD-956-U.mp4", path="/raw/CAWD-956-U.mp4", size=1, identifier="CAWD-956", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/4k2.me@cawd-985.mp4", filename="4k2.me@cawd-985.mp4", path="/raw/4k2.me@cawd-985.mp4", size=1, identifier="CAWD-985", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/CAWD-213-4K.mp4", filename="CAWD-213-4K.mp4", path="/raw/CAWD-213-4K.mp4", size=1, identifier="CAWD-213", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/ABW-348-C.mp4", filename="ABW-348-C.mp4", path="/raw/ABW-348-C.mp4", size=1, identifier="ABW-348", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/MIFD-097-C.mp4", filename="MIFD-097-C.mp4", path="/raw/MIFD-097-C.mp4", size=1, identifier="MIFD-097", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/www.98T.la@ABW-121@BVPP1XdfBVPP4X(STD)_apo8_iris2_watermusk.mp4", filename="www.98T.la@ABW-121@BVPP1XdfBVPP4X(STD)_apo8_iris2_watermusk.mp4", path="/raw/www.98T.la@ABW-121@BVPP1XdfBVPP4X(STD)_apo8_iris2_watermusk.mp4", size=1, identifier="ABW-121", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/hhd800.com@ABW-249.mp4", filename="hhd800.com@ABW-249.mp4", path="/raw/hhd800.com@ABW-249.mp4", size=1, identifier="ABW-249", status="identified"),
            MediaFile(source_id=media_source.id, provider="local_fs", local_path="/raw/STARS-272-cd1.mp4", filename="STARS-272-cd1.mp4", path="/raw/STARS-272-cd1.mp4", size=1, identifier="STARS-272", status="identified"),
        ])
        db.add_all([
            ReferenceItem(source_id=reference_source.id, identifier="CAWD-956", reference_path="kibin/A/CAWD-956/CAWD-956.strm", reference_dir="kibin/A/CAWD-956", filename="CAWD-956.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="CAWD-985", reference_path="kibin/A/CAWD-985/CAWD-985-C.strm", reference_dir="kibin/A/CAWD-985", filename="CAWD-985-C.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="CAWD-213", reference_path="kibin/A/CAWD-213/CAWD-213.strm", reference_dir="kibin/A/CAWD-213", filename="CAWD-213.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="ABW-348", reference_path="kibin/A/ABW-348/ABW-348-C.strm", reference_dir="kibin/A/ABW-348", filename="ABW-348-C.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="MIFD-097", reference_path="kibin/A/MIFD-097/MIFD-097-C.strm", reference_dir="kibin/A/MIFD-097", filename="MIFD-097-C.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="ABW-121", reference_path="kibin/A/ABW-121/ABW-121.strm", reference_dir="kibin/A/ABW-121", filename="ABW-121.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="ABW-249", reference_path="kibin/A/ABW-249/ABW-249.strm", reference_dir="kibin/A/ABW-249", filename="ABW-249.strm", ext="strm", size=1, status="identified"),
            ReferenceItem(source_id=reference_source.id, identifier="STARS-272", reference_path="kibin/A/STARS-272/STARS-272-cd1.strm", reference_dir="kibin/A/STARS-272", filename="STARS-272-cd1.strm", ext="strm", size=1, status="identified"),
        ])
        db.commit()
        media_source_id = media_source.id
        reference_source_id = reference_source.id

    response = client.post("/api/v1/organizer/jobs", json={
        "mode": "reference_based",
        "source_id": media_source_id,
        "reference_source_id": reference_source_id,
        "reference_scope_prefix": "kibin/",
        "output_root": "/output/kibin",
        "filename_strategy": "match_reference_filename_with_source_suffix",
    })
    assert response.status_code == 202, response.text
    job = wait_for_organizer(client, response.json()["id"])
    assert job["status"] == "success"
    ready = client.get(
        f"/api/v1/organizer/jobs/{job['id']}/items",
        params={"status": "ready", "page_size": 20},
    ).json()
    expected_filenames = {
        "CAWD-956": "CAWD-956-U.mp4",
        "CAWD-985": "CAWD-985.mp4",
        "CAWD-213": "CAWD-213-4K.mp4",
        "ABW-348": "ABW-348-C.mp4",
        "MIFD-097": "MIFD-097-C.mp4",
        "ABW-121": "ABW-121.mp4",
        "ABW-249": "ABW-249.mp4",
        "STARS-272": "STARS-272-cd1.mp4",
    }
    assert ready["total"] == len(expected_filenames)
    for item in ready["items"]:
        assert item["target_path"].rsplit("/", 1)[-1] == expected_filenames[item["identifier"]]
