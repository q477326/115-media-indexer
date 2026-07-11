def test_app_settings_defaults_and_update(client):
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["organizer_task_kibin"]["source_root"] == "/mnt/clouddrive/115open/原始库/不正常视频/qb/骑兵"
    assert data["organizer_task_western"]["source_root"] == "/mnt/clouddrive/115open/原始库/不正常视频/qb/欧美"
    assert data["organizer_task_uncensored"]["source_root"] == "/mnt/clouddrive/115open/原始库/不正常视频/qb/无码"
    assert data["organizer_task_domestic"]["source_root"] == "/mnt/clouddrive/115open/原始库/不正常视频/qb/国产"
    assert data["one_click_ingest"]["source_root"]
    assert data["translation_defaults"]["folder_path"]
    assert data["western_poster_defaults"]["root"]

    data["organizer_task_kibin"]["source_root"] = "/mnt/clouddrive/custom/kibin"
    data["organizer_task_western"]["source_root"] = "/mnt/clouddrive/custom/western"
    data["organizer_task_uncensored"]["source_root"] = "/mnt/clouddrive/custom/uncensored"
    data["organizer_task_domestic"]["source_root"] = "/mnt/clouddrive/custom/domestic"
    data["translation_defaults"]["auto_translate"] = False
    updated = client.put("/api/v1/settings", json=data)
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["organizer_task_kibin"]["source_root"] == "/mnt/clouddrive/custom/kibin"
    assert payload["organizer_task_western"]["source_root"] == "/mnt/clouddrive/custom/western"
    assert payload["organizer_task_uncensored"]["source_root"] == "/mnt/clouddrive/custom/uncensored"
    assert payload["organizer_task_domestic"]["source_root"] == "/mnt/clouddrive/custom/domestic"
    assert payload["translation_defaults"]["auto_translate"] is False

    refetched = client.get("/api/v1/settings")
    assert refetched.status_code == 200
    payload = refetched.json()
    assert payload["organizer_task_kibin"]["source_root"] == "/mnt/clouddrive/custom/kibin"
    assert payload["organizer_task_western"]["source_root"] == "/mnt/clouddrive/custom/western"
    assert payload["organizer_task_uncensored"]["source_root"] == "/mnt/clouddrive/custom/uncensored"
    assert payload["organizer_task_domestic"]["source_root"] == "/mnt/clouddrive/custom/domestic"
    assert payload["translation_defaults"]["auto_translate"] is False
