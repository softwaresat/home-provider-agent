"""Deterministic, explainable provider ranking. No LLM scoring."""

from __future__ import annotations

import re

from app.models import Provider, ServiceCategory

# Google Places primaryType values that count as a category match.
CATEGORY_TYPES: dict[ServiceCategory, set[str]] = {
    ServiceCategory.plumbing: {"plumber", "plumbing_service"},
    ServiceCategory.hvac: {
        "hvac_contractor",
        "heating_contractor",
        "air_conditioning_contractor",
        "hvac_repair_service",
    },
    ServiceCategory.electrical: {"electrician", "electrical_service"},
    ServiceCategory.roofing: {"roofing_contractor", "roofing_service"},
    ServiceCategory.water_damage: {
        "water_damage_restoration_service",
        "flood_damage_restoration_service",
        "restoration_service",
    },
    ServiceCategory.pest_control: {"pest_control_service"},
    ServiceCategory.appliance_repair: {"appliance_repair_service"},
    ServiceCategory.handyman: {
        "handyman",
        "general_contractor",
        "home_improvement_store",
        "home_goods_store",
    },
    ServiceCategory.unknown: set(),
}

# Google often types trade businesses as "general_contractor", so the business
# name is the only listing field that confirms the trade.
CATEGORY_NAME_KEYWORDS: dict[ServiceCategory, tuple[str, ...]] = {
    ServiceCategory.plumbing: ("plumb", "rooter", "drain", "sewer", "water heater"),
    ServiceCategory.hvac: ("hvac", "air condition", "heating", "cooling", "a/c", "furnace"),
    ServiceCategory.electrical: ("electric",),
    ServiceCategory.roofing: ("roof",),
    ServiceCategory.water_damage: ("water damage", "restoration", "flood", "water removal", "drying"),
    ServiceCategory.pest_control: ("pest", "extermin", "termite", "bug"),
    ServiceCategory.appliance_repair: ("appliance",),
    ServiceCategory.handyman: ("handyman", "home repair", "home services"),
    ServiceCategory.unknown: (),
}

RATING_PRIOR_MEAN = 3.5
RATING_PRIOR_WEIGHT = 10.0


def _type_match(provider: Provider, category: ServiceCategory) -> bool:
    wanted = CATEGORY_TYPES.get(category) or set()
    if not wanted:
        return False
    primary = (provider.primary_type or "").strip()
    display = (provider.primary_type_display or "").lower().replace(" ", "_")
    return primary in wanted or display in wanted


def _name_match(provider: Provider, category: ServiceCategory) -> bool:
    name = provider.name.lower()
    return any(keyword in name for keyword in CATEGORY_NAME_KEYWORDS.get(category, ()))


def is_trade_match(provider: Provider, category: ServiceCategory) -> bool:
    if category == ServiceCategory.unknown:
        return False
    return _type_match(provider, category) or _name_match(provider, category)


def is_contactable(provider: Provider) -> bool:
    return bool(provider.phone or provider.email or provider.website or provider.maps_url)


def _area_code(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[:3] if len(digits) == 10 else None


def bayesian_rating_points(rating: float | None, review_count: int | None) -> tuple[float, str | None]:
    if rating is None:
        return 0.0, None
    n = float(review_count or 0)
    weighted = (n * float(rating) + RATING_PRIOR_WEIGHT * RATING_PRIOR_MEAN) / (n + RATING_PRIOR_WEIGHT)
    points = max(0.0, min(2.0, (weighted / 5.0) * 2.0))
    reviews = int(review_count or 0)
    reason = f"Google rating {rating:.1f} ({reviews} reviews); listing quality is not independently verified"
    return points, reason


def score_provider(
    provider: Provider,
    category: ServiceCategory,
    city: str | None,
    zip_code: str | None,
) -> Provider:
    score = 0.0
    reasons: list[str] = []

    trade = category.value.replace("_", " ")
    if _type_match(provider, category):
        score += 3
        label = provider.primary_type_display or provider.primary_type or category.value
        reasons.append(f"Listing type matches {trade} ({label})")
    elif _name_match(provider, category):
        score += 2
        label = provider.primary_type_display or provider.primary_type
        listed = f"; Google lists it as {label}" if label else ""
        reasons.append(f"Business name indicates {trade} work{listed}")
    elif provider.primary_type or provider.primary_type_display:
        label = provider.primary_type_display or provider.primary_type
        reasons.append(f"Listed as {label}; category match is not confirmed")
    else:
        reasons.append("Business type not provided on the listing")

    if provider.phone:
        score += 2
        reasons.append("Phone number is on the listing")
    else:
        reasons.append("No phone number on the listing")

    if provider.website:
        score += 1
        reasons.append("Website is on the listing")

    rating_points, rating_reason = bayesian_rating_points(provider.rating, provider.review_count)
    score += rating_points
    if rating_reason:
        reasons.append(rating_reason)

    loc_hits = []
    address = (provider.address or "").lower()
    if city and city.lower() in address:
        loc_hits.append("city")
    if zip_code and zip_code in address:
        loc_hits.append("ZIP")
    if loc_hits:
        score += 1
        reasons.append(f"Address includes the requested {' and '.join(loc_hits)}")
    elif provider.is_service_area_business:
        reasons.append("Mobile/service-area business — service area not confirmed")
    elif provider.address:
        reasons.append("Address does not obviously match the requested city/ZIP")
    else:
        reasons.append("No public address; geographic relevance is the search query only")

    ranked = provider.model_copy()
    ranked.match_score = round(score, 3)
    ranked.match_reasons = reasons
    ranked.trade_confirmed = is_trade_match(provider, category)
    ranked.contactable = is_contactable(provider)
    return ranked


def rank_providers(
    providers: list[Provider],
    category: ServiceCategory,
    city: str | None = None,
    zip_code: str | None = None,
) -> list[Provider]:
    scored = [score_provider(p, category, city, zip_code) for p in providers]
    _flag_nonlocal_phones(scored)
    scored.sort(key=lambda p: (-p.match_score, -(p.review_count or 0), p.name.lower()))
    return scored


def _flag_nonlocal_phones(providers: list[Provider]) -> None:
    """Penalize no-address listings whose area code no addressed result uses.

    National lead-gen call centers often appear as service-area businesses with
    an out-of-state number. Local area codes are inferred from the listings in
    this same search that do publish a street address.
    """
    local_codes = {
        code
        for p in providers
        if p.address and (code := _area_code(p.phone))
    }
    if not local_codes:
        return
    for provider in providers:
        code = _area_code(provider.phone)
        if provider.address or not code or code in local_codes:
            continue
        provider.match_score = round(provider.match_score - 2, 3)
        provider.match_reasons.append(
            f"Phone area code ({code}) matches no locally addressed listing in this search; "
            "may be a national call center rather than a local business"
        )


def match_explanation(provider: Provider) -> str:
    if not provider.match_reasons:
        return f"{provider.name} was returned by Google Places for this search."
    bullets = "; ".join(provider.match_reasons)
    return (
        f"{provider.name} ranked highest among live listings because: {bullets}. "
        "This is listing relevance, not a quality guarantee."
    )
