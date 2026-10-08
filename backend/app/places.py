"""Google Places API (New) Text Search. The LLM never invents businesses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx

from app import config
from app.models import Provider, ServiceCategory

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.googleMapsUri",
    "places.rating",
    "places.userRatingCount",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.businessStatus",
    "places.pureServiceAreaBusiness",
])

CATEGORY_QUERY: dict[ServiceCategory, str] = {
    ServiceCategory.plumbing: "plumber",
    ServiceCategory.hvac: "HVAC contractor",
    ServiceCategory.electrical: "electrician",
    ServiceCategory.roofing: "roofing contractor",
    ServiceCategory.water_damage: "water damage restoration",
    ServiceCategory.pest_control: "pest control",
    ServiceCategory.appliance_repair: "appliance repair",
    ServiceCategory.handyman: "handyman",
    ServiceCategory.unknown: "home repair",
}

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "fallback_providers.json"


def build_text_query(
    category: ServiceCategory,
    location: str,
    urgency: Optional[str] = None,
) -> str:
    trade = CATEGORY_QUERY.get(category, "home repair")
    prefix = "emergency " if urgency == "emergency" else ""
    loc = (location or config.DEFAULT_LOCATION).strip()
    return f"{prefix}{trade} in {loc}".strip()


def _place_id(raw: dict) -> Optional[str]:
    place_id = raw.get("id")
    if place_id:
        return str(place_id)
    name = raw.get("name") or ""
    if isinstance(name, str) and name.startswith("places/"):
        return name.split("/", 1)[1]
    if name:
        return str(name)
    return None


def _display_name(raw: dict) -> Optional[str]:
    display = raw.get("displayName")
    if isinstance(display, dict):
        text = display.get("text")
        return str(text) if text else None
    if isinstance(display, str):
        return display
    return None


def provider_from_place(raw: dict, source: str) -> Optional[Provider]:
    place_id = _place_id(raw)
    name = _display_name(raw)
    if not place_id or not name:
        return None
    status = raw.get("businessStatus")
    if status and status != "OPERATIONAL":
        return None
    type_display = raw.get("primaryTypeDisplayName")
    if isinstance(type_display, dict):
        type_display = type_display.get("text")
    return Provider(
        place_id=place_id,
        name=name,
        address=raw.get("formattedAddress"),
        phone=raw.get("nationalPhoneNumber"),
        website=raw.get("websiteUri"),
        maps_url=raw.get("googleMapsUri"),
        rating=raw.get("rating"),
        review_count=raw.get("userRatingCount"),
        primary_type=raw.get("primaryType"),
        primary_type_display=type_display if isinstance(type_display, str) else None,
        is_service_area_business=bool(raw.get("pureServiceAreaBusiness")),
        source=source,
    )


def load_fallback_fixture() -> list[Provider]:
    if not FIXTURE_PATH.exists():
        return []
    try:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    providers: list[Provider] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        # Recorded live responses may be raw Place objects or already-normalized Providers.
        if "place_id" in item and "name" in item:
            try:
                provider = Provider.model_validate(item)
                provider.source = "fallback_fixture"
                providers.append(provider)
                continue
            except Exception:  # noqa: BLE001
                continue
        parsed = provider_from_place(item, source="fallback_fixture")
        if parsed:
            providers.append(parsed)
    return providers


def write_fallback_fixture(providers: list[Provider]) -> None:
    """Dev-only. Places terms restrict caching; do not use this as a production cache."""
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [p.model_dump() for p in providers]
    for item in payload:
        item["source"] = "fallback_fixture"
    FIXTURE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def search_text(
    category: ServiceCategory,
    location: str,
    urgency: Optional[str] = None,
) -> tuple[list[Provider], str, Optional[str]]:
    """Return (providers, source, error_message). source is google_places or fallback_fixture."""
    query = build_text_query(category, location, urgency)

    if not config.places_configured():
        fixtures = load_fallback_fixture()
        if not fixtures:
            return [], "fallback_fixture", (
                "Google Places is not configured and the fallback fixture is empty. "
                "Set GOOGLE_PLACES_API_KEY in backend/.env."
            )
        return fixtures, "fallback_fixture", (
            "Google Places key missing; showing recorded fallback listings, not a live search."
        )

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {
        "textQuery": query,
        "pageSize": 10,
        "includePureServiceAreaBusinesses": True,
    }
    try:
        response = httpx.post(
            PLACES_TEXT_SEARCH_URL,
            headers=headers,
            json=body,
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        fixtures = load_fallback_fixture()
        message = f"Places API error ({exc})."
        if fixtures:
            return fixtures, "fallback_fixture", message + " Showing recorded fallback listings."
        return [], "fallback_fixture", message + " Fallback fixture is empty."

    providers: list[Provider] = []
    for raw in data.get("places") or []:
        parsed = provider_from_place(raw, source="google_places")
        if parsed:
            providers.append(parsed)
    if not providers:
        fixtures = load_fallback_fixture()
        if fixtures:
            return fixtures, "fallback_fixture", "Places returned no operational listings; showing fallback data."
        return [], "google_places", "No operational listings matched this search."
    return providers, "google_places", None
