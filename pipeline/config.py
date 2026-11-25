from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
PACKAGED = Path(__file__).resolve().parent / "resources"
RESOURCES = ROOT if (ROOT / "migrations").is_dir() else PACKAGED


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_",
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    database: Path = Path("data/kbeauty.sqlite3")
    snapshot_dir: Path = Path("data/snapshots")
    dictionary_path: Path = RESOURCES / "dictionary/procedures.yaml"
    migrations_dir: Path = RESOURCES / "migrations"
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    site_url: str = ""
    bot_name: str = "SeoulBeautyPrice"
    model_extract: str = Field(default="", validation_alias="MODEL_EXTRACT")
    model_extract_retry: str = Field(default="", validation_alias="MODEL_EXTRACT_RETRY")
    model_analyst: str = Field(default="", validation_alias="MODEL_ANALYST")
    analyst_provider: Literal["google_genai", "openai_compatible"] = "google_genai"
    analyst_base_url: str = ""
    analyst_api_key: SecretStr | None = Field(default=None, validation_alias="ANALYST_API_KEY")
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    daily_ai_budget_usd: Decimal = Field(default=Decimal("5.00"), gt=0)
    # A gateway's prices cannot be inferred from Google's retail pricing.
    ai_input_usd_per_million: Decimal | None = Field(default=None, ge=0)
    ai_output_usd_per_million: Decimal | None = Field(default=None, ge=0)
    crawl_limit: int = Field(default=100, ge=1, le=10000)
    crawl_require_kst_window: bool = True
    crawl_window_start: int = Field(default=0, ge=0, le=23)
    crawl_window_end: int = Field(default=7, ge=1, le=24)
    source_names: str = "babitalk,yeoshin"
    web_dir: Path = ROOT / "web"
    publish_dir: Path = Path("data/site")
    extraction_limit: int = Field(default=100, ge=1)
    extraction_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    analyst_token_limit: int = Field(default=30000, gt=0)
    analyst_max_rounds: int = Field(default=15, ge=1, le=15)
    analyst_timeout_seconds: int = Field(default=600, ge=1, le=600)
    contact_email: str = ""
    telegram_bot_token: SecretStr | None = Field(
        default=None, validation_alias="TELEGRAM_BOT_TOKEN"
    )
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    healthchecks_url: SecretStr | None = Field(default=None, validation_alias="HEALTHCHECKS_URL")

    @field_validator("analyst_base_url")
    @classmethod
    def check_analyst_base_url(cls, value: str) -> str:
        if not value:
            return value
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Analyst base URL must be https without credentials, query or fragment"
            )
        return value.rstrip("/")

    @field_validator("site_url")
    @classmethod
    def check_site_url(cls, value: str) -> str:
        if not value:
            return value
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("SITE_URL must be a public https URL without credentials")
        if url.query or url.fragment:
            raise ValueError("SITE_URL must not contain query parameters or fragments")
        return value.rstrip("/")

    @field_validator("bot_name")
    @classmethod
    def check_bot_name(cls, value: str) -> str:
        if not value.isascii() or not value.replace("-", "").isalnum():
            raise ValueError("BOT_NAME must contain ASCII letters, digits or hyphens")
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def user_agent(self) -> str:
        if not self.site_url:
            raise ValueError("Live collection requires PIPELINE_SITE_URL (the real site URL)")
        if urlsplit(self.site_url).hostname.endswith((".invalid", ".example")):
            raise ValueError("Live collection requires a real site URL, not a placeholder")
        return f"{self.bot_name}/0.1 (+{self.site_url}/)"
