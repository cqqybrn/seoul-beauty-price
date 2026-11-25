import re
from datetime import datetime

from scrapy.spiders import SitemapSpider

from pipeline.config import Settings
from pipeline.db import connect
from pipeline.sources.babitalk import BabitalkAdapter
from pipeline.sources.policy import SourceGate, permitted_url


class BabitalkDiscoverySpider(SitemapSpider):
    name = "babitalk_discovery"
    # A discovery job consumes sitemaps only; no detail requests are scheduled here.
    sitemap_rules = []
    sitemap_follow = [r"/sitemap/sitemap-event(?:-\d+)?\.xml$"]

    def __init__(self, *, config: Settings, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.policy = BabitalkAdapter.policy
        self.sitemap_urls = [self.policy.sitemap_url]
        self.gate = SourceGate(config, self.policy)
        self.failure_reason: str | None = None
        self.seen_urls: set[str] = set()
        self.robots_delay = self.policy.delay_seconds

    def sitemap_filter(self, entries):
        day = datetime.now(self.config.tz).date().isoformat()
        for entry in entries:
            url = entry.get("loc", "")
            if not permitted_url(url, self.policy):
                continue
            if "/sitemap/" in urlsplit_path(url):
                yield entry
                continue
            if not re.fullmatch(r"https://babitalk\.com/events/\d+", url):
                continue
            self.seen_urls.add(url)
            with connect(self.config.database) as conn:
                conn.execute(
                    "INSERT INTO discovered_urls (source, url, lastmod, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source, url) DO UPDATE SET "
                    "lastmod=excluded.lastmod, last_seen=excluded.last_seen",
                    (self.policy.name, url, entry.get("lastmod"), day, day),
                )
            # No yield: retaining metadata must not trigger a detail request.


def urlsplit_path(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).path


def needs_refresh(
    lastmod: str | None, fetched_lastmod: str | None, last_fetched: str | None, today: str
) -> bool:
    if last_fetched is None:
        return True
    if lastmod is not None:
        return lastmod != fetched_lastmod
    return last_fetched[:10] != today
