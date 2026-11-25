"""Display-only lexical classification; no inferred dose, brand or unit-price eligibility."""

import re

from pipeline.dictionary import Dictionary
from pipeline.extract.schema import ExtractedOption, Item

CONDITIONS = {
    "first_visit": r"첫\s*방문|첫\s*구매|체험가|1회\s*한정",
    "weekday_only": r"평일",
    "designated_doctor": r"대표\s*원장|원장\s*지정",
    "korean_only": r"내국인\s*전용|외국인\s*불가",
    "student_only": r"학생\s*전용|학생\s*한정",
    "app_pay_only": r"앱\s*결제\s*전용",
    "review_required": r"후기\s*필수|리뷰\s*필수",
}


def classify_unranked(option: dict, dictionary: Dictionary) -> ExtractedOption | None:
    name = option["name_raw"]
    text = str(option.get("title_raw") or "") + " " + name
    if re.search(r"필러\s*녹|녹이는\s*주사|히알라제", text):
        return None
    # A broad event headline can list several treatments. Never transfer its project
    # or brand to an unnamed option that might be an unrelated add-on.
    matched = dictionary.matches(name)
    if len(matched) != 1 or re.search(r"\+|패키지|결합|복합|무제한|년권|개월권", text):
        return None
    procedure = next(p for p in dictionary.procedures if p.id in matched)
    brands = [
        b for b in procedure.brands if any(a.casefold() in name.casefold() for a in b.aliases)
    ]
    brand = brands[0] if len(brands) == 1 else None
    sessions = re.fullmatch(r"(\d+)회(?:권)?", option.get("sessions_raw") or "")
    if not sessions:
        return None
    conditions = [key for key, pattern in CONDITIONS.items() if re.search(pattern, text)]
    return ExtractedOption(
        items=[
            Item(
                procedure_id=procedure.id,
                brand_id=brand.id if brand else None,
                tier=brand.tier if brand else "unknown",
                quantity=None,
                unit=None,
            )
        ],
        is_bundle=False,
        sessions=int(sessions[1]),
        price_from="부터" in text,
        vat=option.get("vat", "unknown"),
        conditions=conditions,
        extra_fees=[
            fee
            for fee, pattern in {
                "anesthesia": r"마취비\s*별도|수면마취\s*별도",
                "aftercare": r"관리비\s*별도",
                "consultation": r"상담비\s*별도",
            }.items()
            if re.search(pattern, text)
        ],
        confidence=1,
    )
