import re

from rapidfuzz.fuzz import ratio

from pipeline.config import Settings
from pipeline.db import connect


def normalize(text: str) -> str:
    return re.sub(r"[\s(),.-]", "", text).casefold()


def same_clinic(a: dict, b: dict) -> bool:
    # Conservative: exact normalized full address, including floor/unit. No fuzzy address merges.
    if not a["address_ko"] or normalize(a["address_ko"]) != normalize(b["address_ko"]):
        return False
    # Branch suffixes must be retained; a similar name at a shared medical building isn't enough.
    first, second = normalize(a["name_ko"]), normalize(b["name_ko"])
    return first == second and ratio(first, second) == 100


def merge_clinics(settings: Settings) -> dict:
    merged = 0
    with connect(settings.database) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM clinics WHERE merged_into IS NULL")]
        for index, target in enumerate(rows):
            if target.get("merged_into"):
                continue
            for duplicate in rows[index + 1 :]:
                if duplicate.get("merged_into") or not same_clinic(target, duplicate):
                    continue
                conn.execute(
                    "UPDATE events SET clinic_id=? WHERE clinic_id=?",
                    (target["id"], duplicate["id"]),
                )
                conn.execute(
                    "UPDATE clinic_sources SET clinic_id=? WHERE clinic_id=?",
                    (target["id"], duplicate["id"]),
                )
                conn.execute(
                    "UPDATE clinics SET merged_into=? WHERE id=?", (target["id"], duplicate["id"])
                )
                duplicate["merged_into"] = target["id"]
                merged += 1
    return {"merged": merged}
