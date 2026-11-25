from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceNotReady(RuntimeError):
    """A source is not verified enough to safely produce comparable facts."""


class CollectionStopped(RuntimeError):
    """Source-wide collection was stopped for the KST day."""


@dataclass(frozen=True)
class SourcePolicy:
    name: str
    domain: str
    sitemap_url: str
    delay_seconds: float
    concurrency: int = 1
    sitewide_vat_included: bool = False


class OptionFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_option_id: str = Field(min_length=1)
    name_raw: str = Field(min_length=1)
    sessions_raw: str | None = None
    list_price_krw: int | None = Field(default=None, gt=0)
    price_krw: int = Field(gt=0)
    coupon_price_krw: int | None = Field(default=None, gt=0)


class EventFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["babitalk", "yeoshin"]
    source_event_id: str = Field(min_length=1)
    url: str
    title_raw: str = Field(min_length=1)
    clinic_name: str = Field(min_length=1)
    clinic_address: str = Field(min_length=1)
    source_clinic_id: str | None = None
    clinic_url: str | None = None
    district: str | None = None
    area: str | None = None
    foreign_patient_registered: bool | None = None
    vat: Literal["included", "excluded", "unknown"] = "unknown"
    extra_fees: list[Literal["anesthesia", "aftercare", "consultation"]] = Field(
        default_factory=list
    )
    options: list[OptionFacts] = Field(min_length=1)


class SourceAdapter(ABC):
    policy: SourcePolicy

    @abstractmethod
    def parse_detail(self, html: str, url: str) -> EventFacts:
        """Return only allowed facts; never promote a headline price to an option."""
