from app.core.config import settings


def test_western_poster_dry_run_and_execute(client, tmp_path, monkeypatch):
    root = tmp_path / "local-media" / "欧美"
    folder = root / "Movie A"
    folder.mkdir(parents=True)
    thumb = folder / "thumb.jpg"
    thumb.write_bytes(b"thumb-data")
    (folder / "poster.png").write_bytes(b"old-png")

    monkeypatch.setattr(settings, "local_media_container_root", str((tmp_path / "local-media").resolve()))

    dry_run = client.post(
        "/api/v1/western-posters/run",
        json={
            "root": str(root),
            "state_file": str(tmp_path / "western-state.json"),
            "process_all": False,
            "dry_run": True,
        },
    )
    assert dry_run.status_code == 200
    payload = dry_run.json()
    assert payload["dry_run"] == 1
    assert payload["processed"] == 0
    assert payload["touched"] == [str(folder.resolve())]
    assert not (folder / "poster.jpg").exists()

    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)

    execute = client.post(
        "/api/v1/western-posters/run",
        json={
            "root": str(root),
            "state_file": str(tmp_path / "western-state.json"),
            "process_all": False,
            "dry_run": False,
        },
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["processed"] == 1
    assert payload["dry_run"] == 0
    assert (folder / "poster.jpg").read_bytes() == b"thumb-data"
    assert (folder / "fanart.jpg").read_bytes() == b"thumb-data"
    assert not (folder / "poster.png").exists()
    assert (folder / "poster.png.bak").exists()
