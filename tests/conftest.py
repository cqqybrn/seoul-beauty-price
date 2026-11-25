import socket
from pathlib import Path

import pytest

from pipeline.config import Settings
from pipeline.db import migrate
from pipeline.dictionary import load_dictionary

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("pipeline.collection.subprocess.run", forbidden)


@pytest.fixture
def config(tmp_path):
    settings = Settings(
        _env_file=None,
        database=tmp_path / "test.sqlite3",
        snapshot_dir=tmp_path / "snapshots",
        site_url="https://beauty.example.org",
    )
    migrate(settings.database, settings.migrations_dir)
    return settings


@pytest.fixture
def dictionary(config):
    return load_dictionary(config.dictionary_path)
