from app.llm import (
    analyze,
    draft_problem_paragraph,
    fallback_analysis,
    fallback_problem_paragraph,
    fallback_safety_reply,
    parse_analysis,
    _sanitize_problem_paragraph,
    _sanitize_safety_text,
)
from app.models import ChatMessage, Hazard, ServiceCategory, Urgency


def test_valid_json_parses():
    raw = """
    {
      "service_category": "plumbing",
      "category_confidence": 0.8,
      "urgency": "same_day",
      "urgency_reason": "Active leak",
      "problem_summary": "Sink leaking",
      "facts": {"room": "kitchen"},
      "city": "Austin",
      "zip_code": "78704",
      "hazards": [],
      "missing_details": [],
      "next_question": null
    }
    """
    analysis = parse_analysis(raw)
    assert analysis.service_category == ServiceCategory.plumbing
    assert analysis.city == "Austin"


def test_fenced_json_and_invalid_enums_are_coerced():
    raw = """```json
    {
      "service_category": "hvac",
      "category_confidence": 9,
      "urgency": "super-urgent",
      "hazards": ["ghosts", "electrical"],
      "facts": "not-a-dict",
      "next_question": "Where is the leak?"
    }
    ```"""
    analysis = parse_analysis(raw)
    assert analysis.service_category == ServiceCategory.hvac
    assert analysis.category_confidence == 1.0
    assert analysis.urgency == Urgency.flexible
    assert [h.value for h in analysis.hazards] == ["electrical"]
    assert analysis.facts == {}


def test_catalog_label_is_not_a_category():
    try:
        parse_analysis(
            '{"service_category":"plumbing: leaking pipe or fixture",'
            '"category_confidence":0.8,"next_question":"Where?","dispatch_ready":false}'
        )
        assert False, "expected category error"
    except ValueError as exc:
        assert "service_category" in str(exc)


def test_partial_object_uses_defaults():
    analysis = parse_analysis(
        '{"service_category": "hvac", "category_confidence": 0.4}'
    )
    assert analysis.service_category == ServiceCategory.hvac
    assert analysis.facts == {}
    assert analysis.next_question is None
    assert analysis.safety_confirmed is False


def test_unknown_category_cannot_skip_the_question():
    try:
        parse_analysis(
            '{"service_category":"unknown","category_confidence":0.2,'
            '"dispatch_ready":true,"next_question":null}'
        )
        assert False, "expected unknown to require a question"
    except ValueError as exc:
        assert "unknown" in str(exc).lower()


def test_safety_confirmed_parses_from_json():
    assert parse_analysis('{"safety_confirmed": true}').safety_confirmed is True
    assert parse_analysis('{"safety_confirmed": "yes"}').safety_confirmed is True
    assert parse_analysis('{"safety_confirmed": false}').safety_confirmed is False


def test_off_schema_json_raises():
    try:
        parse_analysis(
            '{"trade":"plumbing","follow_up_questions":["Where is it leaking?"]}'
        )
        assert False, "expected schema error"
    except ValueError as exc:
        assert "intake schema" in str(exc)


def test_unreadable_stretch_blocks_dispatch_even_if_intake_says_ready(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: object())

    def fake_complete(_client, messages, **_k):
        system = messages[0]["content"]
        if system.startswith("Read ONLY the latest"):
            return '{"needs_clarification": true, "question": "What did that first part mean?"}'
        return (
            '{"service_category":"plumbing","category_confidence":0.9,'
            '"urgency":"same_day","urgency_reason":"Active leak",'
            '"problem_summary":"Leaks in the house.",'
            '"facts":{},"hazards":[],"missing_details":[],'
            '"next_question":null,"dispatch_ready":true}'
        )

    monkeypatch.setattr("app.llm._complete", fake_complete)
    analysis, used_fallback = analyze(
        [ChatMessage(role="user", content="The first words are not readable and the sink leaks.")]
    )
    assert used_fallback is False
    assert analysis.dispatch_ready is False
    assert analysis.next_question == "What did that first part mean?"
    assert analysis.service_category == ServiceCategory.plumbing


def test_readable_message_keeps_dispatch(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: object())

    def fake_complete(_client, messages, **_k):
        system = messages[0]["content"]
        if system.startswith("Read ONLY the latest"):
            return '{"needs_clarification": false, "question": null}'
        return (
            '{"service_category":"plumbing","category_confidence":0.9,'
            '"urgency":"same_day","urgency_reason":"Active leak",'
            '"problem_summary":"My kitchen sink is leaking.",'
            '"facts":{},"hazards":[],"missing_details":[],'
            '"next_question":null,"dispatch_ready":true}'
        )

    monkeypatch.setattr("app.llm._complete", fake_complete)
    analysis, used_fallback = analyze(
        [ChatMessage(role="user", content="My kitchen sink is leaking under the cabinet.")]
    )
    assert used_fallback is False
    assert analysis.dispatch_ready is True
    assert analysis.next_question is None


def test_malformed_json_raises():
    try:
        parse_analysis("not json at all")
        assert False, "expected json error"
    except Exception:
        pass


def test_safety_hold_confirmation_is_separate_from_intake_json(monkeypatch):
    """Fire/gas/CO history must not keep the hold if this turn means they got out."""
    monkeypatch.setattr("app.llm._client", lambda **_k: object())
    seen = {"confirm": 0, "analyze": 0}

    def fake_complete(_client, messages, **_k):
        system = messages[0]["content"]
        if system.startswith("The intake session is paused"):
            seen["confirm"] += 1
            assert messages[-1]["role"] == "user"
            return '{"safety_confirmed": true}'
        seen["analyze"] += 1
        return (
            '{"service_category":"handyman","category_confidence":0.9,'
            '"urgency":"emergency","urgency_reason":"Fire reported",'
            '"problem_summary":"There was a fire.","facts":{},'
            '"hazards":["fire_smoke"],"missing_details":[],'
            '"next_question":null,"dispatch_ready":false,'
            '"safety_confirmed":false}'
        )

    monkeypatch.setattr("app.llm._complete", fake_complete)
    analysis, used_fallback = analyze(
        [
            ChatMessage(role="user", content="there's a fire in my house"),
            ChatMessage(role="assistant", content="Get out and call 911."),
            ChatMessage(role="user", content="Everyone is outside and safe"),
        ],
        safety_hold=True,
    )
    assert used_fallback is False
    assert seen["confirm"] >= 1
    assert seen["analyze"] >= 1
    assert analysis.safety_confirmed is True
    assert analysis.service_category == ServiceCategory.handyman


def test_common_leak_still_calls_deepseek(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: object())
    called = {"n": 0}

    def fake_complete(*_a, **_k):
        called["n"] += 1
        return (
            '{"service_category":"plumbing","category_confidence":0.9,'
            '"urgency":"same_day","urgency_reason":"Active leak",'
            '"problem_summary":"My kitchen sink is leaking.",'
            '"facts":{},"hazards":[],"missing_details":["still_running"],'
            '"next_question":"Is water still leaking right now?"}'
        )

    monkeypatch.setattr("app.llm._complete", fake_complete)
    analysis, used_fallback = analyze(
        [ChatMessage(role="user", content="My kitchen sink has been leaking under the cabinet.")]
    )
    assert used_fallback is False
    assert called["n"] >= 1
    assert analysis.service_category == ServiceCategory.plumbing
    assert analysis.next_question


def test_keyword_fallback_does_not_search_just_because_the_message_is_long():
    analysis = fallback_analysis(
        "I have an issue with plumbing in my house and everything keeps leaking "
        "and I do not know what to do about it right now."
    )
    assert analysis.service_category == ServiceCategory.plumbing
    assert analysis.dispatch_ready is False
    assert analysis.next_question


def test_keyword_fallback_basement_flood():
    analysis = fallback_analysis(
        "Water started coming into my basement last night after the storm."
    )
    assert analysis.service_category == ServiceCategory.water_damage
    assert analysis.category_confidence >= 0.6


def test_keyword_fallback_ac():
    analysis = fallback_analysis("The AC is not cooling the upstairs at all.")
    assert analysis.service_category == ServiceCategory.hvac


def test_keyword_fallback_uses_full_history_not_last_negation():
    from app.models import ChatMessage

    history = [
        ChatMessage(
            role="user",
            content="Water started coming into my basement last night after the storm.",
        ),
        ChatMessage(
            role="user",
            content="Not near any outlets.",
        ),
    ]
    analysis = fallback_analysis("Not near any outlets.", history)
    assert analysis.service_category == ServiceCategory.water_damage


def test_keyword_fallback_ant_is_not_substring_of_want():
    analysis = fallback_analysis("I want someone to look at the kitchen sink leak.")
    assert analysis.service_category == ServiceCategory.plumbing


def test_keyword_fallback_ants_still_match_pest():
    analysis = fallback_analysis("There are ants all over the kitchen counters.")
    assert analysis.service_category == ServiceCategory.pest_control


def test_keyword_fallback_roof_stain():
    analysis = fallback_analysis(
        "There's a wet stain on the ceiling in the guest room after last week's storm."
    )
    assert analysis.service_category == ServiceCategory.roofing


def test_fallback_safety_reply_includes_911():
    text = fallback_safety_reply([Hazard.gas_leak], mode="escalate")
    assert "911" in text
    assert "safe" in text.lower()


def test_sanitize_safety_text_appends_911_if_missing():
    text = _sanitize_safety_text(
        "Please leave the house and wait outside until you know it is clear.",
        mode="escalate",
    )
    assert "911" in text


def test_fallback_problem_paragraph_uses_homeowner_chat():
    history = [
        ChatMessage(role="assistant", content="What are you noticing with the water?"),
        ChatMessage(
            role="user",
            content="The color is murky, the smell is very foul. Temperature is hot.",
        ),
        ChatMessage(role="user", content="I'm not sure"),
    ]
    text = fallback_problem_paragraph(history, problem_summary="ignored when chat exists")
    lowered = text.lower()
    assert "murky" in lowered
    assert "foul" in lowered
    assert "hot" in lowered
    assert "i'm not sure" in lowered
    assert "what are you noticing" not in lowered


def test_draft_problem_paragraph_falls_back_without_client(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: None)
    history = [
        ChatMessage(role="user", content="Kitchen sink leaking onto the floor."),
    ]
    text, used_fallback = draft_problem_paragraph(history, problem_summary="unused")
    assert used_fallback is True
    assert "kitchen sink leaking" in text.lower()


def test_draft_problem_paragraph_uses_model_text(monkeypatch):
    monkeypatch.setattr("app.llm._client", lambda **_k: object())
    monkeypatch.setattr(
        "app.llm._complete",
        lambda *_a, **_k: (
            "The water is murky and smells foul. It is happening on the hot water."
        ),
    )
    history = [
        ChatMessage(role="user", content="The color is murky and the smell is foul."),
    ]
    text, used_fallback = draft_problem_paragraph(
        history,
        problem_summary="Murky water",
        facts={"color": "murky"},
    )
    assert used_fallback is False
    assert "murky" in text.lower()
    assert "foul" in text.lower()


def test_sanitize_problem_paragraph_drops_greeting():
    text = _sanitize_problem_paragraph(
        "Hello Bob,\nThe kitchen sink is leaking under the cabinet.\nSincerely, Alex"
    )
    assert "Hello" not in text
    assert "Sincerely" not in text
    assert "kitchen sink is leaking" in text.lower()
