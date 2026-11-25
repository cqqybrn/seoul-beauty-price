import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from pipeline.config import Settings
from pipeline.db import connect
from pipeline.dictionary import Dictionary
from pipeline.sources.babitalk import BabitalkAdapter
from pipeline.sources.base import EventFacts
from pipeline.sources.policy import permitted_url
from pipeline.sources.yeoshin import YeoshinAdapter


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_in_scope(facts: EventFacts, dictionary: Dictionary) -> bool:
    seoul = re.match(r"^(서울|서울특별시)(?:\s|$)", facts.clinic_address.strip())
    return bool(seoul and dictionary.matches(facts.title_raw, *(o.name_raw for o in facts.options)))


def ingest_facts(
    settings: Settings,
    facts: EventFacts,
    dictionary: Dictionary,
    *,
    observed_at: datetime | None = None,
) -> dict:
    """Atomic idempotent import of verified fact projections, not arbitrary raw page content."""
    policy = BabitalkAdapter.policy if facts.source == "babitalk" else YeoshinAdapter.policy
    if not permitted_url(facts.url, policy):
        raise ValueError("Event URL outside source policy")
    if not is_in_scope(facts, dictionary):
        return {"events": 0, "options": 0, "skipped": 1}
    if len({o.source_option_id for o in facts.options}) != len(facts.options):
        raise ValueError("Duplicate source option IDs")
    when = observed_at or datetime.now(settings.tz)
    if when.tzinfo is None:
        raise ValueError("observed_at must be timezone aware")
    when = when.astimezone(settings.tz)
    day = when.date().isoformat()
    # No full HTML, review text, nicknames, photographs or medical-user content are stored.
    snapshot = canonical_json(facts.model_dump()).encode("utf-8")
    digest = hashlib.sha256(snapshot).hexdigest()
    target = settings.snapshot_dir / facts.source / f"{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(snapshot)
        temporary.replace(target)
    with connect(settings.database) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO clinics (name_ko, address_ko, district, area, "
            "foreign_patient_registered) VALUES (?, ?, ?, ?, ?)",
            (
                facts.clinic_name,
                facts.clinic_address,
                facts.district,
                facts.area,
                facts.foreign_patient_registered,
            ),
        )
        clinic_id = conn.execute(
            "SELECT id FROM clinics WHERE name_ko=? AND address_ko=?",
            (facts.clinic_name, facts.clinic_address),
        ).fetchone()[0]
        if facts.source_clinic_id and facts.clinic_url:
            conn.execute(
                "INSERT INTO clinic_sources VALUES (?, ?, ?, ?) "
                "ON CONFLICT(source, source_clinic_id) DO UPDATE SET "
                "clinic_id=excluded.clinic_id, url=excluded.url",
                (clinic_id, facts.source, facts.source_clinic_id, facts.clinic_url),
            )
        conn.execute(
            "INSERT INTO events (source, source_event_id, url, clinic_id, title_raw, "
            "first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, source_event_id) DO UPDATE SET "
            "url=excluded.url, clinic_id=excluded.clinic_id, title_raw=excluded.title_raw, "
            "last_seen=excluded.last_seen, status='active'",
            (facts.source, facts.source_event_id, facts.url, clinic_id, facts.title_raw, day, day),
        )
        event_id = conn.execute(
            "SELECT id FROM events WHERE source=? AND source_event_id=?",
            (facts.source, facts.source_event_id),
        ).fetchone()[0]
        conn.execute("UPDATE options SET active=0 WHERE event_id=?", (event_id,))
        for option in facts.options:
            # Extraction also depends on event title and tax/fee markers, not just price/name.
            hash_input = {
                **option.model_dump(),
                "title_raw": facts.title_raw,
                "vat": facts.vat,
                "extra_fees": facts.extra_fees,
            }
            content_hash = hashlib.sha256(canonical_json(hash_input).encode()).hexdigest()
            conn.execute(
                "INSERT INTO options (event_id, source_option_id, name_raw, sessions_raw, "
                "list_price_krw, price_krw, coupon_price_krw, content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_id, source_option_id) "
                "DO UPDATE SET name_raw=excluded.name_raw, sessions_raw=excluded.sessions_raw, "
                "list_price_krw=excluded.list_price_krw, price_krw=excluded.price_krw, "
                "coupon_price_krw=excluded.coupon_price_krw, "
                "content_hash=excluded.content_hash, active=1",
                (
                    event_id,
                    option.source_option_id,
                    option.name_raw,
                    option.sessions_raw,
                    option.list_price_krw,
                    option.price_krw,
                    option.coupon_price_krw,
                    content_hash,
                ),
            )
            option_id = conn.execute(
                "SELECT id FROM options WHERE event_id=? AND source_option_id=?",
                (event_id, option.source_option_id),
            ).fetchone()[0]
            conn.execute(
                "UPDATE options SET vat=?, extra_fees=? WHERE id=?",
                (facts.vat, canonical_json(facts.extra_fees), option_id),
            )
            conn.execute(
                "INSERT INTO option_history VALUES (?, ?, ?, ?) "
                "ON CONFLICT(option_id, observed_date) DO UPDATE SET "
                "price_krw=excluded.price_krw, coupon_price_krw=excluded.coupon_price_krw",
                (option_id, day, option.price_krw, option.coupon_price_krw),
            )
        conn.execute(
            "INSERT OR IGNORE INTO raw_snapshots "
            "(source, url, fetched_at, http_status, body_path, sha256) VALUES (?, ?, ?, 200, ?, ?)",
            (facts.source, facts.url, when.isoformat(), str(target.resolve()), digest),
        )
    return {"events": 1, "options": len(facts.options), "skipped": 0}


def export_unlabeled(database: Path, destination: Path, limit: int = 100) -> int:
    with connect(database, readonly=True) as conn:
        rows = conn.execute(
            "SELECT o.id AS option_id, e.source, e.url, e.title_raw, o.name_raw, "
            "o.sessions_raw, o.price_krw, o.coupon_price_krw, o.content_hash "
            "FROM options o JOIN events e ON e.id=o.event_id "
            "WHERE o.active=1 AND e.status='active' ORDER BY e.source, e.id, o.id LIMIT ?",
            (limit,),
        ).fetchall()
    if len(rows) < limit:
        raise ValueError(f"Need {limit} real options for annotation; only {len(rows)} available")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(canonical_json(dict(row)) for row in rows) + "\n"
    destination.write_text(content, encoding="utf-8")
    return len(rows)
