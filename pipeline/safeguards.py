from datetime import date, timedelta

from pipeline.alerts import alert
from pipeline.config import Settings
from pipeline.db import connect


def source_volume_ok(settings: Settings, source: str, day: str, count: int) -> bool:
    start = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    with connect(settings.database, readonly=True) as conn:
        prior = conn.execute(
            "SELECT AVG(collected) FROM source_runs WHERE source=? AND date>=? AND date<? AND ok=1",
            (source, start, day),
        ).fetchone()[0]
    ok = count > 0 and (prior is None or count >= prior * 0.7)
    if not ok:
        alert(
            settings,
            "source_volume_drop",
            "Collection volume dropped; retained previous data",
            source,
        )
    return ok


def record_source_run(
    settings: Settings,
    source: str,
    day: str,
    *,
    ok: bool,
    discovered: int,
    collected: int,
    error: str | None = None,
) -> None:
    with connect(settings.database) as conn:
        conn.execute(
            "INSERT INTO source_runs(source,date,ok,discovered,collected,error) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(source,date) DO UPDATE SET ok=excluded.ok,discovered=excluded.discovered,"
            "collected=excluded.collected,error=excluded.error",
            (source, day, int(ok), discovered, collected, error),
        )


def update_absences(
    settings: Settings, source: str, day: str, present_ids: set[str], not_found_ids: set[str]
) -> int:
    """Call only after a complete healthy sitemap/collection, never a partial or blocked run."""
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    ended = 0
    with connect(settings.database) as conn:
        events = conn.execute(
            "SELECT id,source_event_id FROM events WHERE source=? AND status='active'", (source,)
        ).fetchall()
        for event in events:
            missing = event["source_event_id"] not in present_ids
            failed = event["source_event_id"] in not_found_ids
            if not missing and not failed:
                conn.execute(
                    "DELETE FROM event_absences WHERE event_id=? AND date=?", (event["id"], day)
                )
                continue
            conn.execute(
                "INSERT OR REPLACE INTO event_absences VALUES (?,?,?)",
                (
                    event["id"],
                    day,
                    "http_404" if failed else "sitemap_missing",
                ),
            )
            prior = conn.execute(
                "SELECT 1 FROM event_absences WHERE event_id=? AND date=?", (event["id"], yesterday)
            ).fetchone()
            if prior:
                conn.execute("UPDATE events SET status='ended' WHERE id=?", (event["id"],))
                ended += 1
    return ended


def stale_sources(settings: Settings, day: str) -> dict[str, str]:
    stale = {}
    with connect(settings.database, readonly=True) as conn:
        for source in settings.source_names.split(","):
            days = [(date.fromisoformat(day) - timedelta(days=i)).isoformat() for i in range(3)]
            failures = conn.execute(
                "SELECT COUNT(*) FROM source_runs WHERE source=? AND date IN (?,?,?) AND ok=0",
                (source, *days),
            ).fetchone()[0]
            if failures == 3:
                seen = conn.execute(
                    "SELECT MAX(last_seen) FROM events WHERE source=?", (source,)
                ).fetchone()[0]
                stale[source] = seen or "尚未成功采集"
    return stale
