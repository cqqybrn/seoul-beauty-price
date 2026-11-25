import json
from pathlib import Path

FIELDS = ("procedure_id", "quantity", "unit", "price")


def evaluate(golden_path: Path, prediction_path: Path) -> dict:
    gold = [
        json.loads(line) for line in golden_path.read_text(encoding="utf-8").splitlines() if line
    ]
    predictions = [
        json.loads(line)
        for line in prediction_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(gold) != 100 or len({r["option_id"] for r in gold}) != 100:
        raise ValueError("M2 acceptance requires exactly 100 distinct designer-annotated options")
    if any(row.get("annotation_source") != "designer" for row in gold):
        raise ValueError("Only designer-provided gold labels count for M2")
    by_id = {row["option_id"]: row for row in predictions}
    if len(by_id) != len(predictions) or set(by_id) != {r["option_id"] for r in gold}:
        raise ValueError("Predictions must match the 100 golden option IDs exactly")
    correct = {field: 0 for field in FIELDS}
    for row in gold:
        prediction = by_id[row["option_id"]]
        for field in FIELDS:
            correct[field] += int(row[field] == prediction.get(field))
    accuracy = {field: correct[field] / 100 for field in FIELDS}
    return {"n": 100, "accuracy": accuracy, "accepted": all(v >= 0.95 for v in accuracy.values())}
