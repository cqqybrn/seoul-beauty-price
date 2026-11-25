import json
from datetime import datetime

from google import genai
from google.genai import types
from pydantic import ValidationError

from pipeline.budget import BudgetExceeded, fail, reserve, settle
from pipeline.config import Settings
from pipeline.db import connect
from pipeline.dictionary import load_dictionary
from pipeline.extract.prompt import SYSTEM_PROMPT, extraction_input
from pipeline.extract.schema import ExtractedOption
from pipeline.validate import validate_extraction


def google_extract(settings: Settings, model: str, text: str) -> tuple[ExtractedOption, int, int]:
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is required for the tool-free extraction provider")
    with genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        http_options={
            "timeout": 90000,
            "retry_options": {"attempts": 1},
        },
    ) as client:
        response = client.models.generate_content(
            model=model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ExtractedOption,
                tools=[],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                max_output_tokens=settings.extraction_max_output_tokens,
            ),
        )
    usage = response.usage_metadata
    if not usage or usage.prompt_token_count is None or usage.candidates_token_count is None:
        raise ValueError("Extraction returned no auditable token usage")
    # Include reasoning tokens in output billing.
    output = usage.candidates_token_count + (getattr(usage, "thoughts_token_count", 0) or 0)
    return ExtractedOption.model_validate_json(response.text), usage.prompt_token_count, output


def extract_pending(settings: Settings, *, invoke=None) -> dict:
    if not settings.model_extract or not settings.model_extract_retry:
        raise ValueError("MODEL_EXTRACT and MODEL_EXTRACT_RETRY must be explicitly configured")
    dictionary = load_dictionary(settings.dictionary_path)
    with connect(settings.database, readonly=True) as conn:
        pending = [
            dict(r)
            for r in conn.execute(
                "SELECT o.*,e.title_raw FROM options o JOIN events e ON e.id=o.event_id "
                "WHERE o.active=1 AND e.status='active' AND NOT EXISTS "
                "(SELECT 1 FROM extractions x WHERE x.option_id=o.id "
                "AND x.content_hash=o.content_hash AND x.valid=1) "
                "AND NOT EXISTS (SELECT 1 FROM extractions r WHERE r.option_id=o.id "
                "AND r.content_hash=o.content_hash AND r.model=?) "
                "ORDER BY o.id LIMIT ?",
                (settings.model_extract_retry, settings.extraction_limit),
            )
        ]
    invoke = invoke or (lambda model, text: google_extract(settings, model, text))
    valid = 0
    for row in pending:
        text = extraction_input(row, dictionary)
        passed = False
        with connect(settings.database, readonly=True) as conn:
            tried_cheap = conn.execute(
                "SELECT 1 FROM extractions WHERE option_id=? AND content_hash=? AND model=?",
                (row["id"], row["content_hash"], settings.model_extract),
            ).fetchone()
        models = (
            (settings.model_extract_retry,)
            if tried_cheap
            else (settings.model_extract, settings.model_extract_retry)
        )
        for model in models:
            call = reserve(
                settings,
                model,
                "extract",
                len((SYSTEM_PROMPT + text).encode()) + 4096,
                settings.extraction_max_output_tokens,
            )
            result = None
            try:
                result, inputs, outputs = invoke(model, text)
                settle(settings, call, inputs, outputs)
                reasons = validate_extraction(result, row["price_krw"], dictionary)
            except (ValidationError, ValueError) as exc:
                fail(settings, call)
                reasons = [type(exc).__name__]
            except Exception:
                fail(settings, call)
                raise
            with connect(settings.database) as conn:
                conn.execute(
                    "INSERT INTO extractions (option_id,content_hash,model,extracted_json,"
                    "confidence,valid,invalid_reasons,created_at) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(option_id,content_hash,model) DO UPDATE SET "
                    "extracted_json=excluded.extracted_json,confidence=excluded.confidence,"
                    "valid=excluded.valid,invalid_reasons=excluded.invalid_reasons",
                    (
                        row["id"],
                        row["content_hash"],
                        model,
                        result.model_dump_json() if result else "{}",
                        result.confidence if result else 0,
                        int(not reasons),
                        json.dumps(reasons),
                        datetime.now(settings.tz).isoformat(),
                    ),
                )
            if not reasons:
                passed = True
                break
        valid += int(passed)
    if pending and valid / len(pending) < 0.85:
        raise ValueError("Extraction success below 85%; calculation and publication stopped")
    with connect(settings.database, readonly=True) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM options o JOIN events e ON e.id=o.event_id WHERE "
            "o.active=1 AND e.status='active' AND NOT EXISTS (SELECT 1 FROM extractions x "
            "WHERE x.option_id=o.id AND x.content_hash=o.content_hash)"
        ).fetchone()[0]
        total, successful = conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(EXISTS (SELECT 1 FROM extractions x "
            "WHERE x.option_id=o.id AND x.content_hash=o.content_hash AND x.valid=1)),0) "
            "FROM options o JOIN events e ON e.id=o.event_id WHERE o.active=1 AND e.status='active'"
        ).fetchone()
    if remaining:
        raise BudgetExceeded("Extraction work remains; retain previous published site")
    if total and successful / total < 0.85:
        raise ValueError("Current extraction success below 85%; calculation remains blocked")
    return {"processed": len(pending), "valid": valid}
