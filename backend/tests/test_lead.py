from app.lead import apply_lead, build_lead, draft_email
from app.models import (
    ChatMessage,
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


def test_blank_summary_is_taken_from_the_chat_when_the_lead_is_built(monkeypatch):
    def fake_draft(history, problem_summary="", facts=None):
        assert any(message.role == "user" for message in history)
        if problem_summary:
            return problem_summary, False
        return (
            "Water is leaking in the house. I do not know where it is coming from, and I am in a hurry.",
            False,
        )

    monkeypatch.setattr("app.llm.draft_problem_paragraph", fake_draft)
    session = _session(
        messages=[
            ChatMessage(role="user", content="There is a plumbing leak and I do not know where."),
            ChatMessage(role="user", content="I meant hurry."),
            ChatMessage(role="user", content="I'm not sure"),
        ],
        analysis=LLMAnalysis(
            service_category=ServiceCategory.plumbing,
            category_confidence=0.85,
            urgency=Urgency.flexible,
            problem_summary="",
            city="Austin",
            zip_code="78704",
        ),
        contact=None,
    )
    apply_lead(
        session,
        ContactInfo(
            name="Alex Rivera",
            phone="512-555-0101",
            service_address="1200 Barton Springs Rd",
            consent_to_share=True,
        ),
    )
    assert session.lead is not None
    assert session.lead.status == LeadStatus.complete
    assert "leaking" in session.lead.problem_summary.lower()
    assert session.email is not None
    assert "leaking" in session.email.body.lower()


def test_selected_provider_fills_a_blank_summary_without_a_new_contact(monkeypatch):
    monkeypatch.setattr(
        "app.llm.draft_problem_paragraph",
        lambda *_a, **_k: ("Water is leaking through the house and I do not know the source.", False),
    )
    session = _session(
        messages=[ChatMessage(role="user", content="There is a leak and I do not know where.")],
        analysis=LLMAnalysis(
            service_category=ServiceCategory.plumbing,
            category_confidence=0.85,
            problem_summary="",
            city="Austin",
            zip_code="78704",
        ),
    )
    apply_lead(session)
    assert session.lead is not None
    assert "leaking" in session.lead.problem_summary.lower()
    assert session.lead.status == LeadStatus.complete


def test_typed_problem_replaces_a_blank_summary(monkeypatch):
    def fake_draft(_history, problem_summary="", facts=None):
        assert problem_summary == "The kitchen sink has been leaking under the cabinet."
        return problem_summary, False

    monkeypatch.setattr("app.llm.draft_problem_paragraph", fake_draft)
    session = _session(
        analysis=LLMAnalysis(
            service_category=ServiceCategory.plumbing,
            category_confidence=0.85,
            problem_summary="",
            city="Austin",
            zip_code="78704",
        ),
        contact=None,
        messages=[ChatMessage(role="user", content="The sink is leaking.")],
    )
    apply_lead(
        session,
        ContactInfo(
            name="Alex Rivera",
            phone="512-555-0101",
            service_address="1200 Barton Springs Rd",
            consent_to_share=True,
            problem_summary="The kitchen sink has been leaking under the cabinet.",
        ),
    )
    assert session.lead is not None
    assert session.lead.problem_summary == "The kitchen sink has been leaking under the cabinet."
    assert session.email is not None


def test_complete_lead_and_email_draft(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: None)
    session = _session(
        messages=[
            ChatMessage(
                role="user",
                content="Kitchen sink leaking onto the floor.",
            )
        ]
    )
    lead = build_lead(session)
    assert lead.status == LeadStatus.complete
    assert lead.missing_required == []
    email = draft_email(lead, messages=session.messages)
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


def test_email_includes_chat_details_not_generic_technician(monkeypatch):
    """Chat specifics must appear. A canned technician line is not enough."""
    monkeypatch.setattr("app.llm._client", lambda **_k: None)
    messages = [
        ChatMessage(
            role="user",
            content="something's off with the water, idk, the house just feels wrong",
        ),
        ChatMessage(
            role="assistant",
            content="What are you noticing with the water — color, smell, or which fixtures?",
        ),
        ChatMessage(
            role="user",
            content="The color is murky, the smell is very foul. Temperature is hot.",
        ),
        ChatMessage(
            role="assistant",
            content="Is this happening at every tap, or only on the hot-water side?",
        ),
        ChatMessage(role="user", content="I'm not sure"),
    ]
    lead = build_lead(
        _session(
            messages=messages,
            analysis=LLMAnalysis(
                service_category=ServiceCategory.plumbing,
                category_confidence=0.9,
                urgency=Urgency.same_day,
                urgency_reason="Water quality issue",
                problem_summary="something's off with the water, idk",
                facts={
                    "color": "murky",
                    "smell": "foul",
                    "temperature": "hot",
                    "scope": "unknown",
                },
                zip_code="78717",
            ),
            city=None,
            zip_code="78717",
        )
    )
    email = draft_email(lead, messages=messages)
    assert email is not None
    lowered = email.body.lower()
    assert "murky" in lowered
    assert "foul" in lowered
    assert "hot" in lowered
    assert "i need a technician at the home" not in lowered
    assert "What I know" not in email.body
    assert "leak_location" not in email.body


def test_email_llm_writes_from_transcript(monkeypatch):
    captured = {}

    def fake_draft(history, problem_summary="", facts=None):
        captured["history"] = history
        captured["summary"] = problem_summary
        captured["facts"] = facts
        return (
            "The water is murky and has a foul smell. It is hot. "
            "I do not know how widespread it is.",
            False,
        )

    monkeypatch.setattr("app.llm.draft_problem_paragraph", fake_draft)
    messages = [
        ChatMessage(
            role="user",
            content="The color is murky, the smell is very foul. Temperature is hot.",
        ),
        ChatMessage(role="user", content="I'm not sure"),
    ]
    lead = build_lead(
        _session(
            messages=messages,
            analysis=LLMAnalysis(
                service_category=ServiceCategory.plumbing,
                category_confidence=0.9,
                urgency=Urgency.same_day,
                problem_summary="Murky, foul-smelling hot water.",
                facts={"color": "murky", "smell": "foul", "temperature": "hot"},
                zip_code="78717",
            ),
            city=None,
            zip_code="78717",
        )
    )
    email = draft_email(lead, messages=messages)
    assert captured["history"] == messages
    assert "murky" in captured["summary"].lower()
    assert captured["facts"]["color"] == "murky"
    body = email.body
    assert "The water is murky and has a foul smell." in body
    assert "Hello Austin Rooter," in body
    assert "The service address is 1200 Barton Springs Rd." in body
    assert "I need a technician at the home" not in body


def test_email_does_not_dump_form_field_labels(monkeypatch):
    monkeypatch.setattr(
        "app.llm.draft_problem_paragraph",
        lambda *_a, **_k: (
            "The lights went out throughout the house. I do not know what caused it.",
            False,
        ),
    )
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
    assert "The lights went out throughout the house." in body
    assert "yes I am safe" not in body
    assert "What I know" not in body
    assert "Lights out:" not in body
    assert "Safety signs present" not in body
    assert "lights_out" not in body
    assert "Hi " not in body


def test_email_llm_output_stays_first_person(monkeypatch):
    monkeypatch.setattr(
        "app.llm.draft_problem_paragraph",
        lambda *_a, **_k: (
            "My living room ceiling fan sparked and stopped spinning. "
            "I shut off power at the breaker.",
            False,
        ),
    )
    lead = build_lead(
        _session(
            providers=[_electrician()],
            analysis=LLMAnalysis(
                service_category=ServiceCategory.electrical,
                category_confidence=0.95,
                urgency=Urgency.emergency,
                problem_summary=(
                    "Living room ceiling fan sparked and stopped spinning. "
                    "The homeowner shut off power at the breaker."
                ),
                facts={
                    "fixture": "ceiling fan",
                    "location": "living_room",
                    "room": "living room",
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
    assert "I shut off" in body
    assert "What I know" not in body


def test_mailto_uses_provider_email(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: None)
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
