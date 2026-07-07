import os
import shutil
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
os.environ["ALLOWED_SCAN_ROOTS"] = str(Path("data/test-media").resolve())
os.environ["SCAN_BATCH_SIZE"] = "10"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def media_root():
    root = Path("data/test-media")
    root.mkdir(parents=True, exist_ok=True)
    for item in root.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    return root.resolve()


@pytest.fixture
def client():
    return TestClient(app)
