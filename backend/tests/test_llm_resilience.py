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
      "service_category": "wizardry",
      "category_confidence": 9,
      "urgency": "super-urgent",
      "hazards": ["ghosts", "electrical"],
      "facts": "not-a-dict",
      "next_question": "Where is the leak?"
    }
    ```"""
    analysis = parse_analysis(raw)
    assert analysis.service_category == ServiceCategory.unknown
    assert analysis.category_confidence == 1.0
    assert analysis.urgency == Urgency.flexible
    assert [h.value for h in analysis.hazards] == ["electrical"]
    assert analysis.facts == {}


def test_partial_object_uses_defaults():
    analysis = parse_analysis('{"service_category": "hvac"}')
    assert analysis.service_category == ServiceCategory.hvac
    assert analysis.facts == {}
    assert analysis.next_question is None


def test_malformed_json_raises():
    try:
        parse_analysis("not json at all")
        assert False, "expected json error"
    except Exception:
        pass


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
