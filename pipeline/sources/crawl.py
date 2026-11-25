"""One-off worker invoked in a fresh process so Twisted's reactor is never restarted."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from scrapy import Request
from scrapy.crawler import CrawlerProcess
from scrapy.spiders import SitemapSpider

from pipeline.config import Settings
from pipeline.db import connect
from pipeline.sources.babitalk import BabitalkAdapter
from pipeline.sources.policy import SourceGate, crawler_settings, permitted_url
from pipeline.sources.yeoshin import YeoshinAdapter

ADAPTERS = {"babitalk": BabitalkAdapter, "yeoshin": YeoshinAdapter}


class PublicSourceSpider(SitemapSpider):
    name = "public_prices"
    sitemap_rules = []

    def __init__(self, *, config, source, mode, stage_dir, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.source = source
        self.mode = mode
        self.adapter = ADAPTERS[source]()
        self.policy = self.adapter.policy
        self.gate = SourceGate(config, self.policy)
        self.stage_dir = Path(stage_dir)
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        self.sitemap_urls = [self.policy.sitemap_url]
        self.sitemap_follow = (
            [r"sitemap-event(?:-\d+)?\.xml$"]
            if source == "babitalk"
            else [r"sales_event[^/]*\.xml(?:\.gz)?$"]
        )
        self._follow = [re.compile(x) for x in self.sitemap_follow]
        self.failure_reason = None
        self.robots_delay = self.policy.delay_seconds
        self.discovered = set()
        self.parsed_count = 0
        self.failed_count = 0
        self.not_found = set()

    def sitemap_filter(self, entries):
        day = datetime.now(self.config.tz).date().isoformat()
        for entry in entries:
            url = entry.get("loc", "")
            if not permitted_url(url, self.policy):
                continue
            if ".xml" in url:
                yield entry
                continue
            pattern = (
                r"/events/\d+$" if self.source == "babitalk" else r"/(?:ko/)?event/mobile/\d+$"
            )
            if not re.search(pattern, url):
                continue
            self.discovered.add(url)
            with connect(self.config.database) as conn:
                conn.execute(
                    "INSERT INTO discovered_urls(source,url,lastmod,first_seen,last_seen) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(source,url) DO UPDATE SET "
                    "lastmod=excluded.lastmod,last_seen=excluded.last_seen",
                    (self.source, url, entry.get("lastmod"), day, day),
                )

    async def start(self):
        if self.mode == "discover":
            for url in self.sitemap_urls:
                yield Request(url, callback=self._parse_sitemap, errback=self.failed)
        else:
            with connect(self.config.database, readonly=True) as conn:
                # Conservative daily refresh: lastmod may be a shared sitemap build timestamp.
                rows = conn.execute(
                    "SELECT url FROM discovered_urls WHERE source=? ORDER BY "
                    "COALESCE(last_fetched,'') ASC,url LIMIT ?",
                    (self.source, self.config.crawl_limit),
                ).fetchall()
            if not rows:
                self.failure_reason = "no_discovered_urls"
            for row in rows:
                yield Request(
                    row["url"],
                    callback=self.detail,
                    errback=self.failed,
                    meta={"handle_httpstatus_list": [404]},
                )

    def detail(self, response):
        if response.status == 404:
            self.not_found.add(response.url.rstrip("/").split("/")[-1])
            return
        # Authentication walls are skipped, never submitted to a model.
        if response.css('input[type="password"], form[action*="login"], form[action*="signin"]'):
            self.failed_count += 1
            return
        try:
            facts = self.adapter.parse_detail(response.text, response.url)
        except Exception:
            self.failed_count += 1
            return
        path = self.stage_dir / f"{self.source}-{facts.source_event_id}.json"
        path.write_text(facts.model_dump_json(), encoding="utf-8")
        self.parsed_count += 1

    def failed(self, failure):
        self.failed_count += 1
        self.failure_reason = "request_failed"

    def closed(self, reason):
        stats = self.crawler.stats.get_stats()
        if (
            reason != "finished"
            or stats.get("spider_exceptions/count", 0)
            or stats.get("downloader/exception_count", 0)
            or stats.get("httperror/response_ignored_count", 0)
        ):
            self.failure_reason = self.failure_reason or "incomplete_crawl"
        self.result = {
            "source": self.source,
            "mode": self.mode,
            "ok": not self.failure_reason and self.failed_count == 0,
            "discovered": len(self.discovered),
            "collected": self.parsed_count,
            "failed": self.failed_count,
            "error": self.failure_reason,
            "not_found_ids": sorted(self.not_found),
        }
        (self.stage_dir / f"{self.source}-{self.mode}-result.json").write_text(
            json.dumps(self.result),
            encoding="utf-8",
        )


def main():
    source, mode, stage_dir = sys.argv[1:]
    config = Settings()
    now = datetime.now(config.tz)
    if config.crawl_require_kst_window and not (
        config.crawl_window_start <= now.hour < config.crawl_window_end
    ):
        raise ValueError("Collection is restricted to the configured KST early-morning window")
    adapter = ADAPTERS[source]()
    _ = config.user_agent  # Validate real contact URL before any network request.
    SourceGate(config, adapter.policy).ensure_open()
    process = CrawlerProcess(crawler_settings(config, adapter.policy))
    process.crawl(PublicSourceSpider, config=config, source=source, mode=mode, stage_dir=stage_dir)
    process.start()


if __name__ == "__main__":
    main()
