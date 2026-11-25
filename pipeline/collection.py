import json
import os
import subprocess
import sys
import uuid
from datetime import datetime

from pipeline.alerts import alert
from pipeline.config import Settings
from pipeline.db import connect
from pipeline.dictionary import load_dictionary
from pipeline.ingest import ingest_facts
from pipeline.safeguards import record_source_run, source_volume_ok, update_absences
from pipeline.sources.base import EventFacts, SourceNotReady


def collect_sources(settings: Settings, mode: str) -> dict:
    _ = settings.user_agent
    if mode not in {"discover", "collect"}:
        raise ValueError("Invalid collection stage")
    now = datetime.now(settings.tz)
    if settings.crawl_require_kst_window and not (
        settings.crawl_window_start <= now.hour < settings.crawl_window_end
    ):
        raise SourceNotReady("Live collection must run in the configured KST early-morning window")
    day = now.date().isoformat()
    dictionary = load_dictionary(settings.dictionary_path)
    total = 0
    failures = []
    sources = settings.source_names.split(",")
    if any(source not in {"babitalk", "yeoshin"} for source in sources):
        raise ValueError("Only Babitalk and Yeoshin can be collected")
    for source in sources:
        stage = settings.database.parent / "staging" / uuid.uuid4().hex
        stage.mkdir(parents=True)
        env = os.environ.copy()
        env["PIPELINE_DATABASE"] = str(settings.database.resolve())
        env["PIPELINE_SITE_URL"] = settings.site_url
        env["PIPELINE_CRAWL_LIMIT"] = str(settings.crawl_limit)
        env["PIPELINE_CRAWL_REQUIRE_KST_WINDOW"] = str(settings.crawl_require_kst_window)
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pipeline.sources.crawl", source, mode, str(stage.resolve())],
            env=env,
            capture_output=True,
            timeout=4 * 3600,
        )
        path = stage / f"{source}-{mode}-result.json"
        summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        healthy = result.returncode == 0 and summary.get("ok", False)
        if mode == "discover":
            healthy = healthy and summary.get("discovered", 0) > 0
        if mode == "collect":
            healthy = healthy and source_volume_ok(
                settings, source, day, summary.get("collected", 0)
            )
        if not healthy:
            failures.append(source)
            alert(settings, "collection_failed", "Source failed; old data retained", source)
            record_source_run(
                settings,
                source,
                day,
                ok=False,
                discovered=summary.get("discovered", 0),
                collected=summary.get("collected", 0),
                error="collection_failed",
            )
            continue
        if mode == "collect":
            # Source-level gate runs before any events/options mutation.
            for file in sorted(stage.glob(f"{source}-*.json")):
                if file.name.endswith("-result.json"):
                    continue
                facts = EventFacts.model_validate_json(file.read_text(encoding="utf-8"))
                counts = ingest_facts(settings, facts, dictionary)
                total += counts["options"]
                with connect(settings.database) as conn:
                    conn.execute(
                        "UPDATE discovered_urls SET last_fetched=?,fetched_lastmod=lastmod,"
                        "last_outcome='ok' WHERE source=? AND url=?",
                        (now.isoformat(), source, facts.url),
                    )
            with connect(settings.database, readonly=True) as conn:
                present = {
                    row[0].rstrip("/").split("/")[-1]
                    for row in conn.execute(
                        "SELECT url FROM discovered_urls WHERE source=? AND last_seen=?",
                        (source, day),
                    )
                }
            # Only current complete discovery can support absence decisions.
            if present:
                update_absences(
                    settings, source, day, present, set(summary.get("not_found_ids", []))
                )
            record_source_run(
                settings,
                source,
                day,
                ok=True,
                discovered=len(present),
                collected=summary["collected"],
            )
        else:
            total += summary["discovered"]
    if len(failures) == len(sources):
        raise SourceNotReady("All sources failed; downstream stages stopped and old site retained")
    return {"processed": total, "failed_sources": failures}
