import json
import uuid
from collections.abc import Callable
from datetime import datetime

from pipeline.config import Settings
from pipeline.db import connect, migrate
from pipeline.dictionary import load_dictionary

STEPS = ("discover", "collect", "prefilter", "extract", "validate", "calculate", "build", "analyst")


def run_step(settings: Settings, step: str, *, run_id: str, live: bool = False) -> dict:
    started = datetime.now(settings.tz).isoformat()
    with connect(settings.database) as conn:
        conn.execute(
            "INSERT INTO run_log (run_id, step, started_at) VALUES (?, ?, ?)",
            (run_id, step, started),
        )
    try:
        counts = _execute(settings, step, live)
    except Exception as exc:
        with connect(settings.database) as conn:
            conn.execute(
                "UPDATE run_log SET finished_at=?, ok=0, error=? WHERE run_id=? AND step=?",
                (datetime.now(settings.tz).isoformat(), type(exc).__name__, run_id, step),
            )
        raise
    with connect(settings.database) as conn:
        conn.execute(
            "UPDATE run_log SET finished_at=?, ok=1, counts_json=? WHERE run_id=? AND step=?",
            (datetime.now(settings.tz).isoformat(), json.dumps(counts), run_id, step),
        )
    return counts


def _execute(settings: Settings, step: str, live: bool) -> dict:
    if not live:
        return {"mode": "scaffold", "processed": 0, "implemented": False}
    if step in {"discover", "collect"}:
        from pipeline.collection import collect_sources

        return collect_sources(settings, step)
    if step == "prefilter":
        from pipeline.clinics import merge_clinics

        return merge_clinics(settings)
    if step == "extract":
        from pipeline.extract.run import extract_pending

        return extract_pending(settings)
    if step == "validate":
        from pipeline.extract.schema import ExtractedOption
        from pipeline.validate import validate_extraction

        dictionary = load_dictionary(settings.dictionary_path)
        with connect(settings.database) as conn:
            rows = conn.execute(
                "SELECT x.id,x.extracted_json,o.price_krw FROM extractions x JOIN options o "
                "ON o.id=x.option_id WHERE x.valid=1 AND x.content_hash=o.content_hash"
            ).fetchall()
            for row in rows:
                reasons = validate_extraction(
                    ExtractedOption.model_validate_json(row["extracted_json"]),
                    row["price_krw"],
                    dictionary,
                )
                if reasons:
                    raise ValueError("Validation gate failed; retain prior publication")
        return {"validated": len(rows)}
    if step == "calculate":
        from pipeline.pricing import calculate

        return calculate(settings)
    if step == "build":
        from pipeline.publish import build_site, update_exchange_rate

        update_exchange_rate(settings)
        return build_site(settings)
    if step == "analyst":
        from pipeline.analyst.loop import analyze
        from pipeline.analyst.tools import apply_dictionary_proposals
        from pipeline.publish import build_site

        result = analyze(settings)
        build_site(settings, include_draft=True)
        result["aliases_applied"] = apply_dictionary_proposals(settings)
        return result
    raise ValueError("Unknown step")


def run(
    settings: Settings,
    *,
    step: str | None = None,
    live: bool = False,
    emit: Callable[[dict], None] | None = None,
) -> str:
    if step is not None and step not in STEPS:
        raise ValueError(f"Unknown step: {step}")
    migrate(settings.database, settings.migrations_dir)
    load_dictionary(settings.dictionary_path)
    run_id = uuid.uuid4().hex
    from pipeline.alerts import alert, heartbeat, send_pending

    if live:
        heartbeat(settings, "/start")
    try:
        for name in (step,) if step else STEPS:
            counts = run_step(settings, name, run_id=run_id, live=live)
            if emit:
                emit({"run_id": run_id, "step": name, "ok": True, **counts})
    except Exception:
        if live:
            alert(
                settings,
                "pipeline_failed",
                "Pipeline stopped; previous published artifacts retained",
            )
            heartbeat(settings, "/fail")
            send_pending(settings)
        raise
    if live:
        heartbeat(settings)
        send_pending(settings)
    return run_id
