from datetime import datetime
from urllib.parse import unquote, urlsplit

from protego import Protego
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse

from pipeline.config import Settings
from pipeline.db import connect
from pipeline.sources.base import CollectionStopped, SourcePolicy

CAPTCHA_SELECTORS = (
    'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], '
    '.g-recaptcha, .h-captcha, input[name="cf-turnstile-response"], '
    '#challenge-form, form[action*="captcha"], #captcha, #captcha-container'
)


def permitted_url(url: str, policy: SourcePolicy) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != policy.domain:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if parsed.username or parsed.password or port not in (None, 443):
        return False
    if policy.name == "unni":
        return False
    # robots.txt remains authoritative; this is an additional hard guard.
    path = unquote(parsed.path).casefold()
    segments = set(path.split("/"))
    if policy.name == "yeoshin" and segments & {
        "api",
        "_next",
        "cart",
        "mypage",
        "payment",
        "admin",
        "callback",
        "auth",
    }:
        return False
    if policy.name == "babitalk" and segments & {
        "login",
        "mypage",
        "elb-status",
        "sentry-example-page",
    }:
        return False
    if policy.name == "babitalk" and "gad_source=" in unquote(parsed.query).casefold():
        return False
    return True


class SourceGate:
    def __init__(self, settings: Settings, policy: SourcePolicy):
        self.settings = settings
        self.policy = policy

    @property
    def date(self) -> str:
        return datetime.now(self.settings.tz).date().isoformat()

    def ensure_open(self) -> None:
        with connect(self.settings.database) as conn:
            row = conn.execute(
                "SELECT reason FROM source_state WHERE source=? AND date=? AND stopped=1",
                (self.policy.name, self.date),
            ).fetchone()
        if row:
            raise CollectionStopped(f"{self.policy.name} stopped for {self.date}: {row[0]}")

    def stop(self, reason: str) -> None:
        with connect(self.settings.database) as conn:
            conn.execute(
                "INSERT INTO source_state (source, date, stopped, reason) VALUES (?, ?, 1, ?) "
                "ON CONFLICT(source, date) DO UPDATE SET stopped=1, reason=excluded.reason",
                (self.policy.name, self.date, reason),
            )
            conn.execute(
                "INSERT OR IGNORE INTO alerts (source, date, code, message) VALUES (?, ?, ?, ?)",
                (self.policy.name, self.date, "source_blocked", reason),
            )


class SourceSafetyMiddleware:
    """Runs before robots and redirect/retry middleware; stop state survives process restarts."""

    def process_request(self, request, spider):
        try:
            spider.gate.ensure_open()
        except CollectionStopped:
            raise IgnoreRequest("Source already stopped today") from None
        if not permitted_url(request.url, spider.policy):
            raise IgnoreRequest("URL outside source policy")
        internal_robots = urlsplit(request.url).path == "/robots.txt"
        if (request.meta.get("dont_obey_robotstxt") and not internal_robots) or request.meta.get(
            "playwright"
        ):
            # Browser integration requires its own robot-aware subresource routing in M1.
            raise IgnoreRequest("Robots bypass / unverified browser integration is disabled")

    def process_response(self, request, response, spider):
        blocked = response.status in (403, 429)
        challenge = isinstance(response, HtmlResponse) and bool(response.css(CAPTCHA_SELECTORS))
        if blocked or challenge:
            reason = f"http_{response.status}" if blocked else "captcha"
            spider.gate.stop(reason)
            spider.failure_reason = reason
            spider.crawler.engine.close_spider(spider, reason=reason)
            raise IgnoreRequest(f"Source stopped: {reason}")
        return response


class StrictRobotsMiddleware(RobotsTxtMiddleware):
    """Scrapy's default ignores Crawl-delay and fails open on robots download errors."""

    def _parse_robots(self, response, netloc, spider):
        if response.status != 200:
            spider.gate.stop("robots_unavailable")
            spider.failure_reason = "robots_unavailable"
        else:
            parser = Protego.parse(response.text)
            delay = parser.crawl_delay(self._default_useragent) or 0
            spider.robots_delay = max(float(delay), spider.policy.delay_seconds)
            # Existing slot already contains the robots request; future requests use this slot.
            for slot in self.crawler.engine.downloader.slots.values():
                slot.delay = max(slot.delay, spider.robots_delay)
        super()._parse_robots(response, netloc, spider)

    def _robots_error(self, failure, netloc):
        spider = self.crawler.spider
        spider.gate.stop("robots_download_error")
        spider.failure_reason = "robots_download_error"
        super()._robots_error(failure, netloc)

    def process_request_2(self, rp, request, spider):
        try:
            spider.gate.ensure_open()
        except CollectionStopped:
            raise IgnoreRequest("Robots unavailable; fail closed") from None
        if rp is None:
            raise IgnoreRequest("Missing robots policy; fail closed")
        return super().process_request_2(rp, request, spider)


def crawler_settings(settings: Settings, policy: SourcePolicy) -> dict:
    return {
        "USER_AGENT": settings.user_agent,
        "ROBOTSTXT_OBEY": True,
        "ROBOTSTXT_PARSER": "scrapy.robotstxt.ProtegoRobotParser",
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": policy.delay_seconds,
        "RANDOMIZE_DOWNLOAD_DELAY": False,  # default jitter could violate the hard minimum
        "AUTOTHROTTLE_ENABLED": False,
        "RETRY_ENABLED": False,
        "COOKIES_ENABLED": False,
        "HTTPCACHE_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 30,
        "DOWNLOAD_MAXSIZE": 10 * 1024 * 1024,
        "DEFAULT_REQUEST_HEADERS": {"Accept-Language": "ko"},
        "DOWNLOADER_MIDDLEWARES": {
            "pipeline.sources.policy.SourceSafetyMiddleware": 50,
            "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
            "pipeline.sources.policy.StrictRobotsMiddleware": 100,
        },
        "LOG_LEVEL": "WARNING",
        "TELNETCONSOLE_ENABLED": False,
    }
