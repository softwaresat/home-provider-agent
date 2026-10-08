from app.intake_catalog import (
    already_asked,
    match_problem,
    turn_guidance,
    unanswered_questions,
)
from app.models import ServiceCategory


def test_match_leaking_sink():
    problem = match_problem(
        ServiceCategory.unknown,
        "My kitchen sink has been leaking under the cabinet since this morning.",
    )
    assert problem is not None
    assert problem.id == "leaking_fixture"
    assert problem.category == ServiceCategory.plumbing


def test_unanswered_skips_details_already_in_text():
    blob = (
        "My kitchen sink has been leaking under the cabinet since this morning. "
        "It's still dripping. I can turn off the valve under the sink."
    )
    problem = match_problem(ServiceCategory.plumbing, blob)
    remaining = unanswered_questions(problem, facts={}, asked=[], blob=blob)
    collects = {item.collects for item in remaining}
    assert "still_running" not in collects
    assert "location" not in collects
    assert "shutoff_access" not in collects


def test_unanswered_skips_known_facts_and_asked_questions():
    blob = "The pipe is leaking."
    problem = match_problem(ServiceCategory.plumbing, blob)
    remaining = unanswered_questions(
        problem,
        facts={"still_running": "yes, dripping"},
        asked=["Which fixture is leaking, and which room is it in?"],
        blob=blob,
    )
    collects = [item.collects for item in remaining]
    assert "still_running" not in collects
    assert "location" not in collects
    assert "shutoff_access" in collects


def test_already_asked_treats_paraphrase_as_redundant():
    assert already_asked(
        "Is water still leaking right now?",
        ["Is the water still running right now?"],
    )


def test_uncovered_problem_has_no_guidance():
    text = "My smart lock randomly unlocks at 2am and the keypad is dead."
    assert match_problem(ServiceCategory.unknown, text) is None
    assert turn_guidance(ServiceCategory.unknown, text, facts={}, asked=[]) is None
    assert unanswered_questions(None, blob=text) == []


def test_ambiguous_unknown_does_not_force_a_type():
    assert match_problem(ServiceCategory.unknown, "Something is wrong with the house.") is None


def test_guidance_lists_only_remaining_slots():
    blob = "There is a leaking pipe in the basement."
    guidance = turn_guidance(ServiceCategory.plumbing, blob, facts={}, asked=[])
    assert guidance is not None
    assert "leaking pipe or fixture" in guidance
    assert "still_running" in guidance
    assert "Ask at most ONE question" in guidance
    # Location is already in the blob (basement).
    assert "- [dispatch] location:" not in guidance


def test_want_does_not_match_pest_catalog():
    text = "I want someone to look at my kitchen sink. It has been leaking."
    problem = match_problem(ServiceCategory.unknown, text)
    assert problem is not None
    assert problem.category == ServiceCategory.plumbing
    assert problem.id != "indoor_pest"


def test_common_jobs_match_a_type():
    cases = [
        ("The downstairs toilet will not flush.", "toilet_issue", ServiceCategory.plumbing),
        ("The garbage disposal is humming and jammed.", "garbage_disposal", ServiceCategory.plumbing),
        ("Sewage is backing up through the floor drain.", "sewer_or_sump", ServiceCategory.plumbing),
        ("The garage door opener stopped halfway down.", "general_home_repair", ServiceCategory.handyman),
        ("We have bed bugs in the mattress.", "indoor_pest", ServiceCategory.pest_control),
        ("A gutter is pulling off after hail.", "roof_leak", ServiceCategory.roofing),
        ("The dishwasher won't start and shows an error.", "broken_appliance", ServiceCategory.appliance_repair),
    ]
    for text, problem_id, category in cases:
        problem = match_problem(ServiceCategory.unknown, text)
        assert problem is not None, text
        assert problem.id == problem_id, text
        assert problem.category == category, text


def test_niche_jobs_still_left_to_the_model():
    niche = [
        "The pool pump is making a grinding noise.",
        "I need a Level 2 EV charger installed in the garage.",
        "Our septic alarm is beeping.",
        "The solar inverter shows a red fault light.",
        "My smart lock randomly unlocks at 2am and the keypad is dead.",
    ]
    for text in niche:
        assert match_problem(ServiceCategory.unknown, text) is None, text
