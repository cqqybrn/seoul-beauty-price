import pytest

from pipeline.extract.lexical import classify_unranked
from pipeline.pricing import unit_price
from pipeline.validate import validate_extraction


def option(name, **updates):
    return {"name_raw": name, "title_raw": "", "sessions_raw": "1회", "vat": "included", **updates}


def test_unranked_never_invents_dose_or_brand(dictionary):
    result = classify_unranked(option("보톡스 턱 상담"), dictionary)
    assert result.items[0].brand_id is None
    assert result.items[0].quantity is None
    assert result.items[0].unit is None
    assert unit_price(10000, result, result.items[0].quantity) is None
    assert not validate_extraction(result, 10000, dictionary)


def test_unranked_conditions_and_raw_sessions(dictionary):
    result = classify_unranked(option("평일 첫방문 슈링크", sessions_raw="3회"), dictionary)
    assert set(result.conditions) == {"weekday_only", "first_visit"}
    assert result.sessions == 3


@pytest.mark.parametrize(
    "name", ["슈링크 + 리쥬란", "슈링크 패키지", "슈링크 무제한", "슈링크 12개월권"]
)
def test_unranked_complex_bundles_rejected(dictionary, name):
    assert classify_unranked(option(name), dictionary) is None


def test_headline_not_used_to_classify_unrelated_option(dictionary):
    assert classify_unranked(option("진정관리", title_raw="울쎄라 300샷"), dictionary) is None


def test_brand_not_transferred_from_headline(dictionary):
    result = classify_unranked(option("보톡스 턱", title_raw="제오민 보톡스"), dictionary)
    assert result.items[0].brand_id is None


def test_sessions_must_be_explicit(dictionary):
    assert classify_unranked(option("슈링크", sessions_raw=""), dictionary) is None


def test_filler_dissolving_not_fill_injection(dictionary):
    assert classify_unranked(option("필러 녹이는 주사"), dictionary) is None
