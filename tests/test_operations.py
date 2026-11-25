import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline.alerts import alert, heartbeat, send_pending
from pipeline.analyst.loop import analyze, declarations
from pipeline.analyst.tools import AnalystTools
from pipeline.budget import BudgetExceeded
from pipeline.collection import collect_sources
from pipeline.db import connect
from pipeline.extract.run import extract_pending
from pipeline.ingest import ingest_facts
from pipeline.publish import build_site, update_exchange_rate
from tests.test_m1_foundations import facts
from tests.test_runtime import extraction, priced_config


def test_collection_requires_real_site_before_worker(config, monkeypatch):
    settings = config.model_copy(update={"site_url": ""})
    worker = Mock()
    monkeypatch.setattr("pipeline.collection.subprocess.run", worker)
    with pytest.raises(ValueError, match="SITE_URL"):
        collect_sources(settings, "discover")
    worker.assert_not_called()


def test_failed_source_does_not_change_events(config, dictionary, monkeypatch):
    ingest_facts(config, facts(), dictionary)
    worker = Mock(return_value=SimpleNamespace(returncode=1))
    monkeypatch.setattr("pipeline.collection.subprocess.run", worker)
    settings = config.model_copy(update={"crawl_require_kst_window": False})
    with pytest.raises(RuntimeError, match="All sources"):
        collect_sources(settings, "collect")
    with connect(config.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_runs WHERE ok=0").fetchone()[0] == 2


def test_alert_outbox_idempotent_and_sends_once(config, monkeypatch):
    settings = config.model_copy(
        update={
            "telegram_bot_token": __import__("pydantic").SecretStr("test"),
            "telegram_chat_id": "123",
        }
    )
    alert(settings, "test", "A failure")
    alert(settings, "test", "A failure")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"ok":true}'
    network = Mock(return_value=response)
    monkeypatch.setattr("pipeline.alerts.urllib.request.urlopen", network)
    assert send_pending(settings) == 1
    assert send_pending(settings) == 0
    network.assert_called_once()


def test_heartbeat_failure_queues_alert(config, monkeypatch):
    settings = config.model_copy(
        update={
            "healthchecks_url": __import__("pydantic").SecretStr("https://hc-ping.example.org/test")
        }
    )
    monkeypatch.setattr("pipeline.alerts.urllib.request.urlopen", Mock(side_effect=OSError))
    heartbeat(settings, "/start")
    with connect(config.database) as conn:
        assert conn.execute("SELECT code FROM alerts").fetchone()[0] == "heartbeat_failed"


def test_fx_failure_retains_dated_cache(config, monkeypatch):
    with connect(config.database) as conn:
        conn.execute(
            "INSERT INTO exchange_rates VALUES ('2000-01-01','2000-01-01','0.005','fixture')"
        )
    monkeypatch.setattr("pipeline.publish.urllib.request.urlopen", Mock(side_effect=OSError))
    assert update_exchange_rate(config)["observed_date"] == "2000-01-01"


def test_sql_deadline_interrupts_cross_join(config, monkeypatch):
    with connect(config.database) as conn:
        conn.executemany(
            "INSERT INTO bucket_stats VALUES (?,'test',10,1,2,3,4)", [(str(i),) for i in range(250)]
        )
    clock = Mock(side_effect=[0, 6, 6, 6, 6])
    monkeypatch.setattr("pipeline.analyst.tools.time.monotonic", clock)
    with pytest.raises(ValueError, match="deadline"):
        AnalystTools(config).run_sql(
            "SELECT COUNT(*) FROM v_bucket_stats a CROSS JOIN "
            "v_bucket_stats b CROSS JOIN v_bucket_stats c"
        )


def test_analysis_time_limit_without_calls(config):
    settings = priced_config(config)
    client = Mock()
    clock = Mock(side_effect=[0, 1000])
    with pytest.raises(BudgetExceeded, match="wall-clock"):
        analyze(settings, client=client, clock=clock)
    client.complete.assert_not_called()


def test_tool_schema_refs_are_resolved():
    raw = json.dumps(declarations())
    assert "$ref" not in raw and "$defs" not in raw
    assert len(declarations()) == 4


def test_bad_extraction_stays_blocked_on_rerun(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    settings = priced_config(config)
    invoke = Mock(return_value=(extraction(confidence=0.1), 100, 100))
    with pytest.raises(ValueError, match="85%"):
        extract_pending(settings, invoke=invoke)
    calls = invoke.call_count
    with pytest.raises(ValueError, match="85%"):
        extract_pending(settings, invoke=invoke)
    assert invoke.call_count == calls


def test_successful_build_atomically_switches_pointer(config, tmp_path):
    settings = config.model_copy(update={"publish_dir": tmp_path / "site"})

    def builder(output, payload):
        output.mkdir(parents=True)
        (output / "index.html").write_text("new-site")

    try:
        result = build_site(settings, builder=builder)
    except ValueError as exc:
        if "symlink" in str(exc):
            pytest.skip("Windows directory symlink privilege unavailable")
        raise
    current = settings.publish_dir / "current"
    assert (current / "index.html").read_text() == "new-site"
    with connect(config.database) as conn:
        assert conn.execute("SELECT path FROM publication_state").fetchone()[0].endswith("site")
    assert result["offers"] == 0


def test_api_key_is_not_exported_to_static_data(config):
    from pipeline.publish import site_payload

    settings = config.model_copy(update={"model_analyst": "private-model"})
    payload = json.dumps(site_payload(settings))
    assert "private-model" not in payload
    assert "analyst_api_key" not in payload
    assert datetime.now(config.tz).date().isoformat() in payload


def test_raw_activity_options_visible_without_extraction(config, dictionary):
    from pipeline.publish import site_payload

    ingest_facts(config, facts(), dictionary)
    payload = site_payload(config)
    assert payload["offers"] == []
    assert len(payload["raw_options"]) == len(facts().options)
    row = payload["raw_options"][0]
    assert row["price_krw"] > 0
    assert row["option_name"]
    assert set(row) == {
        "id",
        "option_name",
        "sessions_raw",
        "price_krw",
        "coupon_price_krw",
        "vat",
        "event_id",
        "event_title",
        "source",
        "url",
        "observed_date",
        "clinic_id",
        "clinic_name",
        "address",
        "option_name_zh",
        "event_title_zh",
        "clinic_name_zh",
    }
    assert "content_hash" not in row
