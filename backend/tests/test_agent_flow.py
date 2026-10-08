from app import agent
from app.agent import _extract_location
from app.models import (
    ContactInfo,
    LeadStatus,
    LLMAnalysis,
    Provider,
    ServiceCategory,
    Stage,
    Urgency,
)


def _listing(**kwargs) -> Provider:
    data = dict(
        place_id="ChIJ-eval",
        name="Stub Plumbing",
        address="Austin, TX 78704",
        phone="512-555-0111",
        website="https://example.com",
        maps_url="https://maps.google.com/?cid=1",
        rating=4.7,
        review_count=42,
        primary_type="plumber",
        source="google_places",
    )
    data.update(kwargs)
    return Provider(**data)


def _analysis(**overrides) -> LLMAnalysis:
    data = dict(
        service_category=ServiceCategory.plumbing,
        category_confidence=0.92,
        urgency=Urgency.same_day,
        urgency_reason="active leak",
        problem_summary="Kitchen sink leaking",
        facts={"fixture": "kitchen sink"},
        missing_details=["whether water is still running"],
        next_question="Is water still running from the leak?",
    )
    data.update(overrides)
    return LLMAnalysis(**data)


def _stub_places(monkeypatch, listing: Provider | None = None) -> None:
    item = listing or _listing()
    monkeypatch.setattr(
        "app.places.search_text",
        lambda *_args, **_kwargs: ([item], "google_places", None),
    )


def test_extract_location_does_not_swallow_prose():
    city, zip_code, query = _extract_location(
        "It's still seeping in along the basement wall, not near any outlets. Austin, TX 78704"
    )
    assert city == "Austin"
    assert zip_code == "78704"
    assert query == "Austin, TX 78704"


def test_gas_smell_escalates_without_search(monkeypatch):
    called = {"search": False}

    def fake_search(*_args, **_kwargs):
        called["search"] = True
        return [], "google_places", None

    monkeypatch.setattr("app.places.search_text", fake_search)
    session = agent.create_session("gas")
    agent.handle_user_message(session, "I smell gas in the kitchen. It started a few minutes ago.")
    assert session.stage == Stage.safety_escalated
    assert called["search"] is False
    assert session.lead is not None
    assert session.lead.status == LeadStatus.safety_escalated


def test_happy_path_completes_lead_with_stubbed_places(monkeypatch):
    listing = Provider(
        place_id="ChIJ-eval",
        name="Stub Plumbing",
        address="Austin, TX 78704",
        phone="512-555-0111",
        website="https://example.com",
        maps_url="https://maps.google.com/?cid=1",
        rating=4.7,
        review_count=42,
        primary_type="plumber",
        source="google_places",
    )

    monkeypatch.setattr(
        "app.places.search_text",
        lambda *_args, **_kwargs: ([listing], "google_places", None),
    )
    turns = {"n": 0}

    def fake_analyze(_history):
        turns["n"] += 1
        if turns["n"] == 1:
            return _analysis(
                next_question="Where is the leak, and is water still running?"
            ), False
        return _analysis(next_question=None, missing_details=[]), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)

    session = agent.create_session("sink")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "My kitchen sink has been leaking under the cabinet since this morning.",
    )
    assert session.stage == Stage.gathering
    agent.handle_user_message(
        session,
        "It's under the kitchen sink, still dripping.",
    )
    assert session.providers
    assert session.providers[0].place_id == "ChIJ-eval"
    agent.handle_select(session, "ChIJ-eval")
    agent.handle_contact(
        session,
        ContactInfo(
            name="Alex Rivera",
            phone="512-555-0101",
            email="alex@example.com",
            service_address="1200 Barton Springs Rd, Austin, TX 78704",
            consent_to_share=True,
        ),
    )
    assert session.stage == Stage.lead_ready
    assert session.lead is not None
    assert session.lead.status == LeadStatus.complete
    assert session.email is not None
    assert "Stub Plumbing" in session.email.body
    assert agent.effective_category(session) == ServiceCategory.plumbing


def test_location_field_avoids_chat_zip_prompt(monkeypatch):
    listing = Provider(
        place_id="p-plumb",
        name="Stub Plumbing",
        address="Austin, TX 78704",
        phone="512-555-0111",
        primary_type="plumber",
        source="google_places",
    )
    monkeypatch.setattr(
        "app.places.search_text",
        lambda *_args, **_kwargs: ([listing], "google_places", None),
    )
    session = agent.create_session("loc-field")
    agent.handle_location(session, "Austin, TX 78704")
    assert session.city == "Austin"
    assert session.zip_code == "78704"
    agent.handle_user_message(
        session,
        "My kitchen sink has been leaking under the cabinet since this morning.",
    )
    chat = " ".join(message.content for message in session.messages if message.role == "assistant")
    assert "What city or ZIP code should I use" not in chat
    assert session.zip_code == "78704"


def test_chat_after_panel_search_rereads_problem(monkeypatch):
    calls = {"queries": []}

    def fake_search(category, location, urgency=None):
        calls["queries"].append(category)
        listing = Provider(
            place_id=f"id-{category.value}",
            name=f"{category.value} co",
            address="Austin, TX",
            phone="512-555-0100",
            primary_type="plumber" if category == ServiceCategory.plumbing else "handyman",
            source="google_places",
        )
        return [listing], "google_places", None

    monkeypatch.setattr("app.places.search_text", fake_search)
    session = agent.create_session("panel-then-chat")
    agent.handle_search(session, category=None, location="Austin, TX")
    assert session.stage == Stage.showing_providers
    agent.handle_user_message(
        session,
        "My kitchen sink has been leaking under the cabinet since this morning.",
    )
    assert ServiceCategory.plumbing in calls["queries"]
    assert session.providers[0].place_id == "id-plumbing"
    assert "Select a provider from the list when you are ready" not in session.messages[-1].content


def test_where_in_home_is_not_a_city_prompt():
    assert not agent._question_looks_like_location(
        "Where in the home is the leak, and which fixture?"
    )
    assert agent._question_looks_like_location("What city or ZIP should I use?")
    assert agent._question_looks_like_contact("What is your name and phone number?")
    assert agent._question_looks_like_contact("What is the service address for the visit?")
    assert agent.MAX_FOLLOWUPS == 8


def test_keeps_asking_high_value_followups(monkeypatch):
    _stub_places(monkeypatch)
    questions = [
        "Which fixture is leaking, and which room is it in?",
        "Is the water still running right now?",
        "Can a technician open the cabinet to reach the shutoff?",
    ]
    call = {"n": 0}

    def fake_analyze(_history):
        question = questions[min(call["n"], len(questions) - 1)]
        call["n"] += 1
        return _analysis(next_question=question), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("multi-q")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "My kitchen sink is leaking.")
    assert session.stage == Stage.gathering
    assert session.questions_asked == 1
    assert "which fixture" in session.messages[-1].content.lower()

    agent.handle_user_message(session, "The kitchen sink under the cabinet.")
    assert session.stage == Stage.gathering
    assert session.questions_asked == 2
    assert "still running" in session.messages[-1].content.lower()

    agent.handle_user_message(session, "Yes, it is still dripping.")
    assert session.stage == Stage.gathering
    assert session.questions_asked == 3
    assert "shutoff" in session.messages[-1].content.lower()
    assert session.providers == []


def test_stops_early_when_next_question_is_null(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history):
        return _analysis(next_question=None, missing_details=[]), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("enough")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "Kitchen sink has been leaking under the cabinet since this morning, still dripping.",
    )
    assert session.stage == Stage.showing_providers
    assert session.questions_asked == 0
    assert session.providers


def test_skips_contact_and_city_questions_in_chat(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history):
        return _analysis(next_question="What is your name and phone number?"), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("skip-contact")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "My kitchen sink is leaking under the cabinet.")
    last = session.messages[-1].content.lower()
    assert "what is your name" not in last
    assert session.asked_questions == []
    assert session.stage == Stage.showing_providers
    assert session.questions_asked == 0

    def fake_city(_history):
        return _analysis(next_question="What city or ZIP code are you in?"), False

    monkeypatch.setattr("app.llm.analyze", fake_city)
    missing_loc = agent.create_session("skip-city")
    agent.handle_user_message(missing_loc, "My kitchen sink is leaking under the cabinet.")
    assert missing_loc.stage == Stage.need_location
    assert missing_loc.questions_asked == 0
    assert "location field" in missing_loc.messages[-1].content.lower()
    assert "do not need to type it in the chat" in missing_loc.messages[-1].content.lower()


def test_high_followup_cap_then_searches(monkeypatch):
    _stub_places(monkeypatch)
    call = {"n": 0}

    def fake_analyze(_history):
        call["n"] += 1
        return _analysis(
            next_question=f"What access constraint number {call['n']} should dispatch know?"
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("cap")
    agent.handle_location(session, "Austin, TX 78704")
    session.questions_asked = agent.MAX_FOLLOWUPS
    session.asked_questions = [f"prior question {i}" for i in range(agent.MAX_FOLLOWUPS)]
    agent.handle_user_message(session, "It is still dripping under the kitchen sink.")
    assert session.questions_asked == agent.MAX_FOLLOWUPS
    assert session.stage == Stage.showing_providers
    assert session.providers


def test_header_location_does_not_abort_gathering(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history):
        return _analysis(
            next_question="Which fixture is leaking, and which room is it in?"
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("loc-later")
    agent.handle_user_message(session, "My kitchen sink is leaking.")
    assert session.stage == Stage.gathering
    assert session.questions_asked == 1
    agent.handle_location(session, "Austin, TX 78704")
    assert session.stage == Stage.gathering
    assert session.questions_asked == 1
    assert not session.providers
