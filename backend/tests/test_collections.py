from tests.test_api import wait_for_scan


def seed_collection_data(client, media_root):
    for filename in ["SSIS-001 part1.mp4", "SSIS-001 part2.mkv", "IPZZ-123 movie.mp4"]:
        (media_root / filename).write_bytes(b"fake")
    source = client.post("/api/v1/sources", json={
        "name": "Collections",
        "provider_type": "local_fs",
        "root_path": str(media_root),
    }).json()
    job = client.post(f"/api/v1/sources/{source['id']}/scans").json()
    assert wait_for_scan(client, job["id"])["status"] == "success"

    csv_content = (
        "identifier,title,actors,studio,series,release_date,cover_url\n"
        "ssis001,Title One,Actor A|Actor B,Studio One,Series One,2024-01-01,/covers/one.jpg\n"
        "ipzz123,Title Two,Actor A,Studio Two,Series One,2025-02-03,/covers/two.jpg\n"
    )
    response = client.post("/api/v1/metadata/import/csv", content=csv_content.encode())
    assert response.status_code == 200


def test_actor_collections_search_sort_and_pagination(client, media_root):
    seed_collection_data(client, media_root)

    response = client.get("/api/v1/collections/actors")
    assert response.status_code == 200
    actor_a = response.json()["items"][0]
    assert actor_a == {
        "actor": "Actor A",
        "file_count": 3,
        "identifier_count": 2,
        "latest_release_date": "2025-02-03",
        "cover_url": "/covers/two.jpg",
    }

    searched = client.get("/api/v1/collections/actors", params={"q": "actor b"}).json()
    assert searched["total"] == 1
    assert searched["items"][0]["file_count"] == 2

    paged = client.get(
        "/api/v1/collections/actors",
        params={"sort_by": "latest_release_date", "sort_order": "asc", "page_size": 1, "page": 2},
    ).json()
    assert paged["total"] == 2
    assert len(paged["items"]) == 1


def test_collection_file_details_for_all_kinds(client, media_root):
    seed_collection_data(client, media_root)

    actor_files = client.get("/api/v1/collections/actors/Actor%20A/files").json()
    assert actor_files["total"] == 3
    assert set(actor_files["items"][0]) == {
        "id", "filename", "path", "identifier", "title", "actors", "studio", "series", "size"
    }

    studio = client.get("/api/v1/collections/studios").json()
    assert studio["total"] == 2
    studio_files = client.get("/api/v1/collections/studios/Studio%20One/files").json()
    assert studio_files["total"] == 2
    assert all(item["studio"] == "Studio One" for item in studio_files["items"])

    series = client.get("/api/v1/collections/series").json()
    assert series["items"][0]["series"] == "Series One"
    assert series["items"][0]["file_count"] == 3
    series_files = client.get(
        "/api/v1/collections/series/Series%20One/files", params={"q": "IPZZ"}
    ).json()
    assert series_files["total"] == 1
    assert series_files["items"][0]["title"] == "Title Two"
