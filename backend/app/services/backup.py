import csv
import io
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Iterable

from sqlalchemy.engine import Engine


def sqlite_backup_stream(engine: Engine, chunk_size: int = 1024 * 1024):
    temp = tempfile.NamedTemporaryFile(prefix="media-index-", suffix=".db", delete=False)
    temp_path = Path(temp.name)
    temp.close()
    try:
        source = engine.raw_connection()
        target = sqlite3.connect(temp_path)
        try:
            source.driver_connection.backup(target)
        finally:
            target.close()
            source.close()
        with temp_path.open("rb") as backup_file:
            while chunk := backup_file.read(chunk_size):
                yield chunk
    finally:
        temp_path.unlink(missing_ok=True)


def csv_stream(headers: list[str], rows: Iterable[list]):
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def actors_json(actors: list[str]) -> str:
    return json.dumps(actors or [], ensure_ascii=False)
