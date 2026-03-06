from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.api import routes as api_routes
from app.core.config import get_settings
from app.db import session as db_session
from app.main import app


@pytest.fixture()
def test_settings(tmp_path: Path):
    settings = get_settings()
    settings.data_dir = tmp_path / "data"
    settings.media_dir = tmp_path / "media"
    settings.subtitles_dir = tmp_path / "subtitles"
    settings.backups_dir = tmp_path / "backups"
    settings.models_dir = tmp_path / "models"

    for path in [
        settings.data_dir,
        settings.media_dir,
        settings.subtitles_dir,
        settings.backups_dir,
        settings.models_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    return settings


@pytest.fixture()
def test_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_settings):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(api_routes, "engine", engine)
    db_session.init_db()
    return engine


@pytest.fixture()
def db(test_engine):
    with Session(test_engine) as session:
        yield session


@pytest.fixture()
def client(test_engine):
    with TestClient(app) as test_client:
        yield test_client
