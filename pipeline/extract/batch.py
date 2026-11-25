"""Explicit async Gemini batches: submit once, poll once per invocation, import by metadata ID.

Official API and installed SDK 3.3.0 signatures checked 2026-11-15.
No network retries, auto-function execution, blind polling loop, or submitted job duplication.
"""

import json
from contextlib import nullcontext
from datetime import datetime

from google import genai
from google.genai import types
from pydantic import ValidationError

from pipeline.budget import fail, reserve, settle
from pipeline.config import Settings
from pipeline.db import connect
from pipeline.dictionary import load_dictionary
from pipeline.extract.prompt import SYSTEM_PROMPT, extraction_input
from pipeline.extract.schema import ExtractedOption
from pipeline.validate import validate_extraction


def _client(settings: Settings, supplied):
    if supplied:
        return nullcontext(supplied)
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is required for the native Gemini batch API")
    return genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        http_options={"timeout": 90000, "retry_options": {"attempts": 1}},
    )


def submit_batch(settings: Settings, *, client=None) -> dict:
    if not settings.model_extract:
        raise ValueError("MODEL_EXTRACT is required")
    dictionary = load_dictionary(settings.dictionary_path)
    with connect(settings.database, readonly=True) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT o.*,e.title_raw FROM options o JOIN events e ON e.id=o.event_id "
                "WHERE o.active=1 AND e.status='active' AND NOT EXISTS "
                "(SELECT 1 FROM extractions x WHERE x.option_id=o.id "
                "AND x.content_hash=o.content_hash) "
                "AND NOT EXISTS (SELECT 1 FROM extraction_batch_items bi JOIN extraction_batches b "
                "ON b.name=bi.batch_name WHERE bi.option_id=o.id "
                "AND bi.content_hash=o.content_hash "
                "AND b.imported=0) ORDER BY o.id LIMIT ?",
                (settings.extraction_limit,),
            )
        ]
    if not rows:
        return {"submitted": 0}
    calls = []
    requests = []
    try:
        for row in rows:
            text = extraction_input(row, dictionary)
            calls.append(
                reserve(
                    settings,
                    settings.model_extract,
                    "batch_extract",
                    len((SYSTEM_PROMPT + text).encode()) + 4096,
                    settings.extraction_max_output_tokens,
                )
            )
            requests.append(
                types.InlinedRequest(
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=text)])],
                    metadata={"option_id": str(row["id"]), "content_hash": row["content_hash"]},
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=ExtractedOption,
                        tools=[],
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        max_output_tokens=settings.extraction_max_output_tokens,
                    ),
                )
            )
        with _client(settings, client) as api:
            job = api.batches.create(
                model=settings.model_extract,
                src=requests,
                config={"display_name": "seoul-price-extraction"},
            )
        if not job.name:
            raise ValueError("Batch API returned no durable job name")
        with connect(settings.database) as conn:
            state = getattr(job.state, "name", str(job.state))
            conn.execute(
                "INSERT INTO extraction_batches VALUES (?,?,?,?,0)",
                (
                    job.name,
                    settings.model_extract,
                    state,
                    datetime.now(settings.tz).isoformat(),
                ),
            )
            for row, call in zip(rows, calls, strict=True):
                conn.execute(
                    "INSERT INTO extraction_batch_items VALUES (?,?,?,?)",
                    (
                        job.name,
                        row["id"],
                        row["content_hash"],
                        call,
                    ),
                )
        return {"submitted": len(rows), "batch": job.name, "state": state}
    except Exception:
        for call in calls:
            fail(settings, call)
        raise


def poll_batch(settings: Settings, name: str, *, client=None) -> dict:
    with connect(settings.database, readonly=True) as conn:
        stored = conn.execute("SELECT * FROM extraction_batches WHERE name=?", (name,)).fetchone()
        items = {
            str(r["option_id"]): dict(r)
            for r in conn.execute(
                "SELECT bi.*,o.price_krw,o.content_hash AS current_hash "
                "FROM extraction_batch_items bi "
                "JOIN options o ON o.id=bi.option_id WHERE batch_name=?",
                (name,),
            )
        }
    if not stored:
        raise ValueError("Unknown extraction batch")
    if stored["imported"]:
        return {"batch": name, "imported": 0, "already_imported": True}
    dictionary = load_dictionary(settings.dictionary_path)
    with _client(settings, client) as api:
        job = api.batches.get(name=name)
        state = getattr(job.state, "name", str(job.state))
        with connect(settings.database) as conn:
            conn.execute("UPDATE extraction_batches SET state=? WHERE name=?", (state, name))
        if state != "JOB_STATE_SUCCEEDED":
            if state in {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}:
                for item in items.values():
                    fail(settings, item["call_id"])
                raise ValueError("Batch did not succeed; previous site retained")
            return {"batch": name, "state": state, "pending": True}
        if not job.dest:
            raise ValueError("Successful batch has no output destination")
        results = job.dest.inlined_responses
        if not results and job.dest.file_name:
            raw = api.files.download(file=job.dest.file_name)
            if not raw or len(raw) > 20 * 1024 * 1024:
                raise ValueError("Batch result file missing or exceeds size limit")
            results = []
            for line in raw.decode("utf-8").splitlines():
                data = json.loads(line)
                results.append(
                    types.InlinedResponse(
                        response=data.get("response"),
                        error=data.get("error"),
                        metadata=data.get("metadata") or {"option_id": str(data.get("key", ""))},
                    )
                )
    if not results:
        raise ValueError("No batch responses returned")
    seen = set()
    imported = 0
    for result in results:
        key = (result.metadata or {}).get("option_id", "")
        if key not in items or key in seen:
            raise ValueError("Batch output contains unknown or duplicate option metadata")
        seen.add(key)
        item = items[key]
        if result.error or not result.response:
            fail(settings, item["call_id"])
            raise ValueError("Batch contains failed extraction; do not publish partial results")
        response = result.response
        usage = response.usage_metadata
        if not usage or usage.prompt_token_count is None or usage.candidates_token_count is None:
            raise ValueError("Batch response is missing usage")
        settle(
            settings,
            item["call_id"],
            usage.prompt_token_count,
            usage.candidates_token_count + (getattr(usage, "thoughts_token_count", 0) or 0),
        )
        if item["current_hash"] != item["content_hash"]:
            continue  # Results for changed input are never attached to the new option state.
        parsed = None
        try:
            parsed = ExtractedOption.model_validate_json(response.text)
            reasons = validate_extraction(parsed, item["price_krw"], dictionary)
        except (ValidationError, ValueError):
            reasons = ["invalid_batch_schema"]
        with connect(settings.database) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO extractions(option_id,content_hash,model,extracted_json,"
                "confidence,valid,invalid_reasons,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    item["option_id"],
                    item["content_hash"],
                    stored["model"],
                    parsed.model_dump_json() if parsed else "{}",
                    parsed.confidence if parsed else 0,
                    int(not reasons),
                    json.dumps(reasons),
                    datetime.now(settings.tz).isoformat(),
                ),
            )
        imported += 1
    if seen != set(items):
        raise ValueError("Batch response count does not match submitted inputs")
    with connect(settings.database) as conn:
        conn.execute("UPDATE extraction_batches SET imported=1 WHERE name=?", (name,))
    return {"batch": name, "imported": imported, "state": state}
