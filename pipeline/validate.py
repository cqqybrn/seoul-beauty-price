from pipeline.dictionary import Dictionary
from pipeline.extract.schema import ExtractedOption


def validate_extraction(
    result: ExtractedOption, price_krw: int, dictionary: Dictionary
) -> list[str]:
    reasons = []
    if type(price_krw) is not int or price_krw <= 0:
        reasons.append("invalid_price")
    if not result.is_bundle and len(result.items) != 1:
        reasons.append("non_bundle_multiple_items")
    if result.is_bundle and len({i.procedure_id for i in result.items}) < 2:
        reasons.append("bundle_requires_distinct_procedures")
    by_id = {p.id: p for p in dictionary.procedures}
    for item in result.items:
        procedure = by_id.get(item.procedure_id)
        if procedure is None:
            reasons.append("unknown_procedure")
            continue
        # A missing quantity is intentionally unranked, not hidden; an invalid quantity is rejected.
        if item.unit is not None and item.unit not in procedure.canonical_units:
            reasons.append("invalid_unit")
        if item.quantity is not None:
            if item.unit is None:
                reasons.append("quantity_without_unit")
            elif item.unit in procedure.quantity_bounds:
                lo, hi = procedure.quantity_bounds[item.unit]
                if not lo <= item.quantity <= hi:
                    reasons.append("quantity_out_of_range")
        if item.brand_id is not None:
            brand = next((b for b in procedure.brands if b.id == item.brand_id), None)
            if not brand:
                reasons.append("unknown_brand")
            elif brand.tier != item.tier:
                reasons.append("brand_tier_mismatch")
        elif item.tier != "unknown":
            reasons.append("tier_without_brand")
    if result.confidence < 0.7:
        reasons.append("low_confidence")
    return sorted(set(reasons))
