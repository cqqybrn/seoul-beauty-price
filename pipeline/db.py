import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    path = path.resolve()
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    uri = path.as_uri() + ("?mode=ro" if readonly else "?mode=rwc")
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if readonly:
            conn.execute("PRAGMA query_only=ON")
        else:
            conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            yield conn
    finally:
        conn.close()


def migrate(path: Path, directory: Path) -> int:
    scripts = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not scripts:
        raise FileNotFoundError(f"No migrations in {directory}")
    applied = 0
    with connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.commit()
        for script in scripts:
            raw = script.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            previous = conn.execute(
                "SELECT sha256 FROM schema_migrations WHERE name=?", (script.name,)
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValueError(f"Applied migration was modified: {script.name}")
                continue
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + raw.decode("utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations VALUES "
                    "(?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                    (script.name, digest),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            applied += 1
    return applied
