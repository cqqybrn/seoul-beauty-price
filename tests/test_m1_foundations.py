import gzip
import hashlib
import json
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scrapy import Request
from scrapy.crawler import Crawler
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, Response, XmlResponse
from scrapy.settings import Settings as ScrapySettings

from pipeline.db import connect
from pipeline.ingest import export_unlabeled, ingest_facts, is_in_scope
from pipeline.sources.babitalk import BabitalkAdapter
from pipeline.sources.base import CollectionStopped, EventFacts, SourceNotReady
from pipeline.sources.discovery import BabitalkDiscoverySpider, needs_refresh
from pipeline.sources.policy import (
    SourceGate,
    SourceSafetyMiddleware,
    StrictRobotsMiddleware,
    crawler_settings,
    permitted_url,
)
from pipeline.sources.yeoshin import YeoshinAdapter
from tests.conftest import FIXTURES


def facts():
    return EventFacts.model_validate_json(
        (FIXTURES / "event-facts.synthetic.json").read_text(encoding="utf-8")
    )


def test_headline_not_promoted_to_option_and_footer_not_clinic():
    html = (FIXTURES / "babitalk-http-headline.synthetic.html").read_text(encoding="utf-8")
    adapter = BabitalkAdapter()
    observation = adapter.observe_http(html, "https://babitalk.com/events/1")
    assert observation.has_product
    assert observation.headline_price_krw == 159000
    assert not observation.has_option_heading
    with pytest.raises(SourceNotReady):
        adapter.parse_detail(html, "https://babitalk.com/events/1")


def test_http_200_error_does_not_become_ended():
    html = (FIXTURES / "babitalk-http-error.synthetic.html").read_text(encoding="utf-8")
    assert BabitalkAdapter().observe_http(html, "https://babitalk.com/events/1").is_error_page
    with pytest.raises(SourceNotReady, match="HTTP-200"):
        BabitalkAdapter().parse_detail(html, "https://babitalk.com/events/1")


@pytest.mark.parametrize("policy", [BabitalkAdapter.policy, YeoshinAdapter.policy])
def test_settings_respect_minimum_delay(config, policy):
    settings = crawler_settings(config, policy)
    assert settings["DOWNLOAD_DELAY"] >= (5 if policy.name == "yeoshin" else 3)
    assert settings["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert settings["ROBOTSTXT_OBEY"] is True
    assert settings["RETRY_ENABLED"] is False
    assert settings["RANDOMIZE_DOWNLOAD_DELAY"] is False
    assert "SeoulBeautyPrice" in settings["USER_AGENT"]
    assert "Googlebot" not in settings["USER_AGENT"]


@pytest.mark.parametrize(
    "url",
    [
        "https://babitalk.com/login",
        "https://babitalk.com/mypage",
        "https://babitalk.com/events/1?gad_source=1",
        "http://babitalk.com/events/1",
        "https://evil.invalid/events/1",
        "https://babitalk.com:444/events/1",
        "https://evil:b@babitalk.com/events/1",
    ],
)
def test_babitalk_url_guard(url):
    assert not permitted_url(url, BabitalkAdapter.policy)


@pytest.mark.parametrize("path", ["/api/x", "/zh/api/x", "/_next/data/a", "/ko/auth/x"])
def test_yeoshin_forbidden_paths(path):
    assert not permitted_url("https://www.yeoshin.co.kr" + path, YeoshinAdapter.policy)


def spider_for(config):
    return SimpleNamespace(
        gate=SourceGate(config, BabitalkAdapter.policy),
        policy=BabitalkAdapter.policy,
        failure_reason=None,
        crawler=SimpleNamespace(engine=Mock()),
    )


@pytest.mark.parametrize(
    "status,body",
    [
        (403, "Forbidden"),
        (429, "Too many requests"),
        (200, '<iframe src="https://recaptcha.example.org"></iframe>'),
        (200, '<form id="challenge-form"></form>'),
    ],
)
def test_block_stops_source_and_persists_without_retry(config, status, body):
    spider = spider_for(config)
    middleware = SourceSafetyMiddleware()
    request = Request("https://babitalk.com/events/1")
    response = HtmlResponse(request.url, status=status, body=body.encode(), encoding="utf-8")
    with pytest.raises(IgnoreRequest):
        middleware.process_response(request, response, spider)
    spider.crawler.engine.close_spider.assert_called_once()
    with pytest.raises(CollectionStopped):
        SourceGate(config, BabitalkAdapter.policy).ensure_open()
    with pytest.raises(IgnoreRequest):
        middleware.process_request(Request("https://babitalk.com/events/2"), spider)
    with connect(config.database) as conn:
        assert conn.execute("SELECT count(*) FROM alerts").fetchone()[0] == 1


def test_internal_robots_allowed_but_bypass_rejected(config):
    spider = spider_for(config)
    middleware = SourceSafetyMiddleware()
    middleware.process_request(
        Request("https://babitalk.com/robots.txt", meta={"dont_obey_robotstxt": True}), spider
    )
    with pytest.raises(IgnoreRequest):
        middleware.process_request(
            Request("https://babitalk.com/events/1", meta={"dont_obey_robotstxt": True}), spider
        )


def test_robots_rules_enforced_by_scrapy(config):
    crawler = Crawler(
        BabitalkDiscoverySpider, ScrapySettings(crawler_settings(config, BabitalkAdapter.policy))
    )
    crawler.stats = Mock()
    middleware = RobotsTxtMiddleware(crawler)
    rp = middleware._parserimpl.from_crawler(
        crawler, (FIXTURES / "robots.synthetic.txt").read_bytes()
    )
    spider = spider_for(config)
    with pytest.raises(IgnoreRequest):
        middleware.process_request_2(rp, Request("https://babitalk.com/login"), spider)
    middleware.process_request_2(rp, Request("https://babitalk.com/events/1"), spider)


def test_robots_delay_applied(config, monkeypatch):
    # Exercise the custom layer without requiring the Twisted downloader/reactor.
    crawler = Crawler(
        BabitalkDiscoverySpider, ScrapySettings(crawler_settings(config, BabitalkAdapter.policy))
    )
    crawler.engine = SimpleNamespace(
        downloader=SimpleNamespace(slots={"babitalk.com": SimpleNamespace(delay=3)})
    )
    middleware = StrictRobotsMiddleware(crawler)
    monkeypatch.setattr(RobotsTxtMiddleware, "_parse_robots", lambda *args: None)
    response = HtmlResponse(
        "https://babitalk.com/robots.txt",
        body=(FIXTURES / "robots.synthetic.txt").read_bytes(),
        encoding="utf-8",
    )
    spider = spider_for(config)
    middleware._parse_robots(response, "babitalk.com", spider)
    assert spider.robots_delay == 8
    assert crawler.engine.downloader.slots["babitalk.com"].delay == 8


def test_robots_failure_closes_gate(config, monkeypatch):
    crawler = Crawler(
        BabitalkDiscoverySpider, ScrapySettings(crawler_settings(config, BabitalkAdapter.policy))
    )
    middleware = StrictRobotsMiddleware(crawler)
    monkeypatch.setattr(RobotsTxtMiddleware, "_parse_robots", lambda *args: None)
    spider = spider_for(config)
    response = Response("https://babitalk.com/robots.txt", status=500)
    middleware._parse_robots(response, "babitalk.com", spider)
    with pytest.raises(IgnoreRequest):
        middleware.process_request_2(None, Request("https://babitalk.com/events/1"), spider)


def test_sitemap_idempotent_and_gzip(config):
    crawler = Crawler(
        BabitalkDiscoverySpider, ScrapySettings(crawler_settings(config, BabitalkAdapter.policy))
    )
    spider = BabitalkDiscoverySpider.from_crawler(crawler, config=config)
    data = (FIXTURES / "sitemap.synthetic.xml").read_bytes()
    response = XmlResponse("https://babitalk.com/sitemap/sitemap-event-0.xml", body=data)
    assert list(spider._parse_sitemap(response)) == []
    assert list(spider._parse_sitemap(response)) == []
    with connect(config.database) as conn:
        rows = conn.execute("SELECT * FROM discovered_urls").fetchall()
        assert len(rows) == 2
        assert all(row["lastmod"] for row in rows)
    compressed = Response(
        "https://babitalk.com/sitemap/fixture.xml.gz",
        body=gzip.compress(data),
        request=Request("https://babitalk.com/sitemap/fixture.xml.gz"),
    )
    assert spider._get_sitemap_body(compressed) == data


def test_incremental_refresh():
    assert needs_refresh("v1", None, None, "2026-11-15")
    assert not needs_refresh("v1", "v1", "2026-11-14", "2026-11-15")
    assert needs_refresh("v2", "v1", "2026-11-14", "2026-11-15")
    assert needs_refresh(None, None, "2026-11-14", "2026-11-15")
    assert not needs_refresh(None, None, "2026-11-15", "2026-11-15")


def test_idempotent_fact_import_and_snapshot_allowlist(config, dictionary):
    event = facts()
    ingest_facts(config, event, dictionary)
    ingest_facts(config, event, dictionary)
    with connect(config.database) as conn:
        for table, n in [
            ("clinics", 1),
            ("events", 1),
            ("options", 2),
            ("option_history", 2),
            ("raw_snapshots", 1),
        ]:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == n
        snapshot = conn.execute("SELECT * FROM raw_snapshots").fetchone()
        from pathlib import Path

        content = Path(snapshot["body_path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == snapshot["sha256"]
        assert json.loads(content)["clinic_address"] == event.clinic_address
        assert snapshot["snapshot_kind"] == "fact_projection_v1"


def test_price_change_history_and_stale_options(config, dictionary):
    event = facts()
    ingest_facts(config, event, dictionary, observed_at=datetime(2026, 11, 14, tzinfo=config.tz))
    updated = event.model_copy(deep=True)
    updated.options = [updated.options[0].model_copy(update={"price_krw": 169000})]
    ingest_facts(config, updated, dictionary, observed_at=datetime(2026, 11, 15, tzinfo=config.tz))
    with connect(config.database) as conn:
        assert conn.execute("SELECT count(*) FROM options WHERE active=1").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM option_history").fetchone()[0] == 3
        changed = conn.execute(
            "SELECT previous_price_krw FROM v_price_changes WHERE observed_date='2026-11-15'"
        ).fetchone()
        assert changed[0] == 159000


def test_title_tax_change_invalidates_extraction_hash(config, dictionary):
    event = facts()
    ingest_facts(config, event, dictionary)
    with connect(config.database) as conn:
        old_hash = conn.execute("SELECT content_hash FROM options ORDER BY id").fetchone()[0]
    event.vat = "excluded"
    ingest_facts(config, event, dictionary)
    with connect(config.database) as conn:
        assert (
            conn.execute("SELECT content_hash FROM options ORDER BY id").fetchone()[0] != old_hash
        )


@pytest.mark.parametrize("address", ["경기 수원시 테스트로 1", "부산 서울로 1", "서울로 123"])
def test_non_seoul_filtered(config, dictionary, address):
    event = facts().model_copy(update={"clinic_address": address})
    assert not is_in_scope(event, dictionary)
    assert ingest_facts(config, event, dictionary)["skipped"] == 1
    assert not config.snapshot_dir.exists()


def test_out_of_scope_procedure_filtered(config, dictionary):
    event = facts()
    event.title_raw = "쌍꺼풀"
    for option in event.options:
        option.name_raw = "눈성형"
    assert not is_in_scope(event, dictionary)


def test_unlabeled_export_wont_fabricate_100(config, dictionary, tmp_path):
    ingest_facts(config, facts(), dictionary)
    destination = tmp_path / "unlabeled.jsonl"
    with pytest.raises(ValueError, match="only 2"):
        export_unlabeled(config.database, destination)
    assert not destination.exists()


def test_gate_resets_next_day(config):
    gate = SourceGate(config, BabitalkAdapter.policy)
    with connect(config.database) as conn:
        conn.execute("INSERT INTO source_state VALUES ('babitalk', '2000-01-01', 1, '403')")
    gate.ensure_open()
    assert replace(BabitalkAdapter.policy, name="unni").name == "unni"


def test_duplicate_options_rejected_before_snapshot(config, dictionary):
    event = facts()
    event.options.append(event.options[0])
    with pytest.raises(ValueError, match="Duplicate"):
        ingest_facts(config, event, dictionary)
    assert not config.snapshot_dir.exists()


def test_unlabeled_export(config, dictionary, tmp_path):
    ingest_facts(config, facts(), dictionary)
    destination = tmp_path / "unlabeled.jsonl"
    assert export_unlabeled(config.database, destination, limit=2) == 2
    rows = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["price_krw"] == 159000
    assert rows[0]["content_hash"]


def test_snapshot_cannot_add_review_or_photo_fields():
    from pydantic import ValidationError

    data = facts().model_dump()
    data["review_text"] = "not allowed"
    with pytest.raises(ValidationError):
        EventFacts.model_validate(data)
