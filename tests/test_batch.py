import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.genai import types

from pipeline.db import connect
from pipeline.extract.batch import poll_batch, submit_batch
from pipeline.extract.evaluate import evaluate
from pipeline.ingest import ingest_facts
from tests.test_m1_foundations import facts
from tests.test_runtime import extraction, priced_config


def test_batch_submit_poll_cache(config, dictionary):
    ingest_facts(config, facts(), dictionary)
    settings = priced_config(config)
    api = Mock()
    api.batches.create.return_value = SimpleNamespace(
        name="batches/test",
        state=SimpleNamespace(name="JOB_STATE_PENDING"),
    )
    result = submit_batch(settings, client=api)
    assert result["submitted"] == 2
    requests = api.batches.create.call_args.kwargs["src"]
    assert all(request.config.tools == [] for request in requests)
    assert all(request.config.automatic_function_calling.disable for request in requests)
    assert submit_batch(settings, client=api)["submitted"] == 0
    api.batches.get.return_value = SimpleNamespace(
        state=SimpleNamespace(name="JOB_STATE_RUNNING"),
    )
    assert poll_batch(settings, "batches/test", client=api)["pending"]
    responses = []
    for request in requests:
        responses.append(
            types.InlinedResponse(
                metadata=request.metadata,
                response=types.GenerateContentResponse(
                    candidates=[
                        types.Candidate(
                            content=types.Content(
                                role="model",
                                parts=[
                                    types.Part.from_text(text=extraction().model_dump_json()),
                                ],
                            )
                        )
                    ],
                    usage_metadata=types.GenerateContentResponseUsageMetadata(
                        prompt_token_count=100,
                        candidates_token_count=100,
                        total_token_count=200,
                    ),
                ),
            )
        )
    api.batches.get.return_value = SimpleNamespace(
        state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
        dest=types.BatchJobDestination(inlined_responses=responses),
    )
    assert poll_batch(settings, "batches/test", client=api)["imported"] == 2
    assert poll_batch(settings, "batches/test", client=api)["already_imported"]
    with connect(settings.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM extractions WHERE valid=1").fetchone()[0] == 2


def test_unknown_batch_rejected(config):
    with pytest.raises(ValueError, match="Unknown"):
        poll_batch(config, "batches/missing", client=Mock())


def test_evaluation_requires_100_designer_labels(tmp_path):
    gold = tmp_path / "gold.jsonl"
    pred = tmp_path / "pred.jsonl"
    row = {"option_id": 1, "procedure_id": "botox", "quantity": 1, "unit": "area", "price": 100}
    gold.write_text(json.dumps(row) + "\n")
    pred.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="100"):
        evaluate(gold, pred)


def test_evaluation_measures_fields_individually(tmp_path):
    gold = tmp_path / "gold.jsonl"
    pred = tmp_path / "pred.jsonl"
    rows = [
        {
            "option_id": i,
            "procedure_id": "botox",
            "quantity": 1,
            "unit": "area",
            "price": 100,
            "annotation_source": "designer",
        }
        for i in range(100)
    ]
    gold.write_text("\n".join(json.dumps(r) for r in rows))
    rows[0]["procedure_id"] = "unknown"
    for row in rows[:6]:
        row["quantity"] = 99
    pred.write_text("\n".join(json.dumps(r) for r in rows))
    result = evaluate(gold, pred)
    assert result["accuracy"] == {"procedure_id": 0.99, "quantity": 0.94, "unit": 1.0, "price": 1.0}
    assert not result["accepted"]
