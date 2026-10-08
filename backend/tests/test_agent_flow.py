from app import agent
from app.agent import _extract_location, apply_location_string, merge_analysis
from app.models import (
    ContactInfo,
    Hazard,
    LeadStatus,
    LLMAnalysis,
    Provider,
    ServiceCategory,
    SessionState,
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
    called = {"search": False, "analyze": False, "safety": False}

    def fake_search(*_args, **_kwargs):
        called["search"] = True
        return [], "google_places", None

    def fake_analyze(_history, **_kwargs):
        called["analyze"] = True
        raise AssertionError("gas emergency must not run intake analysis")

    def fake_safety_reply(user_text, hazards, mode="escalate"):
        called["safety"] = True
        assert mode == "escalate"
        assert "smell gas" in user_text.lower()
        return (
            "Get everyone outside right now and call 911 from a safe place. "
            "I will not look up contractors until you confirm everyone is safe.",
            False,
        )

    monkeypatch.setattr("app.places.search_text", fake_search)
    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    monkeypatch.setattr("app.llm.safety_reply", fake_safety_reply)
    session = agent.create_session("gas")
    agent.handle_user_message(session, "I smell gas in the kitchen. It started a few minutes ago.")
    assert session.stage == Stage.safety_escalated
    assert called["search"] is False
    assert called["analyze"] is False
    assert called["safety"] is True
    assert session.lead is not None
    assert session.lead.status == LeadStatus.safety_escalated
    assert "911" in session.messages[-1].content
    assert "Get everyone outside" in session.messages[-1].content
    assert session.safety_advice == session.messages[-1].content


def _historical_escalate_analyze(hazard: Hazard, category: ServiceCategory):
    """DeepSeek keeps returning the original escalate label from chat history."""

    def fake_analyze(history, **_kwargs):
        last = next(
            (message.content.lower() for message in reversed(history) if message.role == "user"),
            "",
        )
        want_search = "find contractors" in last
        return _analysis(
            service_category=category,
            category_confidence=0.93,
            hazards=[hazard],
            problem_summary="Emergency reported earlier in the chat.",
            facts={"hazard": hazard.value},
            missing_details=[] if want_search else ["dispatch details"],
            next_question=None if want_search else "What else should dispatch know?",
            dispatch_ready=want_search,
        ), False

    return fake_analyze


def _stub_escalate_copy(monkeypatch, modes: list[str]) -> None:
    def fake_safety_reply(_user_text, _hazards, mode="escalate"):
        modes.append(mode)
        if mode == "escalate":
            return (
                "This is an emergency. Get out and call 911. "
                "I will not look up contractors until you confirm everyone is safe.",
                False,
            )
        if mode == "resume":
            return (
                "Thanks for confirming you are safe. I can continue helping you find a provider.",
                False,
            )
        return ("Caution noted.", False)

    monkeypatch.setattr("app.llm.safety_reply", fake_safety_reply)


def test_gas_safe_confirmation_does_not_reloop_when_llm_repeats_hazard(monkeypatch):
    """Escalate on gas; 'I am safe' resumes; contractors search is not a 911 hold."""
    modes: list[str] = []
    _stub_escalate_copy(monkeypatch, modes)
    _stub_places(monkeypatch)
    monkeypatch.setattr(
        "app.llm.analyze",
        _historical_escalate_analyze(Hazard.gas_leak, ServiceCategory.plumbing),
    )

    session = agent.create_session("gas-safe-loop")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "I smell gas in the kitchen. It started a few minutes ago.",
    )
    assert session.stage == Stage.safety_escalated
    assert session.safety_cleared is False
    escalate_copy = session.messages[-1].content
    assert "911" in escalate_copy
    assert "will not look up contractors until you confirm" in escalate_copy.lower()

    agent.handle_user_message(session, "I am safe")
    assert session.safety_cleared is True
    assert session.stage != Stage.safety_escalated
    assert agent.blocked_for_safety(session) is False
    resumed = session.messages[-1].content
    assert resumed != escalate_copy
    assert "will not look up contractors until you confirm" not in resumed.lower()
    assert "911" not in resumed
    assert modes.count("escalate") == 1
    assert "resume" in modes
    assert session.providers == []

    agent.handle_user_message(session, "I am safe, please find contractors")
    assert session.safety_cleared is True
    assert session.stage != Stage.safety_escalated
    assert agent.blocked_for_safety(session) is False
    assert session.stage == Stage.showing_providers
    assert session.providers
    last = session.messages[-1].content.lower()
    assert "will not look up contractors until you confirm" not in last
    assert modes.count("escalate") == 1


def test_co_safe_confirmation_does_not_reloop_when_llm_repeats_hazard(monkeypatch):
    """Same 911 loop for carbon monoxide — not gas-only."""
    modes: list[str] = []
    _stub_escalate_copy(monkeypatch, modes)
    _stub_places(
        monkeypatch,
        _listing(name="Stub HVAC", primary_type="hvac_contractor"),
    )
    monkeypatch.setattr(
        "app.llm.analyze",
        _historical_escalate_analyze(Hazard.carbon_monoxide, ServiceCategory.hvac),
    )

    session = agent.create_session("co-safe-loop")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "Our carbon monoxide alarm is going off.")
    assert session.stage == Stage.safety_escalated
    assert Hazard.carbon_monoxide in session.hazards
    assert "911" in session.messages[-1].content

    agent.handle_user_message(session, "I am safe")
    assert session.safety_cleared is True
    assert session.stage != Stage.safety_escalated
    assert "will not look up contractors until you confirm" not in session.messages[-1].content.lower()

    agent.handle_user_message(session, "I am safe, please find contractors")
    assert session.stage != Stage.safety_escalated
    assert session.safety_cleared is True
    assert session.stage == Stage.showing_providers
    assert session.providers
    assert modes.count("escalate") == 1


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

    def fake_analyze(_history, **_kwargs):
        turns["n"] += 1
        if turns["n"] == 1:
            return _analysis(
                next_question="Where is the leak, and is water still running?"
            ), False
        return _analysis(next_question=None, missing_details=[]), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    monkeypatch.setattr("app.llm._client", lambda **_k: None)

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
    assert "leaking" in session.email.body.lower()
    assert "i need a technician at the home" not in session.email.body.lower()
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

    def fake_analyze(_history, **_kwargs):
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

    def fake_analyze(_history, **_kwargs):
        return _analysis(next_question=None, missing_details=[]), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("enough")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "Kitchen sink has been leaking under the cabinet since this morning, "
        "still dripping. I can reach the shutoff.",
    )
    assert session.stage == Stage.showing_providers
    assert session.questions_asked == 0
    assert session.providers


def test_skips_contact_and_city_questions_in_chat(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history, **_kwargs):
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

    def fake_city(_history, **_kwargs):
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

    def fake_analyze(_history, **_kwargs):
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


def test_location_change_replaces_stale_zip():
    session = agent.create_session("loc-replace")
    apply_location_string(session, "Austin, TX 78704")
    assert session.city == "Austin"
    assert session.zip_code == "78704"
    apply_location_string(session, "Dallas, TX")
    assert session.city == "Dallas"
    assert session.zip_code is None
    assert "78704" not in (session.location_query or "")
    if session.analysis:
        assert session.analysis.zip_code is None


def test_completed_lead_does_not_mutate_analysis(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history, **_kwargs):
        return _analysis(next_question=None, missing_details=[]), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    monkeypatch.setattr("app.llm._client", lambda **_k: None)
    session = agent.create_session("lock-lead")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "My kitchen sink has been leaking under the cabinet.")
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
    summary = session.analysis.problem_summary
    category = session.analysis.service_category

    def boom(_history, **_kwargs):
        raise AssertionError("completed leads must not call the LLM")

    monkeypatch.setattr("app.llm.analyze", boom)
    agent.handle_user_message(session, "Actually it is a roof leak and I also have ants.")
    assert session.stage == Stage.lead_ready
    assert session.analysis.service_category == category
    assert session.analysis.problem_summary == summary
    assert "already complete" in session.messages[-1].content.lower()


def test_analyze_receives_catalog_hints_after_trade_is_known(monkeypatch):
    captured = {"guidance": []}

    def fake_analyze(_history, intake_guidance=None, **_kwargs):
        captured["guidance"].append(intake_guidance)
        return _analysis(
            next_question="Is water still leaking right now?",
            missing_details=["still_running"],
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("catalog-hint")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "A pipe is leaking in the house.")
    assert captured["guidance"][0] is None
    agent.handle_user_message(session, "It is still dripping under the sink.")
    second = captured["guidance"][1]
    assert second
    assert "leaking pipe or fixture" in second
    assert "Ask at most ONE question" in second


def test_analyze_gets_no_catalog_hints_for_uncovered_problem(monkeypatch):
    captured = {}

    def fake_analyze(_history, intake_guidance=None, **_kwargs):
        captured["guidance"] = intake_guidance
        return _analysis(
            service_category=ServiceCategory.handyman,
            next_question="What exactly is the lock doing, and when did it start?",
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("no-catalog")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "My smart lock randomly unlocks at 2am and the keypad is dead.",
    )
    assert captured["guidance"] is None


def test_unknown_answer_does_not_pivot_to_catalog_fallback(monkeypatch):
    _stub_places(monkeypatch)
    turns = {"n": 0}

    def fake_analyze(_history, **_kwargs):
        turns["n"] += 1
        if turns["n"] == 1:
            return _analysis(
                problem_summary="Something is off with the water.",
                facts={},
                next_question=(
                    "What are you noticing with the water — color, smell, or which fixtures?"
                ),
                dispatch_ready=False,
            ), False
        if turns["n"] == 2:
            return _analysis(
                problem_summary="Murky, foul-smelling hot water.",
                facts={
                    "color": "murky",
                    "smell": "foul",
                    "temperature": "hot",
                },
                next_question="Is this happening at every tap, or only on the hot-water side?",
                dispatch_ready=False,
            ), False
        return _analysis(
            problem_summary="Murky, foul-smelling hot water. Scope unknown.",
            facts={
                "color": "murky",
                "smell": "foul",
                "temperature": "hot",
                "scope": "unknown",
            },
            missing_details=[],
            next_question=None,
            dispatch_ready=True,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("idk-water")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "something's off with the water, idk, the house just feels wrong",
    )
    assert session.stage == Stage.gathering
    agent.handle_user_message(
        session,
        "The color is murky, the smell is very foul. Temperature is hot.",
    )
    assert session.stage == Stage.gathering
    agent.handle_user_message(session, "I'm not sure")
    last = session.messages[-1].content.lower()
    assert "leak or clog" not in last
    assert "still running" not in last
    assert session.stage == Stage.showing_providers
    assert session.providers
    assert session.analysis.dispatch_ready is True
    assert session.analysis.facts["scope"] == "unknown"
    assert session.analysis.next_question is None
    assert "murky" in session.analysis.problem_summary.lower()


def test_merge_keeps_detailed_summary_on_shrug():
    session = SessionState(id="shrug-merge")
    session.analysis = _analysis(
        problem_summary="Murky, foul-smelling hot water.",
        facts={"color": "murky", "smell": "foul", "temperature": "hot"},
        next_question="Is this at every tap?",
        dispatch_ready=False,
    )
    merge_analysis(
        session,
        _analysis(
            problem_summary="I'm not sure.",
            facts={"scope": "unknown"},
            next_question=None,
            dispatch_ready=True,
        ),
    )
    assert "murky" in session.analysis.problem_summary.lower()
    assert "not sure" not in session.analysis.problem_summary.lower()
    assert session.analysis.facts["color"] == "murky"
    assert session.analysis.facts["scope"] == "unknown"
    assert session.analysis.dispatch_ready is True


def test_idk_does_not_reask_the_same_slot(monkeypatch):
    _stub_places(monkeypatch)
    turns = {"n": 0}

    def fake_analyze(_history, **_kwargs):
        turns["n"] += 1
        if turns["n"] == 1:
            return _analysis(
                next_question="Is water still leaking right now?",
                dispatch_ready=False,
            ), False
        return _analysis(
            facts={"still_running": "unknown"},
            missing_details=[],
            next_question=None,
            dispatch_ready=True,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("idk-same-slot")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "my sink is leaking")
    first = session.messages[-1].content.lower()
    assert "still" in first
    agent.handle_user_message(session, "idk")
    last = session.messages[-1].content.lower()
    assert "still leaking" not in last
    assert "still running" not in last
    assert session.stage == Stage.showing_providers
    assert session.analysis.dispatch_ready is True
    assert session.analysis.facts["still_running"] == "unknown"
    assert session.analysis.next_question is None


def test_vague_water_problem_becomes_actionable_after_a_few_questions(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(history, **_kwargs):
        last = next(
            (m.content.lower() for m in reversed(history) if m.role == "user"),
            "",
        )
        if "every faucet" in last or "hot and cold" in last:
            return _analysis(
                problem_summary="Brown water at every faucet, hot and cold, started this morning.",
                facts={
                    "symptom": "brown discolored water",
                    "scope": "every faucet",
                    "started": "this morning",
                },
                missing_details=[],
                next_question=None,
                dispatch_ready=True,
            ), False
        if "brown" in last:
            return _analysis(
                problem_summary="The water is brown.",
                facts={"symptom": "brown water"},
                missing_details=["scope", "timing"],
                next_question="Is it every faucet, and when did it start?",
                dispatch_ready=False,
            ), False
        return _analysis(
            problem_summary="Something is wrong with the water.",
            facts={},
            missing_details=["symptom", "scope"],
            next_question="What is happening with the water?",
            dispatch_ready=False,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("vague-water")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "something is wrong with the water")
    assert session.stage == Stage.gathering
    assert session.questions_asked == 1
    agent.handle_user_message(session, "it's brown")
    assert session.stage == Stage.gathering
    agent.handle_user_message(
        session,
        "every faucet, hot and cold, started this morning",
    )
    assert session.stage == Stage.showing_providers
    assert session.questions_asked <= 3
    assert session.providers
    assert "brown" in session.analysis.problem_summary.lower()


def test_detailed_opening_needs_no_followups(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history, **_kwargs):
        return _analysis(
            problem_summary=(
                "Kitchen sink leaking under the cabinet since this morning, "
                "still dripping, shutoff is reachable."
            ),
            facts={
                "fixture": "kitchen sink",
                "started": "this morning",
                "still_running": "dripping",
                "shutoff": "reachable",
            },
            missing_details=[],
            next_question=None,
            dispatch_ready=True,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("detailed-open")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "Kitchen sink has been leaking under the cabinet since this morning, "
        "still dripping. I can reach the shutoff.",
    )
    assert session.stage == Stage.showing_providers
    assert session.questions_asked == 0
    assert session.analysis.dispatch_ready is True
    assert session.analysis.facts["fixture"] == "kitchen sink"


def test_ambiguous_house_problem_keeps_clarifying(monkeypatch):
    _stub_places(monkeypatch)
    call = {"n": 0}

    def fake_analyze(_history, **_kwargs):
        call["n"] += 1
        questions = [
            "Which part of the home is affected, and what did you notice?",
            "Is this a water problem, an electrical problem, or something else?",
            "When did it start, and is it getting worse?",
        ]
        return _analysis(
            service_category=ServiceCategory.unknown,
            category_confidence=0.3,
            problem_summary="Something is wrong with the house.",
            facts={},
            missing_details=["what is happening"],
            next_question=questions[min(call["n"] - 1, len(questions) - 1)],
            dispatch_ready=False,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("ambiguous-house")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "I need help with the house but I cannot tell what kind of problem it is.",
    )
    assert session.stage == Stage.gathering
    agent.handle_user_message(session, "utilities maybe")
    assert session.stage == Stage.gathering
    assert session.questions_asked >= 2
    assert session.providers == []
    assert session.questions_asked <= agent.MAX_FOLLOWUPS


def test_repeated_unknown_answers_do_not_get_stuck(monkeypatch):
    _stub_places(monkeypatch)
    turns = {"n": 0}

    def fake_analyze(_history, **_kwargs):
        turns["n"] += 1
        if turns["n"] == 1:
            return _analysis(
                next_question="Can you describe the leak in more detail?",
                dispatch_ready=False,
            ), False
        return _analysis(
            facts={"leak_detail": "unknown"},
            missing_details=[],
            next_question=None,
            dispatch_ready=True,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("repeat-idk")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "my sink is leaking")
    assert session.stage == Stage.gathering
    agent.handle_user_message(session, "idk")
    last = session.messages[-1].content.lower()
    assert "leak or clog" not in last
    assert session.stage == Stage.showing_providers
    assert session.questions_asked == 1
    assert session.providers
    assert session.analysis.dispatch_ready is True
    assert session.analysis.facts["leak_detail"] == "unknown"


def test_python_does_not_stop_on_unknown_wording(monkeypatch):
    """Intake stops only when the LLM says so, not because the reply looks like a shrug."""
    _stub_places(monkeypatch)
    turns = {"n": 0}

    def fake_analyze(_history, **_kwargs):
        turns["n"] += 1
        if turns["n"] == 1:
            return _analysis(
                next_question="Is water still leaking right now?",
                dispatch_ready=False,
            ), False
        return _analysis(
            facts={"still_running": "unknown"},
            next_question="Which room and fixture is leaking?",
            dispatch_ready=False,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("idk-other-slot")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(session, "my sink is leaking")
    agent.handle_user_message(session, "idk")
    last = session.messages[-1].content.lower()
    assert session.stage == Stage.gathering
    assert session.questions_asked == 2
    assert "which room" in last
    assert "fixture" in last
    assert session.providers == []


def test_discolored_water_stops_before_diagnostic_extras(monkeypatch):
    _stub_places(monkeypatch)
    turns = {"n": 0}

    def fake_analyze(history, **_kwargs):
        turns["n"] += 1
        last = next(
            (m.content.lower() for m in reversed(history) if m.role == "user"),
            "",
        )
        if "every faucet" in last:
            return _analysis(
                problem_summary=(
                    "Discolored water at every faucet, hot and cold, started today."
                ),
                facts={
                    "symptom": "discolored water",
                    "scope": "every faucet, hot and cold",
                    "started": "today",
                },
                missing_details=[],
                next_question="Is the water pressure also low?",
                dispatch_ready=True,
            ), False
        return _analysis(
            problem_summary="Discolored water throughout the house.",
            facts={"symptom": "discolored water", "scope": "throughout the house"},
            missing_details=["which fixtures", "when it started"],
            next_question="Is it every faucet, both hot and cold, and when did it start?",
            dispatch_ready=False,
        ), False

    monkeypatch.setattr("app.llm.analyze", fake_analyze)
    session = agent.create_session("brown-water")
    agent.handle_location(session, "Austin, TX 78704")
    agent.handle_user_message(
        session,
        "The water in my house is brown and discolored throughout.",
    )
    assert session.stage == Stage.gathering
    assert session.questions_asked == 1
    agent.handle_user_message(
        session,
        "It's every faucet, both hot and cold, and it started today.",
    )
    assert session.stage == Stage.showing_providers
    assert session.questions_asked == 1
    chat = " ".join(m.content.lower() for m in session.messages if m.role == "assistant")
    assert "pressure" not in chat
    assert "neighbor" not in chat
    assert session.analysis.facts["scope"] == "every faucet, hot and cold"
    assert session.analysis.facts["started"] == "today"


def test_header_location_does_not_abort_gathering(monkeypatch):
    _stub_places(monkeypatch)

    def fake_analyze(_history, **_kwargs):
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
