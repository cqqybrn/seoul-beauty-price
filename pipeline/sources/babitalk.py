import json
from dataclasses import dataclass

import extruct
from parsel import Selector

from pipeline.sources.base import EventFacts, SourceAdapter, SourceNotReady, SourcePolicy
from pipeline.sources.structured import parse_public_offers


@dataclass(frozen=True)
class HttpObservation:
    """Diagnostic facts only, never a purchasable option or a stored full HTML page."""

    has_product: bool
    has_option_heading: bool
    is_error_page: bool
    title: str | None
    clinic_name: str | None
    headline_price_krw: int | None


class BabitalkAdapter(SourceAdapter):
    policy = SourcePolicy(
        "babitalk", "babitalk.com", "https://babitalk.com/sitemap/sitemap-event.xml", 3
    )

    def observe_http(self, html: str, url: str) -> HttpObservation:
        selector = Selector(text=html)
        title = selector.css("title::text").get("")
        visible = " ".join(
            selector.xpath(
                "//body//text()[not(ancestor::script) and not(ancestor::style)]"
            ).getall()
        )
        product = None
        for node in extruct.extract(html, base_url=url, syntaxes=["json-ld"])["json-ld"]:
            nodes = node.get("@graph", [node]) if isinstance(node, dict) else []
            for item in nodes:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    product = item
                    break
        offer = product.get("offers", {}) if product else {}
        if not isinstance(offer, dict):
            offer = {}
        price = offer.get("price")
        # JSON-LD is deliberately not trusted for selectable option prices.
        try:
            parsed_price = int(str(price)) if price is not None else None
        except ValueError:
            parsed_price = None
        seller = offer.get("seller", {})
        if not isinstance(seller, dict):
            seller = {}
        return HttpObservation(
            has_product=product is not None,
            has_option_heading="이벤트 옵션" in visible,
            is_error_page=title.strip().casefold().startswith("error"),
            title=product.get("name") if product else None,
            clinic_name=seller.get("name"),
            headline_price_krw=parsed_price,
        )

    def parse_detail(self, html: str, url: str) -> EventFacts:
        observed = self.observe_http(html, url)
        if not observed.is_error_page:
            try:
                return parse_public_offers(html, url, "babitalk")
            except SourceNotReady:
                pass
        reason = "HTTP-200 error page" if observed.is_error_page else "unverified option markup"
        raise SourceNotReady(
            f"Babitalk: {reason}; main JSON-LD price is not a selectable option. "
            "Browser-rendered option/address evidence is required before enabling collection."
        )


def observation_json(observation: HttpObservation) -> str:
    from dataclasses import asdict

    return json.dumps(asdict(observation), ensure_ascii=False, indent=2)
