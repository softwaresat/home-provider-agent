"""Assemble a validated lead and a dispatch email draft. Never sent."""

from __future__ import annotations

import re
from urllib.parse import quote

from app import llm
from app.models import (
    ChatMessage,
    ContactInfo,
    EmailDraft,
    Lead,
    LeadStatus,
    LLMAnalysis,
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


def _reuse_problem_paragraph(body: str, lead: Lead) -> str | None:
    """Keep a previously drafted problem block when only envelope fields changed."""
    request = _request_sentence(lead)
    if request not in (body or ""):
        return None
    rest = body.split(request, 1)[1]
    if lead.service_address:
        marker = f"The service address is {lead.service_address}."
        if marker in rest:
            rest = rest.split(marker, 1)[0]
    if "Please contact me at" in rest:
        rest = rest.split("Please contact me at", 1)[0]
    if "Sincerely," in rest:
        rest = rest.split("Sincerely,", 1)[0]
    text = rest.strip()
    return text or None


def _problem_paragraph(
    lead: Lead,
    messages: list[ChatMessage] | None,
    previous: EmailDraft | None = None,
) -> str:
    if previous and previous.body:
        reused = _reuse_problem_paragraph(previous.body, lead)
        if reused:
            return reused
    paragraph, _used_fallback = llm.draft_problem_paragraph(
        messages or [],
        problem_summary=lead.problem_summary,
        facts=lead.problem_details,
    )
    return (paragraph or "").strip()


def _assemble_body(lead: Lead, provider: Provider, problem: str) -> str:
    name = lead.customer_name or "Homeowner"
    lines = [
        f"Hello {provider.name},",
        "",
        _request_sentence(lead),
    ]
    if problem:
        lines.extend(["", problem])
    if lead.service_address:
        lines.extend(["", f"The service address is {lead.service_address}."])

    contact_bits = []
    if lead.customer_phone:
        contact_bits.append(_format_phone(lead.customer_phone))
    if lead.customer_email:
        contact_bits.append(lead.customer_email)
    if contact_bits:
        joined = " or ".join(contact_bits)
        lines.extend(["", f"Please contact me at {joined} to schedule a visit."])
    lines.extend(["", "Sincerely,", name, ""])
    return "\n".join(lines)


def draft_email(
    lead: Lead,
    *,
    messages: list[ChatMessage] | None = None,
    previous: EmailDraft | None = None,
) -> EmailDraft | None:
    """Write a short professional service request from the intake chat. Never sent."""
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

    subject = f"{urgency} {category} service request - {location}"
    problem = _problem_paragraph(lead, messages, previous=previous)
    body = _assemble_body(lead, provider, problem)
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
        session.email = draft_email(
            session.lead,
            messages=session.messages,
            previous=session.email,
        )


def _stored_summary(session: SessionState) -> str:
    analysis = session.analysis
    return ((analysis.problem_summary if analysis else "") or "").strip()


def _set_summary(session: SessionState, text: str) -> None:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return
    if session.analysis is None:
        session.analysis = LLMAnalysis(problem_summary=cleaned)
    else:
        session.analysis.problem_summary = cleaned


def _fill_summary_from_chat(session: SessionState) -> None:
    """The chat is the problem. A blank stored summary should not block the lead."""
    if _stored_summary(session):
        return
    if not any(message.role == "user" and (message.content or "").strip() for message in session.messages):
        return
    facts = session.analysis.facts if session.analysis else None
    paragraph, used_fallback = llm.draft_problem_paragraph(
        session.messages,
        problem_summary="",
        facts=facts,
    )
    if used_fallback:
        session.llm_fallback_used = True
    _set_summary(session, paragraph)


def apply_lead(session: SessionState, contact: ContactInfo | None = None) -> None:
    if contact is not None:
        session.contact = contact
        written = (contact.problem_summary or "").strip()
        if written:
            _set_summary(session, written)
    # A selected listing with a blank summary is the stuck lead. The chat is
    # enough to write one; do not wait for the homeowner to retype it.
    if not _stored_summary(session) and (session.selected_place_id or session.contact):
        _fill_summary_from_chat(session)
    previous = session.email
    session.lead = build_lead(session)
    if session.lead.status == LeadStatus.complete:
        session.email = draft_email(
            session.lead,
            messages=session.messages,
            previous=previous,
        )
    else:
        session.email = None
