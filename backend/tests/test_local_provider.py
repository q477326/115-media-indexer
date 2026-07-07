from app.providers.local_fs import LocalFSProvider


def test_only_supported_video_extensions_are_listed(media_root):
    included = ["a.mp4", "b.MKV", "c.avi", "d.wmv", "e.mov", "f.ts", "g.m2ts"]
    excluded = ["cover.jpg", "poster.png", "movie.nfo", "sub.srt", "sub.ass", "note.txt", "unknown.webm"]
    for filename in included + excluded:
        (media_root / filename).touch()

    names = {file.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for file in LocalFSProvider().list_files(str(media_root))}
    assert names == set(included)
