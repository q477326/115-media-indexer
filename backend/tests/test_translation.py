from pathlib import Path

from app.core.config import settings


def _run_translation_inline(job_id, file_path=None):
    from app.core.database import SessionLocal
    from app.services.nfo_translation import run_translation_file_job, run_translation_job

    with SessionLocal() as db:
        if file_path:
            run_translation_file_job(db, job_id, file_path, None)
        else:
            run_translation_job(db, job_id, None)


def patch_translation_task_manager_inline(monkeypatch):
    from app.services import translation_task_manager

    monkeypatch.setattr(translation_task_manager.translation_task_manager, "start", _run_translation_inline)
    monkeypatch.setattr(translation_task_manager.translation_task_manager, "stop", lambda job_id: False)


def wait_for_translation_job(client, job_id, timeout=5):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/translation/jobs/{job_id}").json()
        if job["status"] in {"success", "partial", "failed", "stopped"}:
            return job
        time.sleep(0.1)
    raise AssertionError("translation job timeout")


def test_translation_watch_folder_and_analyze_job(client, tmp_path, monkeypatch):
    patch_translation_task_manager_inline(monkeypatch)
    folder = tmp_path / "jav"
    folder.mkdir(parents=True)
    (folder / "ABW-249.nfo").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>坏中文标题</title>
  <originaltitle>ABW-249 ほげほげ</originaltitle>
  <plot>坏中文简介</plot>
  <originalplot>元のあらすじです。</originalplot>
</movie>
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "allowed_translation_roots", (folder.parent.resolve(),))

    saved = client.post(
        "/api/v1/translation/watch-folders",
        json={
            "name": "JAV",
            "folder_path": str(folder),
            "prompt_template": "翻成简体中文",
            "enabled": True,
        },
    )
    assert saved.status_code == 201

    created = client.post(
        "/api/v1/translation/jobs",
        json={
            "watch_folder_id": saved.json()["id"],
            "mode": "analyze",
        },
    )
    assert created.status_code == 202
    job = wait_for_translation_job(client, created.json()["id"])
    assert job["status"] == "success"
    assert job["translated_count"] == 1

    items = client.get(f"/api/v1/translation/jobs/{job['id']}/items").json()["items"]
    assert items[0]["status"] == "candidate"
    assert items[0]["source_title_field"] == "originaltitle"
    assert items[0]["source_plot_field"] == "originalplot"


def test_translation_job_writes_nfo(client, tmp_path, monkeypatch):
    patch_translation_task_manager_inline(monkeypatch)
    folder = tmp_path / "western"
    folder.mkdir(parents=True)
    target = folder / "MOVIE-001.nfo"
    target.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>old title</title>
  <originaltitle>Original English Title</originaltitle>
  <plot>old plot</plot>
  <originalplot>Original English plot.</originalplot>
</movie>
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "allowed_translation_roots", (folder.parent.resolve(),))
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_ai_translation", True)
    monkeypatch.setattr(settings, "ai_translation_api_key", "test-key")

    from app.services import nfo_translation

    monkeypatch.setattr(
        nfo_translation,
        "translate_title_and_plot",
        lambda *args, **kwargs: {"title": "新标题", "plot": "新简介"},
    )

    created = client.post(
        "/api/v1/translation/jobs",
        json={
            "folder_path": str(folder),
            "prompt_template": "翻成简体中文",
            "mode": "translate",
        },
    )
    assert created.status_code == 202
    job = wait_for_translation_job(client, created.json()["id"])
    assert job["status"] == "success"
    assert job["translated_count"] == 1

    text = target.read_text(encoding="utf-8")
    assert "<title>新标题</title>" in text
    assert "<plot>新简介</plot>" in text
    assert not target.with_suffix(".nfo.bak").exists()


def test_translation_api_settings_and_runtime(client):
    saved = client.put(
        "/api/v1/translation/settings",
        json={
            "enabled": True,
            "api_key": "sk-test-12345678",
            "base_url": "https://4sapi.com/v1",
            "model_name": "grok-4.20-beta",
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["enabled"] is True
    assert body["has_api_key"] is True
    assert body["base_url"] == "https://4sapi.com/v1"
    assert body["model_name"] == "grok-4.20-beta"
    assert body["api_key_masked"]

    fetched = client.get("/api/v1/translation/settings")
    assert fetched.status_code == 200
    assert fetched.json()["model_name"] == "grok-4.20-beta"


def test_translation_connection_test_endpoint(client, monkeypatch):
    from app.api import router as api_router

    monkeypatch.setattr(
        api_router,
        "test_translation_connection",
        lambda **kwargs: {
            "ok": True,
            "provider_name": "openai-compatible",
            "base_url": kwargs["base_url"],
            "model_name": kwargs["model_name"],
            "message": "pong",
        },
    )
    response = client.post(
        "/api/v1/translation/settings/test",
        json={
            "enabled": True,
            "api_key": "sk-xxx",
            "base_url": "https://4sapi.com/v1",
            "model_name": "grok-4.20-beta",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["message"] == "pong"


def test_translation_items_global_endpoint(client, tmp_path, monkeypatch):
    patch_translation_task_manager_inline(monkeypatch)
    folder = tmp_path / "recent"
    folder.mkdir(parents=True)
    target = folder / "RECENT-001.nfo"
    target.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>old title</title>
  <originaltitle>Original English Title</originaltitle>
  <plot>old plot</plot>
  <originalplot>Original English plot.</originalplot>
</movie>
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "allowed_translation_roots", (folder.parent.resolve(),))
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_ai_translation", True)
    monkeypatch.setattr(settings, "ai_translation_api_key", "test-key")

    from app.services import nfo_translation

    monkeypatch.setattr(
        nfo_translation,
        "translate_title_and_plot",
        lambda *args, **kwargs: {"title": "Recent title", "plot": "Recent plot"},
    )

    created = client.post(
        "/api/v1/translation/jobs",
        json={"folder_path": str(folder), "prompt_template": "translate", "mode": "translate"},
    )
    assert created.status_code == 202
    wait_for_translation_job(client, created.json()["id"])

    response = client.get("/api/v1/translation/items?page=1&page_size=10")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(item["translated_title"] == "Recent title" for item in body["items"])


def test_translate_title_and_plot_retries_or_rejects_untranslated(monkeypatch):
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_ai_translation", True)
    monkeypatch.setattr(settings, "ai_translation_api_key", "test-key")

    from app.services import ai_translation

    responses = iter(
        [
            {"choices": [{"message": {"content": '{"title":"WAAA-002 僕を嫌うお義姉さんとバッタリ遭遇したのはソープランド。","plot":"え？ お義姉さん！！ 何故こんなところに？"}'}}]},
            {"choices": [{"message": {"content": '{"title":"WAAA-002 在浴场偶遇讨厌我的义姐","plot":"咦？义姐！你怎么会在这里？"}'}}]},
        ]
    )

    monkeypatch.setattr(ai_translation, "_chat_completion", lambda **kwargs: next(responses))

    class DummySettings:
        enabled = True
        api_key = "test-key"
        base_url = "https://example.com/v1"
        model_name = "demo-model"

    result = ai_translation.translate_title_and_plot(
        db=None,
        prompt_template="translate",
        source_title="WAAA-002 僕を嫌うお義姉さんとバッタリ遭遇したのはソープランド。",
        source_plot="え？ お義姉さん！！ 何故こんなところに？",
        current_title="WAAA-002 僕を嫌うお義姉さんとバッタリ遭遇したのはソープランド。",
        current_plot="え？ お義姉さん！！ 何故こんなところに？",
    )
    assert result["title"] == "WAAA-002 在浴场偶遇讨厌我的义姐"
    assert result["plot"] == "咦？义姐！你怎么会在这里？"


def test_translation_file_search_and_single_run(client, tmp_path, monkeypatch):
    patch_translation_task_manager_inline(monkeypatch)
    folder = tmp_path / "single"
    folder.mkdir(parents=True)
    target = folder / "SONE-001.nfo"
    target.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>old title</title>
  <originaltitle>SONE-001 Original Title</originaltitle>
  <plot>old plot</plot>
  <originalplot>Original English plot.</originalplot>
</movie>
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "allowed_translation_roots", (folder.parent.resolve(),))
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_ai_translation", True)
    monkeypatch.setattr(settings, "ai_translation_api_key", "test-key")

    watch = client.post(
        "/api/v1/translation/watch-folders",
        json={
            "name": "single",
            "folder_path": str(folder),
            "prompt_template": "translate to chinese",
            "enabled": True,
        },
    )
    assert watch.status_code == 201

    search = client.get("/api/v1/translation/files/search", params={"q": "sone-001", "folder_path": str(folder)})
    assert search.status_code == 200
    items = search.json()["items"]
    assert len(items) == 1
    assert items[0]["identifier"] == "SONE-001"

    from app.services import nfo_translation

    monkeypatch.setattr(
        nfo_translation,
        "translate_title_and_plot",
        lambda *args, **kwargs: {"title": "SONE-001 中文标题", "plot": "中文简介"},
    )

    run = client.post(
        "/api/v1/translation/files/run",
        json={"file_path": str(target), "watch_folder_id": watch.json()["id"], "mode": "translate"},
    )
    assert run.status_code == 202
    job = wait_for_translation_job(client, run.json()["id"])
    assert job["status"] == "success"
    assert job["translated_count"] == 1


def test_translation_plot_br_tags_are_normalized_when_writing(client, tmp_path, monkeypatch):
    patch_translation_task_manager_inline(monkeypatch)
    folder = tmp_path / "normalize"
    folder.mkdir(parents=True)
    target = folder / "CAWD-718.nfo"
    target.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>old title</title>
  <originaltitle>CAWD-718 Original Title</originaltitle>
  <plot>old plot</plot>
  <originalplot>Original English plot.</originalplot>
</movie>
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "allowed_translation_roots", (folder.parent.resolve(),))
    monkeypatch.setattr(settings, "read_only_mode", False)
    monkeypatch.setattr(settings, "enable_remote_write", True)
    monkeypatch.setattr(settings, "enable_ai_translation", True)
    monkeypatch.setattr(settings, "ai_translation_api_key", "test-key")

    from app.services import nfo_translation

    monkeypatch.setattr(
        nfo_translation,
        "translate_title_and_plot",
        lambda *args, **kwargs: {
            "title": "CAWD-718 中文标题",
            "plot": "第一段<br><br>第二段<br />第三段",
        },
    )

    created = client.post(
        "/api/v1/translation/jobs",
        json={"folder_path": str(folder), "prompt_template": "translate", "mode": "translate"},
    )
    assert created.status_code == 202
    job = wait_for_translation_job(client, created.json()["id"])
    assert job["status"] == "success"

    text = target.read_text(encoding="utf-8")
    assert "<plot>第一段\n\n第二段\n第三段</plot>" in text
    assert "<br>" not in text.lower()
