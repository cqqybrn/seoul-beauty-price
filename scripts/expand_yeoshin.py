"""Requested development collection: complete Korean sitemap discovery, bounded detail crawl.

No timers/background jobs: run and monitor in this task. All requests pass strict robots,
source stop gates and fixed >=5s serial downloader. Only allowlisted public facts persist.
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from scrapy import Request
from scrapy.crawler import CrawlerProcess
from scrapy.spiders import SitemapSpider
from scrapy.utils.sitemap import Sitemap

from pipeline.config import Settings
from pipeline.db import connect, migrate
from pipeline.dictionary import load_dictionary
from pipeline.ingest import is_in_scope
from pipeline.sources.base import SourceNotReady
from pipeline.sources.policy import SourceGate
from pipeline.sources.yeoshin import YeoshinAdapter


class ExpandSpider(SitemapSpider):
    name = "expand_yeoshin"

    def __init__(self, *, config, limit, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.limit = limit
        self.policy = YeoshinAdapter.policy
        self.gate = SourceGate(config, self.policy)
        self.robots_delay = 5.1
        self.failure_reason = None
        self.dictionary = load_dictionary(config.dictionary_path)
        self.output = Path("data/verified/yeoshin")
        self.output.mkdir(parents=True, exist_ok=True)
        self.state_path = Path("data/yeoshin-expansion-progress.json")
        self.entries = {}
        self.pending_sitemaps = set()
        self.scheduled = set()
        self.recommendations = {}
        self.reasons = Counter()
        self.counts = {
            "sitemaps": 0,
            "discovered": 0,
            "scheduled": 0,
            "pages": 0,
            "parsed_events": 0,
            "parsed_options": 0,
            "seoul_events": 0,
            "seoul_options": 0,
            "skipped": 0,
        }
        self.started_at = datetime.now(config.tz).isoformat()
        self._report("starting")

    def _report(self, status):
        payload = {
            **self.counts,
            "status": status,
            "started_at": self.started_at,
            "updated_at": datetime.now(self.config.tz).isoformat(),
            "skip_reasons": dict(self.reasons),
            "failure": self.failure_reason,
        }
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.state_path)

    async def start(self):
        yield Request(self.policy.sitemap_url, callback=self.index, errback=self.failed)

    def index(self, response):
        body = self._get_sitemap_body(response)
        if body is None:
            raise SourceNotReady("No sitemap index body")
        urls = [
            e["loc"]
            for e in Sitemap(body)
            if re.fullmatch(
                r"https://www\.yeoshin\.co\.kr/sitemap/sales_event_\d+\.xml\.gz", e.get("loc", "")
            )
        ]
        if not urls:
            raise SourceNotReady("No Korean sales-event sitemaps in index")
        self.pending_sitemaps = set(urls)
        for url in urls:
            yield Request(url, callback=self.event_sitemap, errback=self.failed, priority=100)

    def event_sitemap(self, response):
        body = self._get_sitemap_body(response)
        if body is None:
            raise SourceNotReady("Invalid event sitemap")
        day = datetime.now(self.config.tz).date().isoformat()
        rows = []
        for entry in Sitemap(body):
            url = entry.get("loc", "")
            if not re.fullmatch(r"https://www\.yeoshin\.co\.kr/event/mobile/\d+", url):
                continue
            self.entries[url] = entry.get("lastmod")
            rows.append(("yeoshin", url, entry.get("lastmod"), day, day))
        with connect(self.config.database) as conn:
            conn.executemany(
                "INSERT INTO discovered_urls(source,url,lastmod,first_seen,last_seen) "
                "VALUES (?,?,?,?,?) ON CONFLICT(source,url) DO UPDATE SET "
                "lastmod=excluded.lastmod,last_seen=excluded.last_seen",
                rows,
            )
        self.pending_sitemaps.discard(response.url)
        self.counts["sitemaps"] += 1
        self.counts["discovered"] = len(self.entries)
        self._report("discovering")
        print(
            json.dumps(
                {
                    "sitemap": response.url,
                    "entries": len(rows),
                    "total_discovered": len(self.entries),
                }
            ),
            flush=True,
        )
        if self.pending_sitemaps:
            return
        # Sitemap list includes expired older events. Prefer recent entries / high numeric IDs,
        # but breadth-first related pages that explicitly match our ten aliases get priority.
        ordered = sorted(
            self.entries,
            key=lambda u: (self.entries[u] or "", int(u.rsplit("/", 1)[1])),
            reverse=True,
        )
        with connect(self.config.database, readonly=True) as conn:
            done = {
                r[0]
                for r in conn.execute(
                    "SELECT url FROM discovered_urls "
                    "WHERE source='yeoshin' AND last_fetched LIKE ?",
                    (day + "%",),
                )
            }
        pending = [u for u in ordered if u not in done]
        self.already_fetched = done
        self.fallback_urls = iter(pending)
        # Keep the request frontier small so relevant links can displace unrelated new events.
        for _ in range(min(8, self.limit)):
            request = self.next_request()
            if request:
                yield request

    def next_request(self):
        if len(self.scheduled) >= self.limit or self.failure_reason:
            return None
        if self.recommendations:
            url = max(self.recommendations, key=lambda u: self.recommendations[u])
            del self.recommendations[url]
        else:
            url = next((u for u in self.fallback_urls if u not in self.scheduled), None)
        if not url or url in self.scheduled:
            return None
        self.scheduled.add(url)
        self.counts["scheduled"] = len(self.scheduled)
        return Request(
            url, callback=self.detail, errback=self.failed, meta={"handle_httpstatus_list": [404]}
        )

    def detail(self, response):
        self.counts["pages"] += 1
        outcome = "http_404" if response.status == 404 else "parsed"
        if response.status != 404:
            # Discover only links visible in the fetched public page; don't query banned APIs.
            for a in response.css('a[href*="/event/mobile/"]'):
                href = a.attrib.get("href", "")
                url = response.urljoin(href)
                if url not in self.entries or url in self.scheduled or url in self.already_fetched:
                    continue
                title = a.xpath("string(.)").get("")
                matches = self.dictionary.matches(title)
                if matches:
                    # Prefer unseen categories without interpreting source text as instructions.
                    score = len(matches) * 10 + int("강남" in title or "서울" in title)
                    self.recommendations[url] = score
            try:
                facts = YeoshinAdapter().parse_detail(response.text, response.url)
                self.counts["parsed_events"] += 1
                self.counts["parsed_options"] += len(facts.options)
                if is_in_scope(facts, self.dictionary):
                    self.counts["seoul_events"] += 1
                    self.counts["seoul_options"] += len(facts.options)
                    (self.output / f"{facts.source_event_id}.json").write_text(
                        facts.model_dump_json(indent=2), encoding="utf-8"
                    )
                else:
                    self.reasons["outside_seoul_or_dictionary"] += 1
            except (SourceNotReady, ValueError, KeyError) as exc:
                self.counts["skipped"] += 1
                outcome = str(exc)[:160]
                self.reasons[outcome] += 1
        else:
            self.reasons["http_404"] += 1
        with connect(self.config.database) as conn:
            conn.execute(
                "UPDATE discovered_urls SET last_fetched=?,last_outcome=? "
                "WHERE source='yeoshin' AND url=?",
                (datetime.now(self.config.tz).isoformat(), outcome, response.url),
            )
        self._report("collecting")
        if self.counts["pages"] % 10 == 0:
            print(json.dumps(self.counts), flush=True)
        request = self.next_request()
        if request:
            yield request

    def failed(self, failure):
        self.failure_reason = "request_failed"
        self._report("failed")
        self.crawler.engine.close_spider(self, reason="request_failed")

    def closed(self, reason):
        self._report("complete" if reason == "finished" and not self.failure_reason else "stopped")
        print(
            json.dumps(
                {**self.counts, "close_reason": reason, "reasons": dict(self.reasons)},
                ensure_ascii=False,
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        raise ValueError("Choose a bounded limit between 1 and 500")
    config = Settings()
    migrate(config.database, config.migrations_dir)
    process = CrawlerProcess(
        {
            "USER_AGENT": "SeoulBeautyPrice/0.1 (+http://127.0.0.1:4321/about/)",
            "DEFAULT_REQUEST_HEADERS": {"Accept-Language": "ko"},
            "ROBOTSTXT_OBEY": True,
            "ROBOTSTXT_PARSER": "scrapy.robotstxt.ProtegoRobotParser",
            "CONCURRENT_REQUESTS": 1,
            "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
            "DOWNLOAD_DELAY": 5.1,
            "RANDOMIZE_DOWNLOAD_DELAY": False,
            "RETRY_ENABLED": False,
            "COOKIES_ENABLED": False,
            "TELNETCONSOLE_ENABLED": False,
            "DOWNLOAD_TIMEOUT": 40,
            "DOWNLOAD_MAXSIZE": 8 * 1024 * 1024,
            "DOWNLOAD_WARNSIZE": 8 * 1024 * 1024,
            "DOWNLOADER_MIDDLEWARES": {
                "pipeline.sources.policy.SourceSafetyMiddleware": 50,
                "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
                "pipeline.sources.policy.StrictRobotsMiddleware": 100,
            },
            "LOG_LEVEL": "ERROR",
        }
    )
    process.crawl(ExpandSpider, config=config, limit=args.limit)
    process.start()


if __name__ == "__main__":
    main()
