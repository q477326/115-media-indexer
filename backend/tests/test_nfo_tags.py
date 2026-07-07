from app.core.config import settings


def test_nfo_tag_search_and_incremental_add(client, tmp_path, monkeypatch):
    root = tmp_path / "local-media"
    folder = root / "小姐姐" / "骑兵" / "演员A" / "CAWD-953"
    folder.mkdir(parents=True)
    target = folder / "CAWD-953.nfo"
    target.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>美腿秘书的诱惑</title>
  <originaltitle>CAWD-953 original title</originaltitle>
  <tag>连裤袜</tag>
  <genre>腿控</genre>
</movie>
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "local_media_container_root", str(root))
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)

    response = client.get(
        "/api/v1/nfo-tags/search",
        params={"folder_path": str(root / "小姐姐" / "骑兵"), "search_type": "title", "q": "美腿"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["identifier"] == "CAWD-953"
    assert body["items"][0]["raw_tags"] == ["连裤袜", "腿控"]

    response = client.get(
        "/api/v1/nfo-tags/search",
        params={"folder_path": str(root / "小姐姐" / "骑兵"), "search_type": "raw_tag", "q": "连裤袜"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1

    add = client.post(
        "/api/v1/nfo-tags/batch-add",
        json={"file_paths": [str(target)], "tag_name": "美腿"},
    )
    assert add.status_code == 200
    result = add.json()
    assert result["matched_count"] == 1
    assert result["added_count"] == 1
    assert result["skipped_count"] == 0

    text = target.read_text(encoding="utf-8")
    assert "<tag>美腿</tag>" in text

    add_again = client.post(
        "/api/v1/nfo-tags/batch-add",
        json={"file_paths": [str(target)], "tag_name": "美腿"},
    )
    assert add_again.status_code == 200
    result = add_again.json()
    assert result["matched_count"] == 1
    assert result["added_count"] == 0
    assert result["skipped_count"] == 1
    assert target.read_text(encoding="utf-8").count("<tag>美腿</tag>") == 1
