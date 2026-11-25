from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.dictionary import Tier, Unit

Condition = Literal[
    "first_visit",
    "weekday_only",
    "time_limited",
    "designated_doctor",
    "korean_only",
    "foreigner_ok",
    "student_only",
    "app_pay_only",
    "review_required",
]
Fee = Literal["anesthesia", "aftercare", "consultation"]
Vat = Literal["included", "excluded", "unknown"]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    procedure_id: str
    brand_id: str | None = None
    tier: Tier
    quantity: float | None = Field(default=None, gt=0)
    unit: Unit | None = None
    area: str | None = Field(default=None, max_length=80)


class ExtractedOption(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    items: list[Item] = Field(min_length=1, max_length=10)
    is_bundle: bool
    sessions: int = Field(default=1, ge=1, le=100)
    price_from: bool = False
    vat: Vat = "unknown"
    conditions: list[Condition] = Field(default_factory=list, max_length=9)
    extra_fees: list[Fee] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1)
