"""Conservative public JSON-LD parser. Missing evidence fails closed, never invents selectors."""

import hashlib
import re
from urllib.parse import urlsplit

import extruct

from pipeline.sources.base import EventFacts, OptionFacts, SourceNotReady


def parse_public_offers(html: str, url: str, source: str) -> EventFacts:
    documents = extruct.extract(html, base_url=url, syntaxes=["json-ld"])["json-ld"]
    nodes = []
    for document in documents:
        if isinstance(document, dict):
            nodes.extend(document.get("@graph", [document]))
    product = next((n for n in nodes if isinstance(n, dict) and n.get("@type") == "Product"), None)
    if not product:
        raise SourceNotReady("No public Product facts in HTTP response")
    offer_data = product.get("offers", {})
    # A singular Offer is the headline price. Only explicit named, separately identified
    # offers can represent purchasable options; main/new-member prices are not inferred.
    if isinstance(offer_data, dict):
        offers = offer_data.get("offers", [])
    elif isinstance(offer_data, list):
        offers = offer_data
    else:
        offers = []
    if not isinstance(offers, list) or not offers:
        raise SourceNotReady("No explicit public named purchasable options in JSON-LD")
    seller = offer_data.get("seller", {}) if isinstance(offer_data, dict) else {}
    if not seller:
        seller = offers[0].get("seller", {})
    if not isinstance(seller, dict):
        raise SourceNotReady("No verified clinic seller")
    address = seller.get("address", {})
    if isinstance(address, dict):
        address = " ".join(
            str(address[k])
            for k in ("addressRegion", "addressLocality", "streetAddress")
            if address.get(k)
        )
    if not isinstance(address, str) or not address.strip():
        raise SourceNotReady("No verified clinic address; footer addresses are not used")
    options = []
    for offer in offers:
        if not isinstance(offer, dict) or not offer.get("name"):
            raise SourceNotReady("Purchasable option has no explicit name")
        if offer.get("priceCurrency") != "KRW":
            raise SourceNotReady("Purchasable option has no verified KRW price")
        price = str(offer.get("price", ""))
        if not re.fullmatch(r"[1-9]\d*", price):
            raise SourceNotReady("Purchasable option price is not a positive integer")
        identifier = offer.get("sku") or offer.get("@id") or offer.get("url")
        if not identifier:
            raise SourceNotReady("No stable source option identifier")
        # Yeoshin requires explicit base-vs-discount evidence; ambiguous schemas are rejected.
        if source == "yeoshin":
            raise SourceNotReady("Yeoshin coupon/base-price DOM verification remains required")
        options.append(
            OptionFacts(
                source_option_id=hashlib.sha256(str(identifier).encode()).hexdigest()[:24],
                name_raw=offer["name"],
                price_krw=int(price),
            )
        )
    clinic_name = seller.get("name")
    title = product.get("name")
    if not clinic_name or not title:
        raise SourceNotReady("Missing public clinic or event name")
    return EventFacts(
        source=source,
        source_event_id=urlsplit(url).path.rstrip("/").split("/")[-1],
        url=url,
        title_raw=title,
        clinic_name=clinic_name,
        clinic_address=address,
        options=options,
        vat="unknown",
    )
