import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pipeline.analyst.client import Completion
from pipeline.analyst.loop import analyze
from pipeline.analyst.report_schema import Report
from pipeline.analyst.tools import AnalystTools, apply_dictionary_proposals
from pipeline.budget import BudgetExceeded, fail, reserve, settle
from pipeline.clinics import same_clinic
from pipeline.db import connect
from pipeline.extract.run import extract_pending
from pipeline.extract.schema import ExtractedOption, Item
from pipeline.ingest import ingest_facts
from pipeline.pricing import calculate, label_price, percentile, unit_price
from pipeline.publish import build_site, site_payload
from pipeline.safeguards import record_source_run, source_volume_ok, stale_sources, update_absences
from pipeline.validate import validate_extraction
from tests.test_m1_foundations import facts


def extraction(**updates):
    data = {
        "items": [
            {
                "procedure_id": "rejuran",
                "brand_id": "healer",
                "tier": "single",
                "quantity": 2,
                "unit": "cc",
            }
        ],
        "is_bundle": False,
        "sessions": 1,
        "vat": "included",
        "confidence": 0.95,
        **updates,
    }
    return ExtractedOption.model_validate(data)


def priced_config(config):
    return config.model_copy(
        update={
            "ai_input_usd_per_million": Decimal("1"),
            "ai_output_usd_per_million": Decimal("2"),
            "model_extract": "test-cheap",
            "model_extract_retry": "test-retry",
        }
    )


def seed(config, dictionary, *, count=12):
    for index in range(count):
        event = facts()
        event.source_event_id = f"test-{index}"
        event.url = f"https://babitalk.com/events/{1000000 + index}"
        event.options = [event.options[0]]
        event.options[0].price_krw = 100000 + index * 10000
        ingest_facts(config, event, dictionary)
    settings = priced_config(config)
    extract_pending(settings, invoke=lambda *args: (extraction(), 100, 100))
    calculate(settings)
    return settings


def test_vat_sessions_and_quantity():
    assert unit_price(100000, extraction(vat="excluded", sessions=5), 2) == Decimal(11000)
    assert unit_price(100000, extraction(), 2) == Decimal(50000)


@pytest.mark.parametrize("change", [{"price_from": True}, {"is_bundle": True}, {"vat": "unknown"}])
def test_unranked_cases(change):
    assert unit_price(100000, extraction(**change), 2) is None
    assert unit_price(100000, extraction(), None) is None


def test_sitewide_vat_fallback():
    assert unit_price(100000, extraction(vat="unknown"), 2, sitewide_vat=True) == 50000


def test_quantiles_and_labels():
    values = list(range(10, 110, 10))
    assert percentile(values, 0.5) == 55
    stats = {"n": 10, "p5": 14.5, "p25": 32.5, "median": 55, "p75": 77.5}
    assert label_price(10, stats) == "anomaly_low"
    assert label_price(30, stats) == "cheap"
    assert label_price(55, stats) == "normal"
    assert label_price(90, stats) == "expensive"
    assert label_price(None, stats) == "unranked"
    assert label_price(10, {**stats, "n": 9}) == "unranked"


def test_validation_unknown_brand_unit_range_confidence(dictionary):
    assert validate_extraction(extraction(), 100000, dictionary) == []
    for item, reason in [
        ({"procedure_id": "unapproved"}, "unknown_procedure"),
        ({"unit": "shot"}, "invalid_unit"),
        ({"quantity": 100}, "quantity_out_of_range"),
        ({"brand_id": "made-up"}, "unknown_brand"),
        ({"tier": "import"}, "brand_tier_mismatch"),
    ]:
        result = extraction()
        result.items[0] = result.items[0].model_copy(update=item)
        assert reason in validate_extraction(result, 100000, dictionary)
    assert "low_confidence" in validate_extraction(extraction(confidence=0.5), 100000, dictionary)
    assert "invalid_price" in validate_extraction(extraction(), 0, dictionary)


def test_validation_nonbundle_multi_and_missing_quantity(dictionary):
    result = extraction()
    result.items.append(Item(procedure_id="botox", tier="unknown", quantity=1, unit="area"))
    assert "non_bundle_multiple_items" in validate_extraction(result, 100000, dictionary)
    result.is_bundle = True
    assert not validate_extraction(result, 100000, dictionary)
    assert not validate_extraction(
        extraction(
            items=[
                {
                    "procedure_id": "rejuran",
                    "brand_id": None,
                    "tier": "unknown",
                    "quantity": None,
                    "unit": "cc",
                }
            ]
        ),
        100000,
        dictionary,
    )


@pytest.mark.parametrize("quantity", [0, -1, float("inf"), float("nan")])
def test_schema_nonfinite_rejected(quantity):
    with pytest.raises(ValidationError):
        extraction(items=[{"procedure_id": "botox", "tier": "unknown", "quantity": quantity}])


def test_extraction_cache_and_retry(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    settings = priced_config(config)
    calls = []

    def invoke(model, text):
        calls.append((model, text))
        return extraction(confidence=0.5 if model == "test-cheap" else 0.95), 100, 100

    assert extract_pending(settings, invoke=invoke)["valid"] == 2
    assert len(calls) == 4
    assert extract_pending(settings, invoke=invoke)["processed"] == 0
    assert len(calls) == 4
    assert '"untrusted_data"' in calls[0][1]


def test_extraction_success_threshold_aborts(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    with pytest.raises(ValueError, match="85%"):
        extract_pending(
            priced_config(config), invoke=lambda *args: (extraction(confidence=0.2), 100, 100)
        )
    with connect(config.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM offer_items").fetchone()[0] == 0


def test_budget_reservation_survives_failure(config):
    settings = priced_config(config).model_copy(update={"daily_ai_budget_usd": Decimal(".001")})
    first = reserve(settings, "test", "extract", 300, 100)
    fail(settings, first)
    assert reserve(settings, "test", "extract", 300, 100)
    with pytest.raises(BudgetExceeded):
        reserve(settings, "test", "extract", 1, 1)


def test_budget_actual_settlement(config):
    settings = priced_config(config)
    call = reserve(settings, "test", "extract", 1000, 1000)
    settle(settings, call, 100, 100)
    with connect(config.database) as conn:
        row = conn.execute("SELECT * FROM ai_calls").fetchone()
        assert row["state"] == "complete"
        assert Decimal(row["actual_usd"]) == Decimal(".0003")


def test_unconfigured_cost_blocks_paid_call(config):
    with pytest.raises(ValueError, match="prices"):
        reserve(config, "test", "extract", 1, 1)


def test_calculate_stable_ids_and_view(config, dictionary):
    seed(config, dictionary)
    with connect(config.database) as conn:
        before = [r[0] for r in conn.execute("SELECT id FROM offer_items")]
        assert conn.execute("SELECT COUNT(*) FROM v_offers").fetchone()[0] == 12
        labels = dict(conn.execute("SELECT label,COUNT(*) FROM labels GROUP BY label").fetchall())
        assert labels["cheap"] and labels["expensive"]
    calculate(config)
    with connect(config.database) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM offer_items")] == before


def test_changed_hash_hides_stale_offer(config, dictionary):
    seed(config, dictionary, count=1)
    event = facts()
    event.source_event_id = "test-0"
    event.url = "https://babitalk.com/events/1000000"
    event.options = [event.options[0]]
    event.options[0].price_krw = 99999
    ingest_facts(config, event, dictionary)
    with connect(config.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM v_offers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM offer_items").fetchone()[0] == 1


def test_clinic_merges_conservative():
    a = {"name_ko": "테스트의원 강남점", "address_ko": "서울 강남구 길 1 2층"}
    assert same_clinic(a, {**a, "address_ko": "서울 강남구 길1 2층"})
    assert not same_clinic(a, {**a, "name_ko": "테스트의원 신사점"})
    assert not same_clinic(a, {**a, "address_ko": "서울 강남구 길 1 3층"})
    assert not same_clinic(a, {**a, "name_ko": "다른의원"})


def test_volume_drop_and_old_data(config, dictionary):
    seed(config, dictionary, count=1)
    day = datetime.now(config.tz).date()
    for i in range(1, 8):
        record_source_run(
            config,
            "babitalk",
            (day - timedelta(days=i)).isoformat(),
            ok=True,
            discovered=100,
            collected=100,
        )
    assert not source_volume_ok(config, "babitalk", day.isoformat(), 69)
    assert source_volume_ok(config, "babitalk", day.isoformat(), 70)
    with connect(config.database) as conn:
        assert conn.execute("SELECT status FROM events").fetchone()[0] == "active"


def test_two_consecutive_absences(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    assert update_absences(config, "babitalk", "2026-11-14", set(), set()) == 0
    assert update_absences(config, "babitalk", "2026-11-15", set(), set()) == 1


def test_nonconsecutive_and_reappearing_absence(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    update_absences(config, "babitalk", "2026-11-12", set(), set())
    assert update_absences(config, "babitalk", "2026-11-14", set(), set()) == 0
    assert update_absences(config, "babitalk", "2026-11-15", {"fixture-1"}, set()) == 0
    assert update_absences(config, "babitalk", "2026-11-16", set(), set()) == 0


def test_two_404_observations(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    update_absences(config, "babitalk", "2026-11-14", {"fixture-1"}, {"fixture-1"})
    assert update_absences(config, "babitalk", "2026-11-15", {"fixture-1"}, {"fixture-1"}) == 1


def test_three_failed_days_mark_stale(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    day = datetime.now(config.tz).date()
    for i in range(3):
        record_source_run(
            config,
            "babitalk",
            (day - timedelta(days=i)).isoformat(),
            ok=False,
            discovered=0,
            collected=0,
        )
    assert "babitalk" in stale_sources(config, day.isoformat())
    with connect(config.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0] == 1


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM events",
        "SELECT * FROM events",
        "SELECT name_raw FROM options",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM v_offers; DROP TABLE events",
        "SELECT * FROM v_offers -- comment",
        "PRAGMA query_only=OFF",
        "ATTACH DATABASE 'x' AS x",
        "SELECT load_extension('x')",
        "SELECT randomblob(1000000000)",
        "SELECT * FROM v_offers JOIN options ON 1=1",
    ],
)
def test_sql_sandbox_rejects(config, query):
    with pytest.raises(ValueError):
        AnalystTools(config).run_sql(query)


def test_sql_sandbox_views(config, dictionary):
    seed(config, dictionary, count=1)
    tools = AnalystTools(config)
    assert tools.run_sql("SELECT COUNT(*) AS n FROM v_offers")[0]["n"] == 1
    assert tools.run_sql("SELECT * FROM v_price_changes")[0]["price_krw"] == 100000
    assert tools.run_sql("SELECT * FROM v_bucket_stats")


def test_sql_row_limit(config):
    rows = AnalystTools(config).run_sql(
        "SELECT 1 AS x UNION ALL SELECT * FROM (SELECT 2 UNION ALL SELECT 3) LIMIT 3"
    )
    assert len(rows) == 3
    with connect(config.database) as conn:
        conn.executemany(
            "INSERT INTO bucket_stats VALUES (?,'test',10,1,2,3,4)", [(str(i),) for i in range(250)]
        )
    assert len(AnalystTools(config).run_sql("SELECT * FROM v_bucket_stats")) == 200


@pytest.mark.parametrize(
    "note", ["便宜 20%", "价格９９", "<script>x</script>", "[医院](https://x)", "二百元"]
)
def test_model_notes_cannot_supply_numbers_or_html(note):
    day = datetime.now().date().isoformat()
    with pytest.raises(ValidationError):
        Report.model_validate({"date": day, "new_offers": [{"offer_item_id": 1, "note": note}]})


def test_submit_report_validates_ids_and_date(config, dictionary):
    seed(config, dictionary, count=1)
    tools = AnalystTools(config)
    day = datetime.now(config.tz).date().isoformat()
    with pytest.raises(ValueError, match="inactive"):
        tools.submit_report({"date": day, "new_offers": [{"offer_item_id": 999, "note": "新上架"}]})
    with pytest.raises(ValueError, match="date"):
        tools.submit_report({"date": "2000-01-01"})
    assert tools.submit_report(
        {"date": day, "new_offers": [{"offer_item_id": 1, "note": "新上架"}]}
    )["accepted"]
    with connect(config.database) as conn:
        assert conn.execute("SELECT published FROM daily_reports").fetchone()[0] == 0
    data = site_payload(config, include_draft=True)
    assert data["report"]["sections"][1]["entries"][0]["price_krw"] == 100000
    assert data["report"]["sections"][1]["entries"][0]["clinic_name"] == "테스트의원"


def test_failed_build_retains_publication(config, tmp_path):
    settings = config.model_copy(update={"publish_dir": tmp_path / "site"})
    current = settings.publish_dir / "current"
    current.mkdir(parents=True)
    (current / "index.html").write_text("old-site")

    def bad(output, payload):
        raise ValueError("test failure")

    with pytest.raises(ValueError):
        build_site(settings, builder=bad)
    assert (current / "index.html").read_text() == "old-site"
    with connect(config.database) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM alerts WHERE code='build_failed'").fetchone()[0] == 1
        )


def test_analysis_loop_submits_using_validated_tool(config, dictionary):
    settings = seed(config, dictionary, count=1).model_copy(update={"analyst_token_limit": 100000})
    report = {
        "date": datetime.now(config.tz).date().isoformat(),
        "new_offers": [{"offer_item_id": 1, "note": "新上架观察"}],
    }
    completion = Completion(
        model="test",
        message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "submit_report",
                        "arguments": json.dumps({"report": report}),
                    },
                }
            ],
        },
        prompt_tokens=100,
        completion_tokens=100,
        total_tokens=200,
        finish_reason="tool_calls",
    )
    assert analyze(settings, client=Mock(complete=Mock(return_value=completion)))["submitted"]


def test_analysis_round_limit_preserves_previous_report(config):
    settings = priced_config(config).model_copy(
        update={"analyst_max_rounds": 2, "analyst_token_limit": 100000}
    )
    completion = Completion(
        model="test",
        message={"role": "assistant", "content": "hello"},
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        finish_reason="stop",
    )
    with pytest.raises(BudgetExceeded, match="round"):
        analyze(settings, client=Mock(complete=Mock(return_value=completion)))
    with connect(config.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM alerts WHERE code='analyst_failed'").fetchone()[0]
            == 1
        )


def test_dictionary_proposal_verified_counts(config, dictionary, tmp_path):
    path = tmp_path / "procedures.yaml"
    shutil.copyfile(config.dictionary_path, path)
    settings = config.model_copy(update={"dictionary_path": path})
    for i in range(21):
        event = facts()
        event.source_event_id = f"dict-{i}"
        event.options = [event.options[0]]
        event.options[0].name_raw = "리쥬란힐러 새별명 2cc"
        ingest_facts(settings, event, dictionary)
    tools = AnalystTools(settings)
    assert (
        tools.propose_dictionary_entry("새별명", "rejuran", "公开选项出现的新词")[
            "verified_option_count"
        ]
        == 21
    )
    tools.propose_dictionary_entry("새별명", "unapproved", "新项目不生效")
    assert apply_dictionary_proposals(settings) == 1
    assert "새별명" in path.read_text(encoding="utf-8")


def test_direct_readonly_connection_cannot_write(config):
    with connect(config.database, readonly=True) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO dictionary_proposals(date,term_raw,suggested_procedure,reason) "
                "VALUES ('2026-11-15','x','botox','x')"
            )
