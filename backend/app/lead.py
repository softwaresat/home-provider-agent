"""Assemble a validated lead and a deterministic dispatch email draft."""

from __future__ import annotations

import re
from urllib.parse import quote

from app.models import (
    ContactInfo,
    EmailDraft,
    Lead,
    LeadStatus,
    Provider,
    ServiceCategory,
    SessionState,
    Urgency,
)
from app.ranking import is_contactable, is_trade_match, match_explanation
from app.safety import advice_for, is_escalation

URGENCY_LABEL = {
    Urgency.emergency: "Emergency",
    Urgency.same_day: "Same-day",
    Urgency.within_week: "Within a week",
    Urgency.flexible: "Flexible timing",
}


def selected_provider(session: SessionState) -> Provider | None:
    if not session.selected_place_id:
        return None
    for provider in session.providers:
        if provider.place_id == session.selected_place_id:
            return provider
    return None


def build_lead(session: SessionState) -> Lead:
    analysis = session.analysis
    contact = session.contact
    provider = selected_provider(session)
    summary = (analysis.problem_summary if analysis else "") or ""
    category = ServiceCategory.unknown
    if session.category_override:
        category = session.category_override
    elif analysis:
        category = analysis.service_category
    urgency = analysis.urgency if analysis else Urgency.flexible
    details = dict(analysis.facts) if analysis else {}
    city = session.city or (analysis.city if analysis else None)
    zip_code = session.zip_code or (analysis.zip_code if analysis else None)

    missing_required: list[str] = []
    missing_optional: list[str] = []

    if not summary.strip():
        missing_required.append("problem_summary")
    if category == ServiceCategory.unknown:
        missing_required.append("service_category")
    if not city and not zip_code:
        missing_required.append("city_or_zip")
    if not contact or not contact.name:
        missing_required.append("customer_name")
    if not contact or (not contact.phone and not contact.email):
        missing_required.append("customer_phone_or_email")
    if provider is None:
        missing_required.append("selected_provider")
    elif not is_trade_match(provider, category):
        missing_required.append("provider_trade_match")
    if provider is not None and not is_contactable(provider):
        missing_required.append("provider_contact")
    if not contact or not contact.consent_to_share:
        missing_required.append("consent_to_share")
    if not contact or not contact.service_address:
        missing_required.append("service_address")

    if not details:
        missing_optional.append("problem_details")

    status = LeadStatus.incomplete
    if is_escalation(session.hazards) and not session.safety_cleared:
        status = LeadStatus.safety_escalated
    elif not missing_required:
        status = LeadStatus.complete

    provider_contact = None
    explanation = ""
    if provider:
        bits = [provider.name]
        if provider.phone:
            bits.append(provider.phone)
        if provider.website:
            bits.append(provider.website)
        provider_contact = " · ".join(bits)
        explanation = match_explanation(provider)

    safety_notes = advice_for(session.hazards)
    if analysis and analysis.urgency_reason:
        extra = f"Urgency note: {analysis.urgency_reason}"
        safety_notes = f"{safety_notes} {extra}".strip() if safety_notes else extra

    return Lead(
        problem_summary=summary,
        service_category=category,
        urgency=urgency,
        problem_details=details,
        city=city,
        zip_code=zip_code,
        service_address=contact.service_address if contact else None,
        customer_name=contact.name if contact else None,
        customer_phone=contact.phone if contact else None,
        customer_email=contact.email if contact else None,
        selected_provider=provider,
        provider_contact_details=provider_contact,
        safety_notes=safety_notes,
        consent_to_share=bool(contact and contact.consent_to_share),
        status=status,
        missing_required=missing_required,
        missing_optional=missing_optional,
        provider_match_explanation=explanation,
    )


_SKIP_DETAIL_VALUES = {
    "",
    "unknown",
    "none",
    "n/a",
    "na",
    "null",
    "not provided",
}
_YES = {"yes", "true", "y"}
_NO = {"no", "false", "n"}
_CHAT_MARKERS = re.compile(
    r"\b(yes i am safe|idk|lol|idk what happened|i don't know what happened to my)\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CATEGORY_PHRASE = {
    ServiceCategory.plumbing: "plumbing",
    ServiceCategory.hvac: "HVAC",
    ServiceCategory.electrical: "electrical",
    ServiceCategory.roofing: "roofing",
    ServiceCategory.water_damage: "water damage",
    ServiceCategory.pest_control: "pest control",
    ServiceCategory.appliance_repair: "appliance repair",
    ServiceCategory.handyman: "handyman",
    ServiceCategory.unknown: "home service",
}


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(key).lower()).strip()


def _humanize_text(text: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", str(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def _human_value(value: object) -> str | None:
    text = _humanize_text(str(value))
    lowered = text.lower()
    if lowered in _SKIP_DETAIL_VALUES:
        return None
    return text


def _is_useless_fragment(text: str) -> bool:
    lowered = text.lower().strip(" .")
    if lowered in _SKIP_DETAIL_VALUES or lowered in {"none reported", "not reported", "n/a"}:
        return True
    if re.search(r"\b(is|are|was|were|have|has|had|my|the|i|it)\b", lowered):
        return False
    words = re.findall(r"[a-z]+", lowered)
    return len(words) <= 4


def _to_homeowner_voice(text: str) -> str:
    t = _humanize_text(text)
    substitutions = (
        (r"\b[Tt]he homeowner\b", "I"),
        (r"\b[Tt]he customer\b", "I"),
        (r"\b[Tt]he occupant[s]?\b", "I"),
        (r"\bI has\b", "I have"),
        (r"\bI is\b", "I am"),
        (r"\bI was reported\b", "I"),
        (r"\bEveryone at the property is currently safe\b", "I am safe"),
        (r"\bNo visible ([^.]+?) reported\b", r"I do not see \1"),
        (r"\breported\.?\s*$", "."),
    )
    for pattern, repl in substitutions:
        t = re.sub(pattern, repl, t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+\.", ".", t)
    return t


def _as_homeowner_summary(text: str) -> str:
    t = _to_homeowner_voice(text)
    if not t:
        return ""
    return _finish_sentence(t)


def _looks_like_chat(text: str) -> bool:
    stripped = " ".join((text or "").split())
    if not stripped:
        return True
    if _CHAT_MARKERS.search(stripped):
        return True
    if stripped[:1].islower():
        return True
    if len(stripped) > 70 and not re.search(r"[.!?]", stripped):
        return True
    return False


def _finish_sentence(text: str) -> str:
    stripped = " ".join((text or "").split())
    if not stripped:
        return ""
    if stripped[:1].islower():
        stripped = stripped[:1].upper() + stripped[1:]
    if stripped[-1] not in ".!?":
        stripped += "."
    return stripped


def _format_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return (raw or "").strip()


def _extract_email(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if text.lower().startswith("mailto:"):
            text = text[7:].split("?", 1)[0]
        match = _EMAIL_RE.search(text)
        if match:
            return match.group(0)
    return None


def _tel_url(phone: str) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 7:
        return None
    if len(digits) == 10:
        return f"tel:+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"tel:+{digits}"
    return f"tel:{digits}"


def _mailto_url(address: str | None, subject: str, body: str) -> str:
    """Open the user's mail app with this exact draft. Empty To is valid."""
    to = address or ""
    return (
        f"mailto:{to}"
        f"?subject={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def _call_or_listing_action(provider: Provider) -> tuple[str | None, str | None]:
    """Call via tel: when a phone exists. Never sends anything from the app."""
    if provider.phone:
        tel = _tel_url(provider.phone)
        if tel:
            return tel, f"Call {_format_phone(provider.phone)}"
    if provider.website:
        return provider.website, "Open provider website"
    if provider.maps_url:
        return provider.maps_url, "Open Google Maps listing"
    return None, None


def _location_phrase(lead: Lead) -> str:
    if lead.city and lead.zip_code:
        return f"{lead.city} {lead.zip_code}"
    return lead.city or lead.zip_code or "the listed area"


def _request_sentence(lead: Lead) -> str:
    category = _CATEGORY_PHRASE.get(lead.service_category, "home service")
    location = _location_phrase(lead)
    if lead.urgency == Urgency.emergency:
        timing = f"emergency {category} service"
    elif lead.urgency == Urgency.same_day:
        timing = f"same-day {category} service"
    elif lead.urgency == Urgency.within_week:
        timing = f"{category} service this week"
    else:
        timing = f"{category} service"
    return f"I would like to request {timing} at my home in {location}."


def _content_fingerprint(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(
        r"^(the issue is at the|it is in the|it is at the|this is in the)\s+",
        "",
        lowered,
    )
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _fact_sentence(key: str, value: str) -> str | None:
    key_n = _norm_key(key)
    val = _humanize_text(value)
    val_l = val.lower()
    if any(token in key_n for token in ("safety sign", "hazard", "next question")):
        return None
    if val_l.startswith("confirmed"):
        return None
    if val_l in {"none reported", "not reported"}:
        return None

    if "cause" in key_n:
        if val_l in _NO or "unknown" in val_l:
            return "I do not know what caused it."
        if val_l not in _YES:
            return _finish_sentence(f"I think the cause is {val_l}")
        return None

    if any(token in key_n for token in ("lights out", "power loss", "power out", "outage")):
        if any(token in val_l for token in ("entire", "whole", "all", "throughout")):
            return "The power is out throughout the house."
        if val_l in _YES:
            return "The lights are out."
        if val_l not in _NO:
            return _finish_sentence(f"The outage involves {val_l}")
        return None

    if any(token in key_n for token in ("active", "still leaking", "still dripping")):
        if val_l in _YES:
            return "It is still leaking."
        if val_l in _NO:
            return "The leak has stopped for now."
        return None

    if key_n in {"location", "leak location", "fixture", "area", "room"}:
        if val_l in _YES | _NO:
            return None
        return _finish_sentence(f"It is in the {val_l}")

    if "shut" in key_n and "off" in key_n:
        if val_l in _YES:
            return "I shut off the water."
        if val_l in _NO:
            return "I have not shut off the water."
        return None

    if key_n in {"appliance", "unit"}:
        if val_l in _YES | _NO:
            return None
        return _finish_sentence(f"The appliance is the {val_l}")

    if "safe" in key_n:
        if val_l in _YES:
            return "I am safe."
        return None

    if val_l in _YES | _NO:
        return None
    if _is_useless_fragment(val):
        return None
    voiced = _to_homeowner_voice(val)
    if not re.search(r"\b(is|are|was|were|have|has|had|i|my|it)\b", voiced.lower()):
        return None
    return _finish_sentence(voiced)


def _already_covered(sentence: str, blob: str) -> bool:
    fp = _content_fingerprint(sentence)
    if not fp:
        return True
    if fp in _content_fingerprint(blob):
        return True
    tokens = [tok for tok in fp.split() if len(tok) > 3]
    if tokens and all(tok in blob for tok in tokens):
        return True
    return False


def _problem_paragraph(lead: Lead) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    summary = (lead.problem_summary or "").strip()
    if summary and not _looks_like_chat(summary):
        polished = _as_homeowner_summary(summary)
        if polished:
            parts.append(polished)
            seen.add(_content_fingerprint(polished))

    blob = " ".join(parts).lower()
    for key, value in (lead.problem_details or {}).items():
        readable = _human_value(value)
        if not readable:
            continue
        sentence = _fact_sentence(key, readable)
        if not sentence:
            continue
        fingerprint = _content_fingerprint(sentence)
        if fingerprint in seen or _already_covered(sentence, blob):
            continue
        seen.add(fingerprint)
        parts.append(sentence)
        blob = f"{blob} {sentence.lower()}"

    if not parts:
        return "I need a technician at the home."
    return " ".join(parts)


def draft_email(lead: Lead) -> EmailDraft | None:
    """Write a short professional service request. Never sent."""
    if lead.status != LeadStatus.complete:
        return None
    provider = lead.selected_provider
    if provider is None:
        return None
    if not (lead.service_address or "").strip():
        return None
    to_contact = provider.phone or provider.website or provider.maps_url or "listed contact not available"
    location = _location_phrase(lead)
    category = _CATEGORY_PHRASE.get(lead.service_category, "home service")
    urgency = URGENCY_LABEL.get(lead.urgency, lead.urgency.value)
    name = lead.customer_name or "Homeowner"

    subject = f"{urgency} {category} service request - {location}"

    lines = [
        f"Hello {provider.name},",
        "",
        _request_sentence(lead),
        "",
        _problem_paragraph(lead),
    ]
    if lead.service_address:
        lines.extend(["", f"The service address is {lead.service_address}."])

    contact_bits = []
    if lead.customer_phone:
        contact_bits.append(_format_phone(lead.customer_phone))
    if lead.customer_email:
        contact_bits.append(lead.customer_email)
    if contact_bits:
        joined = " or ".join(contact_bits)
        lines.extend(
            [
                "",
                f"Please contact me at {joined} to schedule a visit.",
            ]
        )
    lines.extend(["", "Sincerely,", name, ""])
    body = "\n".join(lines)
    to_email = _extract_email(provider.email, provider.website, provider.phone)
    fallback_url, fallback_label = _call_or_listing_action(provider)

    return EmailDraft(
        to_name=provider.name,
        to_contact=to_contact,
        to_email=to_email,
        subject=subject,
        body=body,
        mailto_url=_mailto_url(to_email, subject, body),
        mailto_disabled_reason=None,
        fallback_url=fallback_url,
        fallback_label=fallback_label,
    )


def refresh_email(session: SessionState) -> None:
    if session.lead and session.lead.status == LeadStatus.complete:
        session.email = draft_email(session.lead)


def apply_lead(session: SessionState, contact: ContactInfo | None = None) -> None:
    if contact is not None:
        session.contact = contact
    session.lead = build_lead(session)
    if session.lead.status == LeadStatus.complete:
        session.email = draft_email(session.lead)
    else:
        session.email = None
