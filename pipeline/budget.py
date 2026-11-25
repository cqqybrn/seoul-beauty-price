import uuid
from datetime import datetime
from decimal import Decimal

from pipeline.config import Settings
from pipeline.db import connect


class BudgetExceeded(RuntimeError):
    pass


def cost(settings: Settings, input_tokens: int, output_tokens: int) -> Decimal:
    if settings.ai_input_usd_per_million is None or settings.ai_output_usd_per_million is None:
        raise ValueError("Configure verified provider input/output token prices before paid jobs")
    return (
        Decimal(input_tokens) * settings.ai_input_usd_per_million
        + Decimal(output_tokens) * settings.ai_output_usd_per_million
    ) / 1_000_000


def reserve(
    settings: Settings, model: str, purpose: str, input_bound: int, output_bound: int
) -> str:
    maximum = cost(settings, input_bound, output_bound)
    now = datetime.now(settings.tz)
    with connect(settings.database) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT reserved_usd, actual_usd FROM ai_calls WHERE date=?", (now.date().isoformat(),)
        ).fetchall()
        spent = sum((Decimal(r[1] if r[1] is not None else r[0]) for r in rows), Decimal(0))
        if spent + maximum > settings.daily_ai_budget_usd:
            raise BudgetExceeded("Daily AI budget exhausted; pending work deferred until tomorrow")
        call_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO ai_calls (id,date,purpose,model,reserved_usd,state,created_at) "
            "VALUES (?,?,?,?,?,'reserved',?)",
            (call_id, now.date().isoformat(), purpose, model, str(maximum), now.isoformat()),
        )
    return call_id


def settle(settings: Settings, call_id: str, input_tokens: int, output_tokens: int) -> None:
    actual = cost(settings, input_tokens, output_tokens)
    with connect(settings.database) as conn:
        conn.execute(
            "UPDATE ai_calls SET actual_usd=?,input_tokens=?,output_tokens=?,state='complete' "
            "WHERE id=? AND state='reserved'",
            (str(actual), input_tokens, output_tokens, call_id),
        )


def fail(settings: Settings, call_id: str) -> None:
    # Interrupted calls may be charged: keep the reservation, never refund blindly.
    with connect(settings.database) as conn:
        conn.execute("UPDATE ai_calls SET state='failed' WHERE id=?", (call_id,))
