from pathlib import Path

from app.core.config import settings
from app.services import download_ingest


def test_one_click_ingest_blocked_by_default_flags(client, media_root, monkeypatch):
    source_root = media_root / "115open" / "云下载"
    output_root = media_root / "115open" / "原始库" / "不正常视频" / "qb" / "骑兵" / "洗版"
    source_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (source_root / "hhd800.com@ABW-249.mp4").write_bytes(b"video" * 1024 * 200)

    monkeypatch.setattr(settings, "clouddrive_container_root", str(media_root).replace("\\", "/"))
    monkeypatch.setattr(settings, "clouddrive_host_root", str(media_root).replace("\\", "/"))
    monkeypatch.setattr(download_ingest, "MIN_VIDEO_MB", 0)

    response = client.post("/api/v1/one-click-ingest", json={
        "source_root": str(source_root).replace("\\", "/"),
        "output_root": str(output_root).replace("\\", "/"),
    })
    assert response.status_code == 409
    assert "ENABLE_REAL_MOVE" in response.json()["detail"]


def test_one_click_ingest_success(client, media_root, monkeypatch):
    source_root = media_root / "115open" / "云下载"
    nested = source_root / "sub"
    output_root = media_root / "115open" / "原始库" / "不正常视频" / "qb" / "骑兵" / "洗版"
    nested.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    video = nested / "hhd800.com@ABW-249.mp4"
    video.write_bytes(b"video" * 1024 * 200)
    junk = nested / "poster.jpg"
    junk.write_bytes(b"jpg")

    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_real_move", True)
    monkeypatch.setattr(settings, "clouddrive_container_root", str(media_root).replace("\\", "/"))
    monkeypatch.setattr(settings, "clouddrive_host_root", str(media_root).replace("\\", "/"))
    monkeypatch.setattr(settings, "cms_sync_url", "")
    monkeypatch.setattr(download_ingest, "MIN_VIDEO_MB", 0)

    response = client.post("/api/v1/one-click-ingest", json={
        "source_root": str(source_root).replace("\\", "/"),
        "output_root": str(output_root).replace("\\", "/"),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preview"]["rename_count"] == 1
    assert body["preview"]["delete_count"] == 1
    assert body["organize"]["rename_count"] == 1
    assert body["organize"]["delete_count"] == 1
    assert body["move"]["moved_count"] == 1
    assert body["move"]["failed_count"] == 0
    assert body["cms_sync"] is None

    assert not video.exists()
    assert not junk.exists()
    assert (output_root / "ABW-249.mp4").exists()
