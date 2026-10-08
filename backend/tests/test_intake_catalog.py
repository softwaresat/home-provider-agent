from app.intake_catalog import (
    PROBLEMS,
    already_asked,
    problem_by_id,
    problems_for_category,
    turn_guidance,
    unanswered_questions,
)
from app.models import ServiceCategory


def test_catalog_entries_are_complete():
    assert 30 <= len(PROBLEMS) <= 45
    for problem in PROBLEMS:
        assert problem.description.strip()
        assert len(problem.examples) >= 2
        assert 2 <= len(problem.questions) <= 4
        cats = {item.priority for item in problem.questions}
        assert min(cats) <= 1


def test_no_hints_until_a_trade_is_known():
    assert turn_guidance(ServiceCategory.unknown, "My kitchen sink is leaking.") is None


def test_plumbing_hints_list_example_jobs_not_a_match():
    guidance = turn_guidance(ServiceCategory.plumbing, facts={}, asked=[])
    assert guidance is not None
    assert "not a diagnosis" in guidance.lower()
    assert "not a checklist" in guidance.lower()
    assert "leaking pipe or fixture" in guidance
    assert "clogged drain" in guidance
    assert "Ask at most ONE question" in guidance
    assert "dispatch_ready" in guidance
    # Do not dump every remaining catalog question as a script.
    assert "Can a technician reach the shutoff valve?" not in guidance


def test_unanswered_skips_only_llm_facts_not_keywords_in_text():
    problem = problem_by_id("leaking_fixture")
    assert problem is not None
    blob_facts = unanswered_questions(problem, facts={}, asked=[])
    collects = {item.collects for item in blob_facts}
    assert "still_running" in collects
    assert "location" in collects
    assert "shutoff_access" in collects

    remaining = unanswered_questions(
        problem,
        facts={
            "still_running": "yes, dripping",
            "location": "kitchen sink",
        },
        asked=[],
    )
    collects = {item.collects for item in remaining}
    assert "still_running" not in collects
    assert "location" not in collects
    assert "shutoff_access" in collects


def test_unanswered_skips_asked_questions():
    problem = problem_by_id("leaking_fixture")
    remaining = unanswered_questions(
        problem,
        facts={"still_running": "yes, dripping"},
        asked=["Which fixture is leaking, and which room is it in?"],
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


def test_guidance_stays_compact_when_facts_are_known():
    guidance = turn_guidance(
        ServiceCategory.plumbing,
        facts={"location": "basement pipe"},
        asked=["Which fixture is leaking, and which room is it in?"],
    )
    assert guidance is not None
    assert "Follow-ups already asked: 1" in guidance
    assert "leaking pipe or fixture" in guidance
    assert "Which fixture is leaking, and which room is it in?" not in guidance


def test_handyman_hints_do_not_depend_on_user_keywords():
    guidance = turn_guidance(
        ServiceCategory.handyman,
        "My smart lock randomly unlocks at 2am and the keypad is dead.",
        facts={},
        asked=[],
    )
    assert guidance is not None
    assert "garage door" in guidance
    assert "ignore these hints" in guidance.lower() or "unusual" in guidance.lower()


def test_problems_for_category_stays_in_trade():
    plumbing = problems_for_category(ServiceCategory.plumbing)
    assert plumbing
    assert all(item.category == ServiceCategory.plumbing for item in plumbing)
