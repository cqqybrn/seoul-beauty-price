import json
from datetime import datetime
from decimal import Decimal

from pipeline.config import Settings
from pipeline.db import connect
from pipeline.dictionary import load_dictionary
from pipeline.extract.schema import ExtractedOption
from pipeline.validate import validate_extraction

RESTRICTED = frozenset({"first_visit", "korean_only", "student_only"})


def unit_price(
    price: int, result: ExtractedOption, quantity: float | None, *, sitewide_vat: bool = False
) -> Decimal | None:
    if result.is_bundle or result.price_from or quantity is None:
        return None
    if result.vat == "unknown" and not sitewide_vat:
        return None
    multiplier = Decimal("1.1") if result.vat == "excluded" else Decimal(1)
    return Decimal(price) * multiplier / result.sessions / Decimal(str(quantity))


def percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("Empty distribution")
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def label_price(value: float | None, stats: dict | None) -> str:
    if value is None or stats is None or stats["n"] < 10:
        return "unranked"
    if value < max(stats["p5"], stats["median"] * 0.5):
        return "anomaly_low"
    if value <= stats["p25"]:
        return "cheap"
    if value >= stats["p75"]:
        return "expensive"
    return "normal"


def calculate(settings: Settings) -> dict:
    dictionary = load_dictionary(settings.dictionary_path)
    day = datetime.now(settings.tz).date().isoformat()
    with connect(settings.database) as conn:
        rows = conn.execute(
            "SELECT o.*,e.source,x.extracted_json FROM options o JOIN events e ON e.id=o.event_id "
            "JOIN extractions x ON x.id=(SELECT MAX(id) FROM extractions z WHERE z.option_id=o.id "
            "AND z.content_hash=o.content_hash AND z.valid=1) "
            "WHERE o.active=1 AND e.status='active'"
        ).fetchall()
        for row in rows:
            result = ExtractedOption.model_validate_json(row["extracted_json"])
            reasons = validate_extraction(result, row["price_krw"], dictionary)
            if reasons:
                raise ValueError("Stored extraction fails validation; calculation aborted")
            existing = conn.execute(
                "SELECT id,content_hash FROM offer_items WHERE option_id=? "
                "AND content_hash=? ORDER BY id",
                (row["id"], row["content_hash"]),
            ).fetchall()
            # IDs persist for unchanged extraction, so historical reports remain resolvable.
            if existing and all(r["content_hash"] == row["content_hash"] for r in existing):
                continue
            # Keep old IDs for historical report rendering; current view filters by hash.
            for item in result.items:
                value = unit_price(
                    row["price_krw"], result, item.quantity, sitewide_vat=row["source"] == "yeoshin"
                )
                bucket = f"{item.procedure_id}:{item.tier}:{item.unit or 'unknown'}"
                conn.execute(
                    "INSERT INTO offer_items (option_id,procedure_id,brand_id,tier,quantity,unit,"
                    "area,sessions,is_bundle,price_from,conditions,extra_fees,vat,unit_price_krw,"
                    "bucket_key,content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row["id"],
                        item.procedure_id,
                        item.brand_id,
                        item.tier,
                        item.quantity,
                        item.unit,
                        item.area,
                        result.sessions,
                        int(result.is_bundle),
                        int(result.price_from),
                        json.dumps(result.conditions),
                        json.dumps(result.extra_fees),
                        result.vat,
                        float(value) if value is not None else None,
                        bucket,
                        row["content_hash"],
                    ),
                )
        offers = conn.execute("SELECT * FROM v_offers").fetchall()
        buckets: dict[str, list[float]] = {}
        for row in offers:
            if row["unit_price_krw"] is not None and not RESTRICTED.intersection(
                json.loads(row["conditions"])
            ):
                buckets.setdefault(row["bucket_key"], []).append(row["unit_price_krw"])
        stats = {}
        conn.execute("DELETE FROM bucket_stats WHERE date=?", (day,))
        conn.execute("DELETE FROM labels WHERE date=?", (day,))
        for key, values in buckets.items():
            stats[key] = {
                "n": len(values),
                "p5": percentile(values, 0.05),
                "p25": percentile(values, 0.25),
                "median": percentile(values, 0.5),
                "p75": percentile(values, 0.75),
            }
            conn.execute(
                "INSERT INTO bucket_stats VALUES (?,?,?,?,?,?,?)",
                (
                    day,
                    key,
                    len(values),
                    stats[key]["p5"],
                    stats[key]["p25"],
                    stats[key]["median"],
                    stats[key]["p75"],
                ),
            )
        for row in offers:
            label = label_price(row["unit_price_krw"], stats.get(row["bucket_key"]))
            conn.execute("INSERT INTO labels VALUES (?,?,?)", (day, row["offer_item_id"], label))
    return {"processed": len(offers), "buckets": len(stats)}
