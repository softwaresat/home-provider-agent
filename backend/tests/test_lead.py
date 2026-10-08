from app.lead import build_lead, draft_email
from app.models import (
    ContactInfo,
    Hazard,
    LLMAnalysis,
    LeadStatus,
    Provider,
    ServiceCategory,
    SessionState,
    Urgency,
)


def _session(**kwargs) -> SessionState:
    provider = Provider(
        place_id="p1",
        name="Austin Rooter",
        phone="512-555-0142",
        website="https://example.com",
        address="Austin, TX 78704",
        source="google_places",
        match_reasons=["Listing type matches plumbing"],
    )
    contact = ContactInfo(
        name="Alex Rivera",
        phone="512-555-0101",
        email="alex@example.com",
        service_address="1200 Barton Springs Rd",
        consent_to_share=True,
    )
    analysis = LLMAnalysis(
        service_category=ServiceCategory.plumbing,
        category_confidence=0.9,
        urgency=Urgency.same_day,
        urgency_reason="Active leak",
        problem_summary="Kitchen sink leaking onto the floor.",
        facts={"location": "kitchen sink", "active": "yes"},
        city="Austin",
        zip_code="78704",
    )
    data = dict(
        id="s1",
        analysis=analysis,
        city="Austin",
        zip_code="78704",
        providers=[provider],
        selected_place_id="p1",
        contact=contact,
    )
    data.update(kwargs)
    return SessionState(**data)


def test_complete_lead_and_email_draft():
    lead = build_lead(_session())
    assert lead.status == LeadStatus.complete
    assert lead.missing_required == []
    email = draft_email(lead)
    assert email is not None
    assert "kitchen sink leaking" in email.body.lower()
    assert "Austin" in email.subject or "78704" in email.subject
    assert "Alex Rivera" in email.body
    assert email.body.startswith("Hello Austin Rooter,")
    assert "Sincerely," in email.body
    assert "The service address is 1200 Barton Springs Rd." in email.body
    assert "I would like to request same-day plumbing service" in email.body
    assert "Please contact me at" in email.body
    assert "512-555-0101" in email.body or "(512) 555-0101" in email.body
    assert "Listing data comes from Google Places" not in email.body
    assert "draft only" not in email.body.lower()
    assert "leak_location" not in email.body
    assert "Hi " not in email.body
    assert "What I know" not in email.body
    assert "You can reach me at" not in email.body
    assert email.to_email is None
    assert email.mailto_url.startswith("mailto:?")
    assert "subject=" in email.mailto_url
    assert "body=" in email.mailto_url
    assert "Hello%20Austin%20Rooter" in email.mailto_url
    assert "Sincerely" in email.mailto_url
    assert email.mailto_disabled_reason is None
    assert email.fallback_url and email.fallback_url.startswith("tel:")
    assert "Call" in (email.fallback_label or "")


def _electrician() -> Provider:
    return Provider(
        place_id="p1",
        name="Austin Electric",
        phone="512-555-0142",
        website="https://example.com",
        address="Austin, TX 78704",
        primary_type="electrician",
        source="google_places",
    )


def test_email_does_not_dump_chat_or_form_fields():
    lead = build_lead(
        _session(
            providers=[_electrician()],
            analysis=LLMAnalysis(
                service_category=ServiceCategory.electrical,
                category_confidence=0.9,
                urgency=Urgency.emergency,
                problem_summary="My lights just went out i don't know what happened to my electricity yes I am safe",
                facts={
                    "lights_out": "yes, entire home",
                    "cause_known": "no",
                    "safety_signs_present": "confirmed yes (sparking, smoke, or burning smell)",
                    "power_loss_scope": "all lights",
                },
                city=None,
                zip_code="78717",
            ),
            city=None,
            zip_code="78717",
        )
    )
    email = draft_email(lead)
    assert email is not None
    body = email.body
    assert "Hello " in body
    assert "I would like to request emergency electrical service" in body
    assert "The power is out throughout the house." in body
    assert "I do not know what caused it." in body
    assert "yes I am safe" not in body
    assert "What I know" not in body
    assert "Lights out:" not in body
    assert "Safety signs present" not in body
    assert "Hi " not in body


def test_email_is_first_person_and_humanizes_facts():
    lead = build_lead(
        _session(
            providers=[_electrician()],
            analysis=LLMAnalysis(
                service_category=ServiceCategory.electrical,
                category_confidence=0.95,
                urgency=Urgency.emergency,
                problem_summary=(
                    "Living room ceiling fan sparked and stopped spinning. "
                    "The homeowner shut off power at the breaker, which stopped the sparking, "
                    "but a pungent burning smell is still present right now. "
                    "No visible smoke, scorch marks, or discoloration reported."
                ),
                facts={
                    "fixture": "ceiling fan",
                    "location": "living_room",
                    "room": "living room",
                    "safe": "yes",
                    "visible_damage": "None reported",
                    "smell": "Persistent, pungent",
                    "breaker": "Breaker off, sparking stopped",
                },
                zip_code="78717",
            ),
            city=None,
            zip_code="78717",
        )
    )
    body = draft_email(lead).body
    assert "living_room" not in body
    assert "The homeowner" not in body
    assert "None reported" not in body
    assert "The issue is at" not in body
    assert "I shut off" in body
    assert "I am safe" not in body or body.count("I am safe") <= 1
    assert body.count("It is in the living room") <= 1


def test_mailto_uses_provider_email():
    lead = build_lead(
        _session(
            providers=[
                Provider(
                    place_id="p1",
                    name="Austin Rooter",
                    phone="512-555-0142",
                    email="jobs@austinrooter.example",
                    website="https://example.com",
                    source="google_places",
                )
            ]
        )
    )
    email = draft_email(lead)
    assert email is not None
    assert email.to_email == "jobs@austinrooter.example"
    assert email.mailto_url.startswith("mailto:jobs@austinrooter.example?")
    assert "subject=" in email.mailto_url
    assert "body=" in email.mailto_url
    assert "Hello%20Austin%20Rooter" in email.mailto_url
    assert email.mailto_disabled_reason is None
    assert email.fallback_url and email.fallback_url.startswith("tel:")
    assert "Call" in (email.fallback_label or "")


def test_missing_service_address_is_incomplete():
    contact = ContactInfo(
        name="Alex Rivera",
        phone="512-555-0101",
        consent_to_share=True,
    )
    lead = build_lead(_session(contact=contact))
    assert lead.status == LeadStatus.incomplete
    assert "service_address" in lead.missing_required
    assert draft_email(lead) is None


def test_missing_consent_is_incomplete():
    contact = ContactInfo(
        name="Alex Rivera",
        phone="512-555-0101",
        consent_to_share=False,
    )
    lead = build_lead(_session(contact=contact))
    assert lead.status == LeadStatus.incomplete
    assert "consent_to_share" in lead.missing_required


def test_missing_provider_is_incomplete():
    lead = build_lead(_session(selected_place_id=None))
    assert lead.status == LeadStatus.incomplete
    assert "selected_provider" in lead.missing_required


def test_unrelated_listing_cannot_complete_lead():
    bakery = Provider(
        place_id="bakery-1",
        name="Austin Bakery",
        primary_type="bakery",
        phone="512-555-0199",
        website="https://bakery.example",
        source="google_places",
    )
    lead = build_lead(_session(providers=[bakery], selected_place_id="bakery-1"))
    assert lead.status == LeadStatus.incomplete
    assert "provider_trade_match" in lead.missing_required
    assert draft_email(lead) is None


def test_listing_without_contact_cannot_complete_lead():
    silent = Provider(
        place_id="p-silent",
        name="Austin Rooter",
        primary_type="plumber",
        source="google_places",
    )
    lead = build_lead(_session(providers=[silent], selected_place_id="p-silent"))
    assert lead.status == LeadStatus.incomplete
    assert "provider_contact" in lead.missing_required
    assert draft_email(lead) is None


def test_safety_escalated_status():
    lead = build_lead(_session(hazards=[Hazard.gas_leak], safety_cleared=False))
    assert lead.status == LeadStatus.safety_escalated


def test_contact_requires_phone_or_email():
    try:
        ContactInfo(name="Alex", consent_to_share=True)
        assert False, "expected validation error"
    except Exception as exc:
        assert "phone or email" in str(exc).lower()
