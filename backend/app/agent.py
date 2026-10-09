"""Deterministic conversation orchestrator. The LLM proposes; this module decides."""

from __future__ import annotations

import re
from typing import Optional

from app import intake_catalog, lead as lead_mod
from app import llm, places, ranking, safety
from app.models import (
    CAUTION_HAZARDS,
    ChatMessage,
    ContactInfo,
    LLMAnalysis,
    ServiceCategory,
    SessionState,
    Stage,
    Urgency,
)

MAX_FOLLOWUPS = 8
CONF_THRESHOLD = 0.6
GREETING = (
    "Hi - add your city or ZIP in the location field at the top, then describe "
    "the home problem here. I will ask follow-up questions as needed and show "
    "nearby listings from Google. Nothing is sent to a business unless you consent."
)
LOCATION_QUESTION = (
    "Add your city or ZIP in the location field at the top of the page. "
    "You do not need to type it in the chat."
)
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
CITY_STATE_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:[\s-][A-Z][a-zA-Z]+){0,2}),\s*([A-Z]{2})\b"
)
URGENCY_RANK = {
    Urgency.flexible: 0,
    Urgency.within_week: 1,
    Urgency.same_day: 2,
    Urgency.emergency: 3,
}


def create_session(session_id: str) -> SessionState:
    session = SessionState(id=session_id)
    session.messages.append(ChatMessage(role="assistant", content=GREETING))
    return session


def effective_category(session: SessionState) -> ServiceCategory:
    if session.category_override:
        return session.category_override
    if session.analysis:
        return session.analysis.service_category
    return ServiceCategory.unknown


def has_location(session: SessionState) -> bool:
    return bool(session.city or session.zip_code or session.location_query)


def blocked_for_safety(session: SessionState) -> bool:
    return safety.is_escalation(session.hazards) and not session.safety_cleared


def location_label(session: SessionState) -> str:
    if session.location_query:
        return session.location_query
    bits = [bit for bit in [session.city, session.zip_code] if bit]
    return ", ".join(bits)


def category_ready(session: SessionState) -> bool:
    category = effective_category(session)
    if category == ServiceCategory.unknown:
        return False
    if session.category_override:
        return True
    confidence = session.analysis.category_confidence if session.analysis else 0.0
    return confidence >= CONF_THRESHOLD


def _append_assistant(session: SessionState, text: str) -> None:
    session.messages.append(ChatMessage(role="assistant", content=text))


def _safety_copy(session: SessionState, user_text: str, mode: str) -> str:
    """Python owns the hold. DeepSeek only writes the message."""
    reply, used_fallback = llm.safety_reply(user_text, session.hazards, mode=mode)
    if used_fallback:
        session.llm_fallback_used = True
    session.safety_advice = reply
    return reply


def _extract_location(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    zip_code = None
    match = ZIP_RE.search(text or "")
    if match:
        zip_code = match.group(1)
    city = None
    query = None
    cs = CITY_STATE_RE.search(text or "")
    if cs:
        city = re.sub(r"\s+", " ", cs.group(1)).strip(" ,")
        query = f"{city}, {cs.group(2)}"
        if zip_code:
            query = f"{query} {zip_code}"
    elif zip_code:
        query = zip_code
    return city, zip_code, query


def _apply_location(session: SessionState, city: Optional[str], zip_code: Optional[str], query: Optional[str]) -> None:
    incoming_city = (city or "").strip() or None
    incoming_zip = (zip_code or "").strip() or None
    if incoming_city:
        city_changed = bool(session.city) and incoming_city.lower() != session.city.lower()
        session.city = incoming_city
        if city_changed and not incoming_zip:
            session.zip_code = None
    if incoming_zip:
        session.zip_code = incoming_zip
    if query:
        session.location_query = query
    else:
        session.location_query = location_label(session)


def _prefer_problem_summary(old: str, incoming: str) -> str:
    """Keep a detailed summary when a later model turn returns a stub."""
    old = (old or "").strip()
    incoming = (incoming or "").strip()
    if not incoming:
        return old
    if not old:
        return incoming
    old_words = len(re.findall(r"[a-z0-9]+", old.lower()))
    incoming_words = len(re.findall(r"[a-z0-9]+", incoming.lower()))
    if incoming_words <= 4 and incoming_words < old_words:
        return old
    return incoming


def merge_analysis(session: SessionState, incoming: LLMAnalysis) -> None:
    # Header/explicit location wins. Do not re-merge stale city/ZIP from chat or the LLM.
    if not (session.city or session.zip_code or session.location_query):
        city, zip_code, query = _extract_location(
            " ".join(m.content for m in session.messages if m.role == "user")
        )
        if incoming.city:
            city = incoming.city
        if incoming.zip_code:
            zip_code = incoming.zip_code
            if not query:
                query = incoming.zip_code
        _apply_location(session, city, zip_code, query)

    if session.analysis is None:
        merged = incoming.model_copy(deep=True)
        merged.city = session.city
        merged.zip_code = session.zip_code
        session.analysis = merged
        return

    old = session.analysis
    if incoming.service_category != ServiceCategory.unknown:
        if (
            old.service_category == ServiceCategory.unknown
            or incoming.category_confidence > old.category_confidence
        ):
            old.service_category = incoming.service_category
            old.category_confidence = incoming.category_confidence
    if URGENCY_RANK[incoming.urgency] >= URGENCY_RANK[old.urgency]:
        old.urgency = incoming.urgency
        if incoming.urgency_reason:
            old.urgency_reason = incoming.urgency_reason
    if incoming.problem_summary:
        old.problem_summary = _prefer_problem_summary(
            old.problem_summary, incoming.problem_summary
        )
    for key, value in incoming.facts.items():
        if value:
            old.facts[key] = value
    old.city = session.city
    old.zip_code = session.zip_code
    old.missing_details = incoming.missing_details
    old.next_question = incoming.next_question
    old.dispatch_ready = bool(incoming.dispatch_ready)
    incoming_hazards = {h.value: h for h in incoming.hazards}
    for hazard in session.hazards:
        incoming_hazards[hazard.value] = hazard
    old.hazards = list(incoming_hazards.values())


def _normalize_question(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).strip()


def _is_redundant(question: str, asked: list[str]) -> bool:
    current = set(_normalize_question(question).split())
    if not current:
        return True
    for previous in asked:
        prev = set(_normalize_question(previous).split())
        if not prev:
            continue
        overlap = len(current & prev) / max(len(current), 1)
        if overlap >= 0.6:
            return True
    return False


_LOCATION_QUESTION_RE = re.compile(
    r"\b("
    r"zip(?:\s*code)?"
    r"|city"
    r"|what area"
    r"|which area"
    r"|where are you"
    r"|your location"
    r"|what (?:city|town|zip)"
    r"|which (?:city|town)"
    r")\b",
    re.IGNORECASE,
)
_CONTACT_QUESTION_RE = re.compile(
    r"\b("
    r"your name|full name|what(?:'s| is) your name"
    r"|phone number|phone or email|your phone|best number|callback"
    r"|e-?mail address|your e-?mail"
    r"|contact (?:number|info|details)"
    r"|service address|street address|home address|mailing address"
    r")\b",
    re.IGNORECASE,
)


def _question_looks_like_location(question: str) -> bool:
    """True for city/ZIP prompts. Does not match 'where in the home' dispatch questions."""
    return bool(_LOCATION_QUESTION_RE.search(question or ""))


def _question_looks_like_contact(question: str) -> bool:
    """True for name/phone/email/address — those belong on the Lead tab form."""
    return bool(_CONTACT_QUESTION_RE.search(question or ""))


def _is_forbidden_chat_question(question: str) -> bool:
    return _question_looks_like_location(question) or _question_looks_like_contact(question)


def _usable_question(question: Optional[str], asked: list[str]) -> Optional[str]:
    if not question or _is_forbidden_chat_question(question):
        return None
    if _is_redundant(question, asked):
        return None
    return question


def _next_followup(session: SessionState) -> Optional[str]:
    """Next chat question, or None when intake should search.

    Policy: ask only a usable LLM question that could still change dispatch.
    Do not inspect homeowner wording. Stop when dispatch_ready, the proposed
    question is null/unusable, the question is redundant or forbidden, or
    MAX_FOLLOWUPS. Once a trade is known, never invent `_fallback_question`.
    Keyword fallback is only when the category is still unknown and DeepSeek
    is down.
    """
    if session.questions_asked >= MAX_FOLLOWUPS:
        return None
    if session.analysis and session.analysis.dispatch_ready:
        return None

    proposed = _usable_question(
        session.analysis.next_question if session.analysis else None,
        session.asked_questions,
    )
    if proposed:
        return proposed
    if (
        session.llm_fallback_used
        and effective_category(session) == ServiceCategory.unknown
    ):
        return _usable_question(
            llm._fallback_question(ServiceCategory.unknown),
            session.asked_questions,
        )
    return None


def _ask_followup(session: SessionState, question: str, spoken: Optional[str] = None) -> None:
    session.questions_asked += 1
    session.asked_questions.append(question)
    session.stage = Stage.gathering
    _append_assistant(session, spoken if spoken is not None else question)


def _prompt_location_field(session: SessionState, preface: str = "") -> None:
    session.stage = Stage.need_location
    session.location_question_asked = True
    _append_assistant(session, (preface + LOCATION_QUESTION).strip())


def _providers_message(session: SessionState, preface: str) -> str:
    top = session.providers[:3]
    if not top:
        extra = session.search_error or "No matching listings came back."
        return (
            f"{preface} {extra} You can try another city or ZIP in the Providers panel. "
            "I will not invent businesses."
        ).strip()
    source = "Google Places" if session.search_source == "google_places" else "recorded fallback data"
    lines = [
        f"{preface} Here are up to three listings from {source}. "
        "A listing existing on Google is not confirmation of service area, availability, or licensing.",
        "",
    ]
    for index, provider in enumerate(top, start=1):
        bits = [f"{index}. {provider.name}"]
        if provider.address:
            bits.append(provider.address)
        elif provider.is_service_area_business:
            bits.append("service-area business (address may be hidden)")
        if provider.rating is not None:
            reviews = provider.review_count or 0
            bits.append(f"Google rating {provider.rating:.1f} ({reviews} reviews)")
        if provider.phone:
            bits.append(provider.phone)
        lines.append(" — ".join(bits))
        if provider.match_reasons:
            lines.append("   Why: " + "; ".join(provider.match_reasons[:3]))
    lines.append("")
    lines.append("Select a provider in the right-hand panel when you want to continue. I will not contact them.")
    return "\n".join(lines)


def apply_location_string(session: SessionState, location: str) -> None:
    """Replace city/ZIP from an explicit location field. Do not keep stale parts."""
    text = (location or "").strip()
    if not text:
        return
    city, zip_code, query = _extract_location(text)
    if not city and not zip_code:
        if "," in text:
            city = text.split(",", 1)[0].strip() or None
            query = text
        else:
            zip_only = ZIP_RE.fullmatch(text)
            if zip_only:
                zip_code = zip_only.group(1)
                query = zip_code
            else:
                city = text
                query = text
    session.city = city
    session.zip_code = zip_code
    session.location_query = query or text
    if session.analysis:
        session.analysis.city = session.city
        session.analysis.zip_code = session.zip_code


def _run_search(session: SessionState, location: Optional[str] = None) -> None:
    if location:
        apply_location_string(session, location)

    loc = location_label(session) or (location or "").strip()
    if not loc:
        session.stage = Stage.need_location
        session.search_error = "Location is required before searching."
        return

    category = effective_category(session)
    if category == ServiceCategory.unknown:
        category = ServiceCategory.handyman

    urgency = session.analysis.urgency.value if session.analysis else None
    session.stage = Stage.searching
    providers, source, error = places.search_text(category, loc, urgency)
    ranked = ranking.rank_providers(providers, category, session.city, session.zip_code)
    session.providers = ranked
    session.search_source = source
    session.search_error = error
    if ranked:
        session.stage = Stage.showing_providers
    else:
        session.stage = Stage.no_results


def _maybe_search_and_reply(session: SessionState, preface: str) -> None:
    _run_search(session)
    _append_assistant(session, _providers_message(session, preface))


def _continue_intake(session: SessionState) -> None:
    if blocked_for_safety(session):
        return

    if session.selected_place_id:
        session.stage = Stage.collecting_contact
        lead_mod.apply_lead(session)
        _append_assistant(
            session,
            "I have a provider selected. On the Lead tab, add your name, a phone or email, "
            "and the service address, then check the consent box so I can draft the email. "
            "Nothing is sent to the business.",
        )
        return

    at_cap = session.questions_asked >= MAX_FOLLOWUPS
    question = _next_followup(session)

    if (
        question
        and _question_looks_like_location(question)
        and not has_location(session)
    ):
        _prompt_location_field(session)
        return

    if question:
        spoken = question
        if (
            not category_ready(session)
            and session.analysis
            and session.analysis.service_category != ServiceCategory.unknown
        ):
            label = session.analysis.service_category.value.replace("_", " ")
            spoken = f"This sounds like a {label} issue. {question}"
        _ask_followup(session, question, spoken)
        return

    if not has_location(session):
        preface = "I will keep the category as a best estimate for now. " if at_cap else ""
        _prompt_location_field(session, preface)
        return

    if effective_category(session) == ServiceCategory.unknown:
        session.stage = Stage.gathering
        return

    if at_cap:
        preface = "I will search with the details collected so far rather than asking more questions."
    elif category_ready(session):
        preface = "I have enough to search locally."
    else:
        preface = "I have enough overlapping detail to search."
    _maybe_search_and_reply(session, preface)


def handle_user_message(session: SessionState, text: str) -> SessionState:
    prior_stage = session.stage
    prior_category = effective_category(session)
    session.messages.append(ChatMessage(role="user", content=text))

    rule_hazards = safety.detect_hazards(text)
    if safety.is_escalation(rule_hazards):
        session.safety_cleared = False
        merged_hazards = {h.value: h for h in (session.hazards + rule_hazards)}
        session.hazards = list(merged_hazards.values())
        session.stage = Stage.safety_escalated
        lead_mod.apply_lead(session)
        _append_assistant(session, _safety_copy(session, text, "escalate"))
        return session

    if prior_stage == Stage.lead_ready:
        _append_assistant(
            session,
            "The lead is already complete. You can copy the draft email from the Lead tab. "
            "Start a new lead if the problem changed. Nothing has been sent.",
        )
        return session

    guidance = intake_catalog.turn_guidance(
        effective_category(session),
        facts=session.analysis.facts if session.analysis else None,
        asked=session.asked_questions,
    )
    analysis, used_fallback = llm.analyze(
        session.messages,
        intake_guidance=guidance,
        safety_hold=prior_stage == Stage.safety_escalated,
    )
    if used_fallback:
        session.llm_fallback_used = True

    # Hold is this-turn detect_hazards. Release is this-turn meaning from
    # DeepSeek (safety_confirmed), not historical hazard labels.
    if prior_stage == Stage.safety_escalated and analysis.safety_confirmed:
        session.safety_cleared = True
        session.stage = Stage.gathering
        _append_assistant(session, _safety_copy(session, text, "resume"))

    merged_hazards = {h.value: h for h in (session.hazards + rule_hazards + analysis.hazards)}
    session.hazards = list(merged_hazards.values())
    analysis.hazards = session.hazards
    merge_analysis(session, analysis)

    if any(h in CAUTION_HAZARDS for h in session.hazards) and session.analysis:
        if URGENCY_RANK[session.analysis.urgency] < URGENCY_RANK[Urgency.emergency]:
            session.analysis.urgency = Urgency.emergency
            session.analysis.urgency_reason = (
                "Electrical or water-near-electrical hazard reported; treating as emergency."
            )

    if blocked_for_safety(session):
        session.stage = Stage.safety_escalated
        lead_mod.apply_lead(session)
        _append_assistant(session, _safety_copy(session, text, "escalate"))
        return session

    if any(h in CAUTION_HAZARDS for h in rule_hazards):
        _safety_copy(session, text, "caution")

    if prior_stage == Stage.collecting_contact:
        lead_mod.apply_lead(session)
        lead = session.lead
        if lead and lead.missing_required:
            _append_assistant(session, _incomplete_lead_reply(lead))
        else:
            _append_assistant(
                session,
                "Use the Lead tab form for name, contact, address, and the consent checkbox. "
                "I cannot take those from chat. Nothing is sent to the business.",
            )
        return session

    if prior_stage in {Stage.showing_providers, Stage.no_results}:
        new_category = effective_category(session)
        category_changed = (
            new_category != ServiceCategory.unknown
            and new_category != prior_category
        )
        described_problem = len(text.strip()) >= 20 and category_ready(session)
        if category_changed or described_problem or prior_stage == Stage.no_results:
            if has_location(session) and category_ready(session):
                _maybe_search_and_reply(
                    session,
                    "Got it — searching for a better match to this problem.",
                )
                return session
            _continue_intake(session)
            return session
        if prior_stage == Stage.showing_providers:
            _append_assistant(
                session,
                "Select a provider from the list when you are ready, or change filters in the "
                "Providers panel to search again. I will not contact anyone.",
            )
            return session

    if session.stage == Stage.need_location:
        if has_location(session):
            if effective_category(session) == ServiceCategory.unknown:
                _continue_intake(session)
                return session
            _maybe_search_and_reply(session, "Thanks — searching with that location.")
            return session
        session.location_question_asked = True
        _append_assistant(session, LOCATION_QUESTION)
        return session

    _continue_intake(session)
    return session


def handle_location(session: SessionState, location: str) -> SessionState:
    """Set city/ZIP from the dedicated field. Do not ask for it in chat."""
    previous = location_label(session)
    apply_location_string(session, location)
    if blocked_for_safety(session):
        return session
    if not has_location(session):
        return session
    changed = location_label(session) != previous
    # Do not abort in-progress intake when the header location is filled.
    # Search when we were blocked on location, or when the user changes location
    # after listings are already on screen.
    ready_to_search = category_ready(session) and session.stage in {
        Stage.need_location,
        Stage.no_results,
        Stage.showing_providers,
        Stage.searching,
    }
    if ready_to_search and (changed or session.stage == Stage.need_location):
        _maybe_search_and_reply(session, "Using the location from the field at the top.")
        return session
    if session.stage == Stage.need_location:
        session.stage = Stage.gathering
        _append_assistant(session, "Location saved. You can keep going in the chat.")
    return session


def handle_search(
    session: SessionState,
    category: Optional[ServiceCategory] = None,
    location: Optional[str] = None,
) -> SessionState:
    if blocked_for_safety(session):
        _append_assistant(
            session,
            session.safety_advice
            or "Please handle the safety situation first. Confirm you are safe before I search.",
        )
        return session
    if category:
        session.category_override = category
    _run_search(session, location=location)
    _append_assistant(session, _providers_message(session, "Updated listings based on your filters."))
    return session


_MISSING_LABELS = {
    "consent_to_share": "your consent to put contact details in a draft email",
    "selected_provider": "a provider selected from the list",
    "provider_trade_match": "a provider whose listing matches this trade",
    "provider_contact": "a provider listing with a phone, website, or Maps link",
    "customer_name": "your name",
    "customer_phone_or_email": "a phone number or email",
    "service_address": "the service address",
    "city_or_zip": "city or ZIP in the location field",
    "problem_summary": "a short description of the problem",
    "service_category": "a service category",
}


def _incomplete_lead_reply(lead) -> str:
    """Ask for what is actually missing. Do not always demand consent."""
    missing = list(getattr(lead, "missing_required", None) or [])
    need_consent = "consent_to_share" in missing
    other_keys = [key for key in missing if key != "consent_to_share"]
    others = [_MISSING_LABELS.get(key, key.replace("_", " ")) for key in other_keys]
    if need_consent and not others:
        return (
            "I can draft the email as soon as you check the consent box on the Lead tab. "
            "That box is how you agree to include your name, contact, and service address "
            "in the draft. Nothing is sent to the business."
        )
    if need_consent:
        listed = ", ".join(others)
        return (
            f"To draft the email I still need {listed}, and your consent. "
            "Fill those on the Lead tab, check the consent box, then click "
            "Build lead + draft email. Nothing is sent to the business."
        )
    if others:
        listed = ", ".join(others)
        return (
            f"I still need {listed} before I can draft the email. "
            "Update the Lead tab or pick a matching listing, then try again. "
            "Nothing is sent to the business."
        )
    return (
        "The lead is still incomplete. Finish the contact form on the Lead tab. "
        "Nothing is sent to the business."
    )


def handle_select(session: SessionState, place_id: str) -> SessionState:
    if blocked_for_safety(session):
        _append_assistant(
            session,
            "I am not collecting a lead during a safety emergency. Confirm you are safe first.",
        )
        return session
    match = next((p for p in session.providers if p.place_id == place_id), None)
    if match is None:
        raise KeyError(f"Provider {place_id} is not in the current result list")
    session.selected_place_id = place_id
    session.stage = Stage.collecting_contact
    lead_mod.apply_lead(session)
    why = ranking.match_explanation(match)
    category = effective_category(session)
    if not ranking.is_trade_match(match, category) or not ranking.is_contactable(match):
        _append_assistant(
            session,
            f"Selected {match.name} as a Google listing. {why} "
            "This is a provisional pick: trade match or a phone/website is missing, "
            "so the lead cannot be marked complete until you choose a relevant, "
            "contactable provider. Availability is unconfirmed either way.",
        )
        return session
    _append_assistant(
        session,
        f"Selected {match.name}. {why} "
        "A Google listing is not a booking or a promise they will take the job. "
        "On the Lead tab, add your name, a phone or email, and the service address, "
        "then check the consent box. That is the ask: I will not draft the email until "
        "you consent. Nothing is sent to the business.",
    )
    return session


def handle_contact(session: SessionState, contact: ContactInfo) -> SessionState:
    if blocked_for_safety(session):
        session.contact = contact
        lead_mod.apply_lead(session)
        _append_assistant(
            session,
            "Contact details were saved, but this session is safety-escalated. "
            "I will not treat it as a dispatchable lead.",
        )
        return session
    lead_mod.apply_lead(session, contact)
    lead = session.lead
    assert lead is not None
    if lead.status.value == "complete":
        session.stage = Stage.lead_ready
        _append_assistant(
            session,
            "Lead is complete. Review the structured lead and draft email on the Lead tab. "
            "Nothing has been sent to the provider.",
        )
    else:
        session.stage = Stage.collecting_contact
        _append_assistant(session, _incomplete_lead_reply(lead))
    return session
