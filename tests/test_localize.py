import pytest

from pipeline.db import connect
from pipeline.localize import (
    attach_translations,
    parse_response,
    save_translations,
    text_hash,
    translation_map,
    validate_translation,
)


def test_translation_numbers_are_immutable():
    assert validate_translation("울쎄라 300샷 3회", "美版超声刀 300发 3次")
    with pytest.raises(ValueError, match="numbers"):
        validate_translation("울쎄라 300샷", "美版超声刀 600发")


@pytest.mark.parametrize("value", ["<b>热玛吉</b>", "https://test.com", "써마지", ""])
def test_invalid_translation_rejected(value):
    with pytest.raises(ValueError):
        validate_translation("써마지", value)


def test_cache_and_display_projection_leave_facts_unchanged(config):
    original = "울쎄라 300샷"
    key = text_hash(original)
    save_translations(config, {key: original}, [{"id": key, "zh": "美版超声刀 300发"}], "test")
    with connect(config.database, readonly=True) as conn:
        mapping = translation_map(conn)
    payload = {
        "offers": [{"option_name": original, "price_krw": 890000, "quantity": 300}],
        "clinics": [],
        "raw_options": [],
    }
    attach_translations(payload, mapping)
    assert payload["offers"][0]["option_name_zh"] == "美版超声刀 300发"
    assert payload["offers"][0]["price_krw"] == 890000
    assert payload["offers"][0]["quantity"] == 300
    assert text_hash(original + " 3회") not in mapping


def test_translation_batch_is_atomic_on_invalid_row(config):
    a, b = text_hash("300샷"), text_hash("600샷")
    with pytest.raises(ValueError):
        save_translations(
            config,
            {a: "300샷", b: "600샷"},
            [{"id": a, "zh": "300发"}, {"id": b, "zh": "700发"}],
            "test",
        )
    with connect(config.database, readonly=True) as conn:
        assert not translation_map(conn)


def test_gateway_fence_parses_as_data_only():
    assert parse_response('```json\n[{"id":"a","zh":"测试"}]\n```')[0]["zh"] == "测试"
