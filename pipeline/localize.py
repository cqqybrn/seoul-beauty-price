"""Display-only Chinese translations, independent of prices and ranking facts."""

import hashlib
import json
import re
from datetime import datetime

from pipeline.config import Settings
from pipeline.db import connect


def text_hash(text: str) -> str:
    return hashlib.sha256(("zh-CN:v1:" + text).encode()).hexdigest()


def validate_translation(original: str, translated: str) -> str:
    if not isinstance(translated, str) or not 1 <= len(translated.strip()) <= 600:
        raise ValueError("Translation is empty or too long")
    translated = translated.strip()
    if re.search(r"[<>]|https?://|www\.", translated, re.I):
        raise ValueError("Translation must be plain text without links")
    if re.search(r"[가-힣]", translated):
        raise ValueError("Chinese translation still contains Korean text")
    # Never let the language layer silently change doses, sessions or tip models.
    if sorted(re.findall(r"\d+(?:\.\d+)?", original)) != sorted(
        re.findall(r"\d+(?:\.\d+)?", translated)
    ):
        raise ValueError("Translation changed source numbers")
    return translated


def save_translations(settings: Settings, originals: dict[str, str], results: list, model: str):
    if not isinstance(results, list) or len(results) != len(originals):
        raise ValueError("Translation response count mismatch")
    verified = {}
    for item in results:
        if not isinstance(item, dict) or set(item) != {"id", "zh"}:
            raise ValueError("Unexpected translation fields")
        identifier = item["id"]
        if identifier not in originals or identifier in verified:
            raise ValueError("Unknown or duplicate translation ID")
        verified[identifier] = validate_translation(originals[identifier], item["zh"])
    with connect(settings.database) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO localized_texts VALUES (?,?,?,?,?)",
            [
                (key, originals[key], value, model, datetime.now(settings.tz).isoformat())
                for key, value in verified.items()
            ],
        )


def translation_map(conn) -> dict[str, str]:
    return {r["source_hash"]: r["text_zh"] for r in conn.execute("SELECT * FROM localized_texts")}


def attach_translations(payload: dict, translations: dict[str, str]) -> dict:
    def get(text):
        return translations.get(text_hash(text or ""))

    for row in payload["offers"] + payload.get("raw_options", []):
        row["option_name_zh"] = get(row.get("option_name"))
        row["event_title_zh"] = get(row.get("event_title"))
        row["clinic_name_zh"] = get(row.get("clinic_name"))
    for row in payload["clinics"]:
        row["name_zh"] = get(row["name"])
    if payload.get("report"):
        for section in payload["report"]["sections"]:
            for row in section["entries"]:
                row["clinic_name_zh"] = get(row["clinic_name"])
    return payload


def parse_response(content: str) -> list:
    # Some compatible gateways add a JSON fence despite the explicit instruction.
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    result = json.loads(value)
    if not isinstance(result, list):
        raise ValueError("Translation response must be a list")
    return result
