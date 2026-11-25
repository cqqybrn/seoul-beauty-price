import json
import re
import sqlite3
import time
from datetime import date as calendar_date
from datetime import datetime

from pipeline.analyst.report_schema import Report
from pipeline.config import Settings
from pipeline.db import connect
from pipeline.dictionary import load_dictionary

VIEWS = frozenset({"v_offers", "v_bucket_stats", "v_price_changes"})
FUNCTIONS = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "round",
        "abs",
        "coalesce",
        "ifnull",
        "nullif",
        "length",
        "lower",
        "upper",
        "lag",
        "lead",
        "row_number",
        "rank",
        "dense_rank",
        "json_extract",
        "json_array_length",
        "substr",
        "typeof",
    }
)


class AnalystTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.submitted = False

    def run_sql(self, query: str) -> list[dict]:
        if len(query) > 10000 or not re.match(r"^\s*SELECT\b", query, re.I):
            raise ValueError("Only a single SELECT statement is permitted")
        if ";" in query or "--" in query or "/*" in query:
            raise ValueError("SQL comments and multiple statements are not permitted")
        deadline = time.monotonic() + 5

        def authorize(action, arg1, arg2, database, origin):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                allowed = database == "main" and (arg1 in VIEWS or origin in VIEWS)
                return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        with connect(self.settings.database, readonly=True) as conn:
            conn.set_authorizer(authorize)
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            try:
                cursor = conn.execute(query)
                return [dict(row) for row in cursor.fetchmany(200)]
            except sqlite3.Error:
                raise ValueError(
                    "SQL rejected by read-only view sandbox or query deadline"
                ) from None
            finally:
                conn.set_authorizer(None)
                conn.set_progress_handler(None, 0)

    def get_previous_report(self, date: str) -> dict | None:
        day = calendar_date.fromisoformat(date).isoformat()
        with connect(self.settings.database, readonly=True) as conn:
            row = conn.execute(
                "SELECT report_json FROM daily_reports WHERE date=? AND published=1", (day,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def propose_dictionary_entry(self, term: str, suggested_procedure: str, reason: str) -> dict:
        if not 1 <= len(term) <= 80 or not 1 <= len(reason) <= 300:
            raise ValueError("Invalid dictionary proposal")
        if any(c in term for c in ("<", ">", "\n", "\r")):
            raise ValueError("Invalid dictionary term")
        day = datetime.now(self.settings.tz).date().isoformat()
        # Count evidence deterministically, never accept a model-supplied count.
        with connect(self.settings.database) as conn:
            rows = conn.execute("SELECT id,name_raw FROM options WHERE active=1").fetchall()
            evidence = [r["id"] for r in rows if term.casefold() in r["name_raw"].casefold()]
            conn.execute(
                "INSERT INTO dictionary_proposals"
                "(date,term_raw,suggested_procedure,reason,seen_count) "
                "VALUES (?,?,?,?,?) ON CONFLICT(date,term_raw,suggested_procedure) DO UPDATE SET "
                "reason=excluded.reason,seen_count=excluded.seen_count",
                (day, term, suggested_procedure, reason, len(evidence)),
            )
            proposal = conn.execute(
                "SELECT id FROM dictionary_proposals WHERE date=? AND term_raw=? "
                "AND suggested_procedure=?",
                (day, term, suggested_procedure),
            ).fetchone()[0]
            for option_id in evidence:
                conn.execute(
                    "INSERT OR IGNORE INTO proposal_evidence VALUES (?,?)", (proposal, option_id)
                )
        return {
            "proposal_id": proposal,
            "verified_option_count": len(evidence),
            "status": "pending",
        }

    def submit_report(self, report: dict) -> dict:
        parsed = Report.model_validate(report)
        if parsed.date != datetime.now(self.settings.tz).date():
            raise ValueError("Report date must be today's KST date")
        with connect(self.settings.database, readonly=True) as conn:
            for item in [*parsed.price_drops, *parsed.new_offers, *parsed.anomalies]:
                if not conn.execute(
                    "SELECT 1 FROM v_offers WHERE offer_item_id=?", (item.offer_item_id,)
                ).fetchone():
                    raise ValueError("Report references nonexistent or inactive offer ID")
            for item in parsed.bucket_notes:
                if not conn.execute(
                    "SELECT 1 FROM bucket_stats WHERE date=? AND bucket_key=?",
                    (parsed.date.isoformat(), item.bucket_key),
                ).fetchone():
                    raise ValueError("Report references nonexistent bucket")
        with connect(self.settings.database) as conn:
            conn.execute(
                "INSERT INTO daily_reports VALUES (?,?,0) ON CONFLICT(date) DO UPDATE SET "
                "report_json=excluded.report_json,published=0",
                (parsed.date.isoformat(), parsed.model_dump_json()),
            )
        self.submitted = True
        return {"accepted": True, "date": parsed.date.isoformat()}

    def invoke(self, name: str, arguments: dict):
        allowed = {
            "run_sql": {"query"},
            "get_previous_report": {"date"},
            "propose_dictionary_entry": {"term", "suggested_procedure", "reason"},
            "submit_report": {"report"},
        }
        if name not in allowed or set(arguments) != allowed[name]:
            raise ValueError("Unknown tool or invalid arguments")
        if name != "submit_report" and any(not isinstance(v, str) for v in arguments.values()):
            raise ValueError("Tool arguments must be strings")
        return getattr(self, name)(**arguments)


def apply_dictionary_proposals(settings: Settings) -> int:
    import yaml

    dictionary = load_dictionary(settings.dictionary_path)
    by_id = {p.id: p for p in dictionary.procedures}
    with connect(settings.database, readonly=True) as conn:
        rows = conn.execute(
            "SELECT p.term_raw,p.suggested_procedure,COUNT(DISTINCT e.option_id) AS n "
            "FROM dictionary_proposals p JOIN proposal_evidence e ON e.proposal_id=p.id "
            "WHERE p.status='pending' GROUP BY p.term_raw,p.suggested_procedure HAVING n>20"
        ).fetchall()
    applied = []
    for row in rows:
        target = by_id.get(row["suggested_procedure"])
        if not target:
            continue
        # Avoid adding broad terms already matching a different project.
        if any(p.id != target.id and row["term_raw"] in p.aliases for p in dictionary.procedures):
            continue
        if row["term_raw"] not in target.aliases:
            target.aliases.append(row["term_raw"])
        applied.append((row["term_raw"], target.id))
    if applied:
        temporary = settings.dictionary_path.with_suffix(".yaml.tmp")
        temporary.write_text(
            yaml.safe_dump(dictionary.model_dump(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        temporary.replace(settings.dictionary_path)
        with connect(settings.database) as conn:
            for term, procedure in applied:
                conn.execute(
                    "UPDATE dictionary_proposals SET status='applied' "
                    "WHERE term_raw=? AND suggested_procedure=?",
                    (term, procedure),
                )
    return len(applied)
