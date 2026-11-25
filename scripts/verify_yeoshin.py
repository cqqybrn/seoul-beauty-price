"""Bounded, user-requested real-site parser verification, NOT the nightly production job.

Uses the actual local preview contact page in its own-name UA; no invented public domain.
Scrapy robots, fixed 5-second delay, no retry, no login, no APIs, no raw HTML persistence.
"""

import json
import sys
from pathlib import Path

from scrapy import Request, Spider
from scrapy.crawler import CrawlerProcess

from pipeline.config import Settings
from pipeline.db import migrate
from pipeline.sources.policy import SourceGate
from pipeline.sources.yeoshin import YeoshinAdapter


class VerifySpider(Spider):
    name = "verify_yeoshin"

    def __init__(self, *, ids: list[str], output: Path, config: Settings, **kwargs):
        super().__init__(**kwargs)
        self.ids = ids
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.policy = YeoshinAdapter.policy
        self.gate = SourceGate(config, self.policy)
        self.failure_reason = None
        self.robots_delay = 5
        self.counts = {"pages": 0, "events": 0, "options": 0, "skipped": 0}

    async def start(self):
        for event_id in self.ids:
            yield Request(
                f"https://www.yeoshin.co.kr/event/mobile/{event_id}",
                callback=self.detail,
                errback=self.failed,
            )

    def detail(self, response):
        self.counts["pages"] += 1
        try:
            facts = YeoshinAdapter().parse_detail(response.text, response.url)
        except Exception as exc:
            self.counts["skipped"] += 1
            print(
                json.dumps(
                    {
                        "event": response.url.rsplit("/", 1)[-1],
                        "parsed": False,
                        "reason": str(exc)[:1600],
                    },
                    ensure_ascii=False,
                )
            )
            return
        (self.output / f"{facts.source_event_id}.json").write_text(
            facts.model_dump_json(indent=2), encoding="utf-8"
        )
        self.counts["events"] += 1
        self.counts["options"] += len(facts.options)
        print(
            json.dumps(
                {
                    "event": facts.source_event_id,
                    "parsed": True,
                    "options": len(facts.options),
                    "clinic": facts.clinic_name,
                    "title": facts.title_raw,
                },
                ensure_ascii=False,
            )
        )

    def failed(self, failure):
        self.failure_reason = "request_failed"

    def closed(self, reason):
        (self.output / "summary.json").write_text(
            json.dumps(
                {
                    **self.counts,
                    "close_reason": reason,
                    "failure": self.failure_reason,
                    "mode": "bounded_development_verification",
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def main():
    ids = sys.argv[1:] or ["29421"]
    if len(ids) > 50 or not all(i.isdigit() for i in ids):
        raise ValueError("Verification accepts at most 50 numeric event IDs")
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
            "DOWNLOAD_TIMEOUT": 35,
            "DOWNLOAD_MAXSIZE": 5 * 1024 * 1024,
            "DOWNLOADER_MIDDLEWARES": {
                "pipeline.sources.policy.SourceSafetyMiddleware": 50,
                "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
                "pipeline.sources.policy.StrictRobotsMiddleware": 100,
            },
            "LOG_LEVEL": "ERROR",
        }
    )
    process.crawl(VerifySpider, ids=ids, output=Path("data/verified/yeoshin"), config=config)
    process.start()


if __name__ == "__main__":
    main()
