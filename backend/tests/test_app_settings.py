def test_app_settings_defaults_and_update(client):
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["organizer_task"]["source_root"] == "/mnt/clouddrive/115open/原始库/小姐姐/骑兵"
    assert data["one_click_ingest"]["source_root"] == "/mnt/clouddrive/115open/云下载"
    assert data["translation_defaults"]["folder_path"] == "/mnt/local-media/小姐姐/骑兵"
    assert data["western_poster_defaults"]["root"] == "/mnt/local-media/data/strm/原始库/不正常视频/link/欧美"

    data["organizer_task"]["source_root"] = "/mnt/clouddrive/custom/source"
    data["translation_defaults"]["auto_translate"] = False
    updated = client.put("/api/v1/settings", json=data)
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["organizer_task"]["source_root"] == "/mnt/clouddrive/custom/source"
    assert payload["translation_defaults"]["auto_translate"] is False

    refetched = client.get("/api/v1/settings")
    assert refetched.status_code == 200
    payload = refetched.json()
    assert payload["organizer_task"]["source_root"] == "/mnt/clouddrive/custom/source"
    assert payload["translation_defaults"]["auto_translate"] is False
