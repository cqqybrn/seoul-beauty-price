# Fixture provenance

These fixtures are **synthetic regression examples**, not saved source HTML and not
M2 golden annotation data. They encode the markup shape observed on 2026-11-15:
Product JSON-LD with headline price does not establish selectable options; an
HTTP-200 error page is not an ended event; footer company address is not clinic address.

The fact projection is invented and must never be published as live data.
Tests prohibit network access using an autouse socket guard.

`yeoshin-29421.fact-projection.html` is different: real public allowed facts fetched
2026-11-15 from https://www.yeoshin.co.kr/event/mobile/29421, reconstructed into a
minimal Flight fixture. It is **not original full HTML**: reviews, nicknames, images,
doctor data, identifiers unrelated to the event/clinic/options, and marketing descriptions
have been removed. It preserves option IDs and observed base/coupon prices for regression.
