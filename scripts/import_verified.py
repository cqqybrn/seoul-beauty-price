"""Import bounded real fact projections, normalize only explicit doses, refresh local preview.

This does not assert M2 golden accuracy or enable the production collector.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from pipeline.config import Settings
from pipeline.db import connect, migrate
from pipeline.dictionary import load_dictionary
from pipeline.extract.explicit import explicit_dose
from pipeline.extract.lexical import classify_unranked
from pipeline.ingest import ingest_facts
from pipeline.pricing import calculate
from pipeline.publish import site_payload, update_exchange_rate
from pipeline.sources.base import EventFacts
from pipeline.validate import validate_extraction


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-draft", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    migrate(settings.database, settings.migrations_dir)
    dictionary = load_dictionary(settings.dictionary_path)
    counts = {"events": 0, "options": 0, "normalized": 0, "pending_ai": 0, "skipped": 0}
    for file in sorted(Path("data/verified/yeoshin").glob("*.json")):
        if file.name == "summary.json":
            continue
        facts = EventFacts.model_validate_json(file.read_text(encoding="utf-8"))
        result = ingest_facts(settings, facts, dictionary)
        for field in ("events", "options", "skipped"):
            counts[field] += result[field]
    with connect(settings.database) as conn:
        rows = conn.execute(
            "SELECT o.*,e.title_raw FROM options o JOIN events e ON e.id=o.event_id "
            "WHERE e.source='yeoshin' AND o.active=1 AND e.status='active'"
        ).fetchall()
        for row in rows:
            result = explicit_dose(dict(row), dictionary)
            model = "rule:explicit-dose-v1"
            if result is None:
                result = classify_unranked(dict(row), dictionary)
                model = "rule:lexical-unranked-v1"
            if result is None or validate_extraction(result, row["price_krw"], dictionary):
                conn.execute(
                    "UPDATE extractions SET valid=0 WHERE option_id=? AND content_hash=? "
                    "AND model LIKE 'rule:%'",
                    (row["id"], row["content_hash"]),
                )
                counts["pending_ai"] += 1
                continue
            previous = conn.execute(
                "SELECT extracted_json FROM extractions WHERE option_id=? AND content_hash=? "
                "AND valid=1 ORDER BY id DESC LIMIT 1",
                (row["id"], row["content_hash"]),
            ).fetchone()
            if previous and previous[0] != result.model_dump_json():
                # Retain past facts/IDs for audit but exclude the old rule projection from
                # the current view. This applies only to this manual preview's rule outputs.
                conn.execute(
                    "UPDATE offer_items SET content_hash=NULL WHERE option_id=? AND content_hash=?",
                    (row["id"], row["content_hash"]),
                )
            conn.execute(
                "UPDATE extractions SET valid=0 WHERE option_id=? AND content_hash=? "
                "AND model LIKE 'rule:%'",
                (row["id"], row["content_hash"]),
            )
            conn.execute(
                "INSERT INTO extractions(option_id,content_hash,model,extracted_json,"
                "confidence,valid,invalid_reasons,created_at) VALUES (?,?,?,?,1,1,'[]',?) "
                "ON CONFLICT(option_id,content_hash,model) DO UPDATE SET "
                "extracted_json=excluded.extracted_json,valid=1,created_at=excluded.created_at",
                (
                    row["id"],
                    row["content_hash"],
                    model,
                    result.model_dump_json(),
                    datetime.now(settings.tz).isoformat(),
                ),
            )
            counts["normalized"] += 1
    calculate(settings)
    update_exchange_rate(settings)
    payload = site_payload(settings, include_draft=args.include_draft)
    payload["report_preview"] = args.include_draft
    # Only allowlisted display facts; API credentials never enter this generated file.
    destination = settings.web_dir / "src/data/generated.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                **counts,
                "display_offers": len(payload["offers"]),
                "clinics": len(payload["clinics"]),
                "mode": "verified_preview",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
