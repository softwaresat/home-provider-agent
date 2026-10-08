"""Pydantic models and enums for the lead-agent prototype."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ServiceCategory(str, Enum):
    plumbing = "plumbing"
    hvac = "hvac"
    electrical = "electrical"
    roofing = "roofing"
    water_damage = "water_damage"
    pest_control = "pest_control"
    appliance_repair = "appliance_repair"
    handyman = "handyman"
    unknown = "unknown"


class Urgency(str, Enum):
    emergency = "emergency"
    same_day = "same_day"
    within_week = "within_week"
    flexible = "flexible"


class Stage(str, Enum):
    gathering = "gathering"
    need_location = "need_location"
    searching = "searching"
    showing_providers = "showing_providers"
    no_results = "no_results"
    collecting_contact = "collecting_contact"
    lead_ready = "lead_ready"
    safety_escalated = "safety_escalated"


class LeadStatus(str, Enum):
    complete = "complete"
    incomplete = "incomplete"
    safety_escalated = "safety_escalated"


class Hazard(str, Enum):
    gas_leak = "gas_leak"
    fire_smoke = "fire_smoke"
    electrical = "electrical"
    flood_electrical = "flood_electrical"
    carbon_monoxide = "carbon_monoxide"


# Hazards that stop the lead funnel and show emergency instructions.
ESCALATE_HAZARDS = {
    Hazard.gas_leak,
    Hazard.fire_smoke,
    Hazard.carbon_monoxide,
}

# Hazards that add caution text and force emergency urgency, but still allow help.
CAUTION_HAZARDS = {
    Hazard.electrical,
    Hazard.flood_electrical,
}


def _coerce_enum(value, enum_cls, default):
    if isinstance(value, enum_cls):
        return value
    if value is None or value == "":
        return default
    if isinstance(value, str):
        key = value.lower().strip().replace(" ", "_").replace("-", "_")
        try:
            return enum_cls(key)
        except ValueError:
            return default
    return default


class LLMAnalysis(BaseModel):
    """The only structured shape the LLM is allowed to return."""

    service_category: ServiceCategory = ServiceCategory.unknown
    category_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    urgency: Urgency = Urgency.flexible
    urgency_reason: str = ""
    problem_summary: str = ""
    facts: dict[str, str] = Field(default_factory=dict)
    city: Optional[str] = None
    zip_code: Optional[str] = None
    hazards: list[Hazard] = Field(default_factory=list)
    missing_details: list[str] = Field(default_factory=list)
    next_question: Optional[str] = None

    @field_validator("service_category", mode="before")
    @classmethod
    def coerce_category(cls, value):
        return _coerce_enum(value, ServiceCategory, ServiceCategory.unknown)

    @field_validator("urgency", mode="before")
    @classmethod
    def coerce_urgency(cls, value):
        return _coerce_enum(value, Urgency, Urgency.flexible)

    @field_validator("category_confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))

    @field_validator("facts", mode="before")
    @classmethod
    def coerce_facts(cls, value):
        if not value:
            return {}
        if not isinstance(value, dict):
            return {}
        cleaned = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned[str(key)] = str(item)
        return cleaned

    @field_validator("hazards", mode="before")
    @classmethod
    def coerce_hazards(cls, value):
        if not value:
            return []
        if not isinstance(value, list):
            value = [value]
        out: list[Hazard] = []
        seen = set()
        for item in value:
            hazard = _coerce_enum(item, Hazard, None)
            if hazard is None or hazard in seen:
                continue
            seen.add(hazard)
            out.append(hazard)
        return out

    @field_validator("missing_details", mode="before")
    @classmethod
    def coerce_missing(cls, value):
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item]

    @field_validator("city", "zip_code", "next_question", "problem_summary", "urgency_reason", mode="before")
    @classmethod
    def empty_str_to_none_or_strip(cls, value, info):
        if value is None:
            return None if info.field_name in {"city", "zip_code", "next_question"} else ""
        if isinstance(value, str):
            stripped = value.strip()
            if info.field_name in {"city", "zip_code", "next_question"}:
                return stripped or None
            return stripped
        return value


class Provider(BaseModel):
    place_id: str
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    primary_type: Optional[str] = None
    primary_type_display: Optional[str] = None
    is_service_area_business: bool = False
    source: str = "google_places"
    match_score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    trade_confirmed: bool = False
    contactable: bool = False


class ContactInfo(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    service_address: Optional[str] = None
    consent_to_share: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def require_name(cls, value):
        if value is None:
            raise ValueError("name is required")
        stripped = str(value).strip()
        if not stripped:
            raise ValueError("name is required")
        return stripped

    @field_validator("phone", "email", "service_address", mode="before")
    @classmethod
    def empty_to_none(cls, value):
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @model_validator(mode="after")
    def require_phone_or_email(self):
        if not self.phone and not self.email:
            raise ValueError("At least one of phone or email is required")
        return self


class ChatMessage(BaseModel):
    role: str
    content: str


class Lead(BaseModel):
    problem_summary: str = ""
    service_category: ServiceCategory = ServiceCategory.unknown
    urgency: Urgency = Urgency.flexible
    problem_details: dict[str, str] = Field(default_factory=dict)
    city: Optional[str] = None
    zip_code: Optional[str] = None
    service_address: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    selected_provider: Optional[Provider] = None
    provider_contact_details: Optional[str] = None
    safety_notes: Optional[str] = None
    consent_to_share: bool = False
    status: LeadStatus = LeadStatus.incomplete
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    provider_match_explanation: str = ""
    verification_note: str = (
        "Listing data comes from Google Places (or a recorded fallback fixture). "
        "This verifies that a business listing exists. It does not confirm service area, "
        "availability, licensing, or willingness to accept a job."
    )


class EmailDraft(BaseModel):
    to_name: str = ""
    to_contact: str = ""
    to_email: Optional[str] = None
    subject: str = ""
    body: str = ""
    mailto_url: Optional[str] = None
    mailto_disabled_reason: Optional[str] = None
    fallback_url: Optional[str] = None
    fallback_label: Optional[str] = None


class SessionState(BaseModel):
    id: str
    stage: Stage = Stage.gathering
    messages: list[ChatMessage] = Field(default_factory=list)
    analysis: Optional[LLMAnalysis] = None
    questions_asked: int = 0
    asked_questions: list[str] = Field(default_factory=list)
    location_question_asked: bool = False
    category_override: Optional[ServiceCategory] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    location_query: Optional[str] = None
    providers: list[Provider] = Field(default_factory=list)
    selected_place_id: Optional[str] = None
    contact: Optional[ContactInfo] = None
    lead: Optional[Lead] = None
    email: Optional[EmailDraft] = None
    safety_advice: Optional[str] = None
    hazards: list[Hazard] = Field(default_factory=list)
    llm_fallback_used: bool = False
    safety_cleared: bool = False
    search_source: Optional[str] = None
    search_error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    deepseek_configured: bool
    google_places_configured: bool
    search_mode: str
    model: str


class MessageRequest(BaseModel):
    text: str


class SearchRequest(BaseModel):
    category: Optional[ServiceCategory] = None
    location: Optional[str] = None


class SelectRequest(BaseModel):
    place_id: str


class LocationRequest(BaseModel):
    location: str


class TurnResponse(BaseModel):
    assistant_message: str
    stage: Stage
    analysis: Optional[LLMAnalysis] = None
    safety_advice: Optional[str] = None
    providers: list[Provider] = Field(default_factory=list)
    lead: Optional[Lead] = None
    email: Optional[EmailDraft] = None
    llm_fallback_used: bool = False
    state: SessionState
