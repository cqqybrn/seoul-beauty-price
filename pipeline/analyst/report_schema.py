import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def plain_note(value: str) -> str:
    if re.search(r"[<>]|https?://|www\.|\]\(|javascript:|&#", value, re.I):
        raise ValueError("Report notes cannot include HTML or links")
    if any(unicodedata.category(c).startswith("N") for c in value) or re.search(
        r"[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟]+"
        r"(?:元|韩元|人民币|万|折|%|％|发|次|cc|unit)",
        value,
        re.I,
    ):
        raise ValueError(
            "Report notes must not contain numeric claims; use database-rendered fields"
        )
    return value


class OfferNote(PlainModel):
    offer_item_id: int = Field(gt=0)
    note: str = Field(max_length=60)
    _plain = field_validator("note")(plain_note)


class AnomalyNote(OfferNote):
    reason_code: Literal[
        "small_dose",
        "first_visit",
        "domestic_brand",
        "bundle_split",
        "suspected_error",
        "other",
    ]


class BucketNote(PlainModel):
    bucket_key: str = Field(max_length=100)
    note: str = Field(max_length=60)
    _plain = field_validator("note")(plain_note)


class QualityNote(PlainModel):
    issue: str = Field(max_length=100)
    detail: str = Field(max_length=300)


class Report(PlainModel):
    date: date
    price_drops: list[OfferNote] = Field(default_factory=list, max_length=30)
    new_offers: list[OfferNote] = Field(default_factory=list, max_length=30)
    anomalies: list[AnomalyNote] = Field(default_factory=list, max_length=30)
    bucket_notes: list[BucketNote] = Field(default_factory=list, max_length=30)
    data_quality: list[QualityNote] = Field(default_factory=list, max_length=30)
