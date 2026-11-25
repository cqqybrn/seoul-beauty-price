"""Narrow deterministic normalizer for explicit standalone single-brand doses.

Not an AI extraction substitute: ambiguous marketing, bundles, restrictions and missing
facts are rejected. Stored provenance is rule:explicit-dose-v1, never a Gemini model ID.
"""

import re

from pipeline.dictionary import Dictionary
from pipeline.extract.schema import ExtractedOption, Item


def explicit_dose(option: dict, dictionary: Dictionary) -> ExtractedOption | None:
    text = " ".join(str(option.get(k) or "") for k in ("title_raw", "name_raw"))
    ids = dictionary.matches(text)
    if len(ids) != 1 or re.search(
        r"\+|패키지|첫\s*방문|첫\s*구매|체험|한정|부터|평일|지정|대표\s*원장"
        r"|내국인|외국인|학생|후기|별도|추가|조건"
        r"|필러\s*녹|녹이는\s*주사|히알라제",
        text,
    ):
        return None
    procedure = next(p for p in dictionary.procedures if p.id in ids)
    brands = [
        b
        for b in procedure.brands
        if any(a.casefold() in option["name_raw"].casefold() for a in b.aliases)
    ]
    if len(brands) != 1:
        return None
    if option.get("vat") != "included" or option.get("extra_fees") not in (None, "[]", []):
        return None
    # Only option name supplies dose; headline often shows another selectable dose.
    doses = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(샷|cc|CC|유닛)\b", option["name_raw"])
    if len(doses) != 1:
        return None
    quantity, raw_unit = doses[0]
    unit = {"샷": "shot", "cc": "cc", "CC": "cc", "유닛": "unit"}[raw_unit]
    sessions = re.fullmatch(r"(\d+)회(?:권)?", option.get("sessions_raw") or "")
    if not sessions:
        return None
    return ExtractedOption(
        items=[
            Item(
                procedure_id=procedure.id,
                brand_id=brands[0].id,
                tier=brands[0].tier,
                quantity=float(quantity),
                unit=unit,
            )
        ],
        is_bundle=False,
        sessions=int(sessions[1]),
        vat="included",
        confidence=1,
    )
