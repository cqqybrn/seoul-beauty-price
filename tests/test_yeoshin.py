import json

import pytest

from pipeline.extract.explicit import explicit_dose
from pipeline.sources.base import SourceNotReady
from pipeline.sources.flight import embedded_json_values
from pipeline.sources.yeoshin import YeoshinAdapter
from tests.conftest import FIXTURES


def page(**updates):
    data = {
        "salesEvent": {
            "id": 29421,
            "hospitalId": 5184,
            "name": "울쎄라피 프라임 300샷",
            "publish": True,
            "view": True,
            "use": True,
        },
        "hospital": {
            "id": 5184,
            "name": "테스트의원",
            "address": "서울특별시 서초구 테스트로 1",
            "addressDetail": "5층",
            "kahf": True,
        },
        "salesProducts": [
            {
                "id": 415238,
                "hospitalId": 5184,
                "salesEventId": 29421,
                "name": "울쎄라피 프라임 300샷",
                "currency": "KRW",
                "price": 890000,
                "discountPrice": 853000,
                "treatmentCount": 1,
                "view": True,
            }
        ],
        **updates,
    }
    flight = "1:" + json.dumps(data, ensure_ascii=False) + "\n"
    return (
        "<html><body>VAT 포함<script>self.__next_f.push("
        + json.dumps([1, flight], ensure_ascii=False)
        + ");</script></body></html>"
    )


def test_parse_embedded_prices_separately():
    facts = YeoshinAdapter().parse_detail(page(), "https://www.yeoshin.co.kr/event/mobile/29421")
    assert facts.options[0].source_option_id == "415238"
    assert facts.options[0].price_krw == 890000
    assert facts.options[0].coupon_price_krw == 853000
    assert facts.options[0].list_price_krw is None
    assert facts.clinic_address.endswith("5층")
    assert facts.district == "서초구"
    assert facts.vat == "included"
    assert facts.foreign_patient_registered is None


def test_mismatched_event_not_imported():
    with pytest.raises(SourceNotReady):
        YeoshinAdapter().parse_detail(page(), "https://www.yeoshin.co.kr/event/mobile/1")


def test_missing_option_identity_rejected():
    with pytest.raises(SourceNotReady):
        YeoshinAdapter().parse_detail(
            page(salesProducts=[]), "https://www.yeoshin.co.kr/event/mobile/29421"
        )


def test_embedded_scripts_not_executed():
    assert embedded_json_values('<script>throw new Error("x")</script>', "hospital") == []


def projection_hospital(**values):
    flight = "2:" + json.dumps({"hospital": {"id": 5184, "name": "테스트의원", **values}})
    return "<script>self.__next_f.push(" + json.dumps([1, flight]) + ");</script>"


def test_summary_missing_address_not_a_conflict():
    html = page().replace(
        "<script>",
        projection_hospital(address=None, addressDetail=None) + "<script>",
        1,
    )
    facts = YeoshinAdapter().parse_detail(
        html,
        "https://www.yeoshin.co.kr/event/mobile/29421",
    )
    assert "테스트로 1" in facts.clinic_address
    assert facts.clinic_address.endswith("5층")


def test_summary_actual_address_disagreement_rejected():
    html = page().replace(
        "</body>",
        projection_hospital(address="서울 강남구 다른로 2", addressDetail="5층") + "</body>",
    )
    with pytest.raises(SourceNotReady, match="Conflicting clinic identity"):
        YeoshinAdapter().parse_detail(
            html,
            "https://www.yeoshin.co.kr/event/mobile/29421",
        )


def test_explicit_dose_uses_option_not_headline(dictionary):
    result = explicit_dose(
        {
            "title_raw": "울쎄라피 프라임 300샷",
            "name_raw": "울쎄라피 프라임 100샷(런칭 특가)",
            "sessions_raw": "1회",
            "vat": "included",
        },
        dictionary,
    )
    assert result.items[0].quantity == 100
    assert result.items[0].procedure_id == "ulthera"


@pytest.mark.parametrize(
    "name",
    [
        "울쎄라 300샷 + 리쥬란 2cc",
        "울쎄라 300샷 첫방문",
        "울쎄라 300샷부터",
        "울쎄라 용량상담",
        "대표원장 울쎄라 300샷",
        "첫 방문 울쎄라 300샷",
    ],
)
def test_ambiguous_rules_fail_closed(dictionary, name):
    assert (
        explicit_dose(
            {"title_raw": "울쎄라", "name_raw": name, "sessions_raw": "1회", "vat": "included"},
            dictionary,
        )
        is None
    )


def test_scrapy_https_handler_imports():
    # Scrapy 2.13 is incompatible with Twisted 26's removed private TLS symbol.
    from scrapy.core.downloader.handlers.http11 import HTTP11DownloadHandler

    assert HTTP11DownloadHandler


def test_real_fact_projection_has_three_distinct_option_prices():
    html = (FIXTURES / "yeoshin-29421.fact-projection.html").read_text(encoding="utf-8")
    facts = YeoshinAdapter().parse_detail(html, "https://www.yeoshin.co.kr/event/mobile/29421")
    prices = {o.source_option_id: (o.price_krw, o.coupon_price_krw) for o in facts.options}
    assert prices == {
        "415237": (1690000, 1653000),
        "415238": (890000, 853000),
        "415239": (320000, 297000),
    }
