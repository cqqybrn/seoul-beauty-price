import re
from urllib.parse import urlsplit

from parsel import Selector

from pipeline.sources.base import (
    EventFacts,
    OptionFacts,
    SourceAdapter,
    SourceNotReady,
    SourcePolicy,
)
from pipeline.sources.flight import embedded_json_values


class YeoshinAdapter(SourceAdapter):
    policy = SourcePolicy(
        "yeoshin",
        "www.yeoshin.co.kr",
        "https://www.yeoshin.co.kr/sitemap.xml",
        5,
        sitewide_vat_included=True,
    )

    def parse_detail(self, html: str, url: str):
        event_id = urlsplit(url).path.rstrip("/").split("/")[-1]
        if not event_id.isdigit():
            raise SourceNotReady("Invalid Yeoshin event URL")
        events = [
            e
            for e in embedded_json_values(html, "salesEvent")
            if isinstance(e, dict) and str(e.get("id")) == event_id
        ]
        if not events:
            raise SourceNotReady("Missing or ambiguous public event facts")
        event = events[0]
        if any(
            any(
                e.get(k) != event.get(k)
                for k in ("id", "hospitalId", "name", "publish", "view", "use", "trash")
            )
            for e in events[1:]
        ):
            raise SourceNotReady("Conflicting public event facts")
        if any(event.get(k) is False for k in ("use", "view", "publish")) or event.get("trash"):
            raise SourceNotReady("Event is not publicly active")
        hospitals = [
            h
            for h in embedded_json_values(html, "hospital")
            if isinstance(h, dict) and h.get("id") == event.get("hospitalId")
        ]
        if not hospitals:
            raise SourceNotReady("Missing or ambiguous clinic identity")
        # Public summary cards sometimes omit the address entirely. A missing field
        # is not contradictory evidence. Only merge an explicit value when every
        # nonempty projection agrees; two actual addresses still fail closed.
        hospital = dict(hospitals[0])
        for field in ("id", "name", "address", "addressDetail"):
            values = {h[field] for h in hospitals if h.get(field) not in (None, "")}
            if len(values) > 1:
                diagnostic = [
                    {k: h.get(k) for k in ("id", "name", "address", "addressDetail")}
                    for h in hospitals
                ]
                raise SourceNotReady("Conflicting clinic identity: " + repr(diagnostic))
            hospital[field] = next(iter(values), None)
        groups = embedded_json_values(html, "salesProducts")
        products = {}
        for group in groups:
            if not isinstance(group, list):
                continue
            for product in group:
                if not isinstance(product, dict) or str(product.get("salesEventId")) != event_id:
                    continue
                if product.get("hospitalId") != hospital["id"] or product.get("view") is False:
                    continue
                identifier = str(product.get("id", ""))
                if identifier in products and any(
                    products[identifier].get(k) != product.get(k)
                    for k in ("id", "name", "price", "currency", "treatmentCount")
                ):
                    diagnostic = [
                        {k: p.get(k) for k in ("id", "name", "price", "currency", "treatmentCount")}
                        for p in (products[identifier], product)
                    ]
                    raise SourceNotReady("Conflicting option facts: " + repr(diagnostic))
                # Repeated UI projections can omit coupon application while retaining base price.
                # Prefer the explicit discountable calculation, never replace the base price.
                if identifier in products and products[identifier].get("discountable"):
                    continue
                products[identifier] = product
        options = []
        for identifier, product in products.items():
            price = product.get("price")
            coupon = product.get("discountPrice")
            count = product.get("treatmentCount")
            if (
                not identifier.isdigit()
                or product.get("currency") != "KRW"
                or type(price) is not int
                or price <= 0
                or type(count) is not int
                or count < 1
            ):
                raise SourceNotReady(
                    "Option price, currency, identity or treatment count unverified"
                )
            if coupon is not None and (type(coupon) is not int or not 0 < coupon <= price):
                raise SourceNotReady("Invalid coupon-price field")
            # oneTimeRegularPrice is a per-session regular price, NOT a strikethrough total.
            options.append(
                OptionFacts(
                    source_option_id=identifier,
                    name_raw=product["name"],
                    sessions_raw=f"{count}회",
                    price_krw=price,
                    coupon_price_krw=coupon if coupon != price else None,
                )
            )
        if not options:
            raise SourceNotReady("No public purchasable options")
        address = " ".join(
            str(hospital.get(k) or "").strip() for k in ("address", "addressDetail")
        ).strip()
        if not address or not hospital.get("name"):
            raise SourceNotReady("Clinic name and address required")
        visible = " ".join(
            Selector(text=html)
            .xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]")
            .getall()
        )
        district = re.search(r"(?:서울특별시|서울)\s+(\S+구)\b", address)
        return EventFacts(
            source="yeoshin",
            source_event_id=event_id,
            url=url,
            title_raw=event["name"],
            clinic_name=hospital["name"],
            clinic_address=address,
            source_clinic_id=str(hospital["id"]),
            district=district[1] if district else None,
            area=hospital.get("landmark"),
            # kahf has not yet been verified as the foreign-patient registration field.
            foreign_patient_registered=None,
            vat="included" if "VAT 포함" in visible else "unknown",
            options=options,
        )
