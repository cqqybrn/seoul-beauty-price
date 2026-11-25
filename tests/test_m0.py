import json
import sqlite3
from datetime import datetime

import pytest
from pydantic import ValidationError

from pipeline.cli import main
from pipeline.config import Settings
from pipeline.db import connect, migrate
from pipeline.dictionary import Dictionary
from pipeline.runner import STEPS, run
from pipeline.sources.base import SourceNotReady
from pipeline.sources.unni import UnniAdapter


def test_migrations_idempotent_wal_foreign_keys(config):
    assert migrate(config.database, config.migrations_dir) == 0
    with connect(config.database) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            len(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()) >= 16
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO option_history VALUES (999, '2026-11-15', 100, NULL)")


def test_migration_tampering_rejected(config, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    original = next(config.migrations_dir.glob("*.sql"))
    (directory / original.name).write_text(original.read_text(encoding="utf-8") + "\n-- edit")
    with pytest.raises(ValueError, match="modified"):
        migrate(config.database, directory)


def test_failed_migration_is_atomic(config, tmp_path):
    scripts = tmp_path / "bad"
    scripts.mkdir()
    (scripts / "002_bad.sql").write_text("CREATE TABLE never_committed (id); INVALID SQL;")
    with pytest.raises(sqlite3.OperationalError):
        migrate(config.database, scripts)
    with connect(config.database) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='never_committed'"
        ).fetchall()


def test_empty_run_logs_all_stages(config):
    run_id = run(config)
    with connect(config.database) as conn:
        rows = conn.execute("SELECT * FROM run_log WHERE run_id=?", (run_id,)).fetchall()
        assert len(rows) == len(STEPS)
        assert all(r["ok"] and r["finished_at"] for r in rows)
        assert all(json.loads(r["counts_json"])["implemented"] is False for r in rows)
        assert conn.execute("SELECT count(*) FROM daily_reports").fetchone()[0] == 0


@pytest.mark.parametrize("step", STEPS)
def test_each_step_runs_independently(config, step):
    run(config, step=step)


def test_failure_stops_pipeline_and_is_logged(config, monkeypatch):
    class DaytimeClock:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 11, 15, 12, 0, tzinfo=tz)

    monkeypatch.setattr("pipeline.collection.datetime", DaytimeClock)
    with pytest.raises(SourceNotReady):
        run(config, live=True)
    with connect(config.database) as conn:
        rows = conn.execute("SELECT * FROM run_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["ok"] == 0
        assert rows[0]["step"] == "discover"


def test_cli(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "cli.db"), "run"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == len(STEPS)


def test_readonly_database_rejects_writes(config):
    with connect(config.database, readonly=True) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM events")


def test_views_have_no_raw_text(config):
    with connect(config.database) as conn:
        for view in ("v_offers", "v_bucket_stats", "v_price_changes"):
            fields = [r[1] for r in conn.execute(f"PRAGMA table_info({view})")]
            assert not {"title_raw", "name_raw", "area", "extracted_json"} & set(fields)


def test_dictionary_scope_and_aliases(dictionary):
    assert len(dictionary.procedures) == 10
    assert dictionary.matches("울쎄라 300샷") == {"ulthera"}
    assert dictionary.matches("슈링크 유니버스 300샷") == {"shurink"}
    data = dictionary.model_dump()
    data["procedures"][0]["id"] = "unapproved"
    with pytest.raises(ValidationError):
        Dictionary.model_validate(data)


def test_secrets_and_timezone():
    settings = Settings(_env_file=None, gemini_api_key="super-secret")
    assert "super-secret" not in repr(settings)
    assert settings.gemini_api_key.get_secret_value() == "super-secret"
    assert settings.tz.key == "Asia/Seoul"
    with pytest.raises(ValueError, match="SITE_URL"):
        _ = settings.user_agent
    with pytest.raises(ValidationError):
        Settings(_env_file=None, site_url="https://user:password@example.org")


def test_unni_disabled():
    with pytest.raises(NotImplementedError):
        UnniAdapter().parse_detail("", "https://unni.app/events/1")
