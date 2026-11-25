from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROCEDURE_IDS = frozenset(
    {
        "botox",
        "filler",
        "ulthera",
        "thermage",
        "shurink",
        "rejuran",
        "skinbooster",
        "pico",
        "inmode",
        "potenza",
    }
)
Unit = Literal["shot", "unit", "cc", "session", "area", "vial"]
Tier = Literal["import", "domestic", "single", "unknown"]


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    aliases: list[str] = Field(min_length=1)
    tier: Tier


class Procedure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name_zh: str
    name_ko: str
    aliases: list[str] = Field(min_length=1)
    canonical_units: list[Unit] = Field(min_length=1)
    quantity_bounds: dict[Unit, tuple[float, float]]
    brands: list[Brand]

    @model_validator(mode="after")
    def consistent_bounds(self):
        if self.id not in PROCEDURE_IDS:
            raise ValueError(f"New procedure not permitted in this release: {self.id}")
        if set(self.canonical_units) != set(self.quantity_bounds):
            raise ValueError("Each canonical unit needs bounds")
        if any(lo <= 0 or hi < lo for lo, hi in self.quantity_bounds.values()):
            raise ValueError("Bounds must be positive and ascending")
        if len({b.id for b in self.brands}) != len(self.brands):
            raise ValueError("Duplicate brand ID")
        return self


class Dictionary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    procedures: list[Procedure]

    @model_validator(mode="after")
    def exact_scope(self):
        ids = [p.id for p in self.procedures]
        if len(ids) != 10 or set(ids) != PROCEDURE_IDS:
            raise ValueError("Dictionary must contain exactly the ten approved procedures")
        return self

    def matches(self, *texts: str) -> set[str]:
        text = " ".join(texts).casefold()
        return {
            p.id for p in self.procedures if any(alias.casefold() in text for alias in p.aliases)
        }


def load_dictionary(path: Path) -> Dictionary:
    return Dictionary.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
