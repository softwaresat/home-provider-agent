"""Run scripted prototype scenarios against the agent.

This reports lead completeness and simulated conversion as prototype proxies.
It is not a production conversion rate or provider acceptance rate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app import agent, config, places  # noqa: E402
from app.models import CAUTION_HAZARDS, ContactInfo, LeadStatus, ServiceCategory, Stage  # noqa: E402
from app.ranking import is_trade_match  # noqa: E402

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"
RESULTS_PATH = Path(__file__).resolve().parent / "results.md"
MAX_TURNS = 12

DEFAULT_CONTACT = ContactInfo(
    name="Eval Homeowner",
    phone="512-555-0199",
    email="eval@example.com",
    service_address="100 Congress Ave, Austin, TX",
    consent_to_share=True,
)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _assistant_text(session) -> str:
    for message in reversed(session.messages):
        if message.role == "assistant":
            return message.content
    return ""


def _next_reply(scenario: dict, assistant: str, used: int) -> tuple[str, int]:
    lowered = assistant.lower()
    answers = scenario.get("answers") or []
    if any(token in lowered for token in ("zip", "city", "location", "what area")):
        return scenario.get("location_reply") or "Austin, TX 78704", used
    if used < len(answers):
        return answers[used], used + 1
    return "That's everything I know.", used


def _has_caution(session) -> bool:
    return any(h in CAUTION_HAZARDS for h in (session.hazards or []))


def _mentions_911(session) -> bool:
    blob = " ".join(
        [
            _assistant_text(session),
            session.safety_advice or "",
        ]
    ).lower()
    return "911" in blob or "emergency services" in blob


def run_scenario(scenario: dict) -> dict:
    session = agent.create_session(scenario["id"])
    used = 0
    agent.handle_location(session, scenario.get("location_reply") or "Austin, TX 78704")
    agent.handle_user_message(session, scenario["opening"])
    user_turns = 1

    for _ in range(MAX_TURNS):
        if session.stage in {
            Stage.showing_providers,
            Stage.no_results,
            Stage.collecting_contact,
            Stage.lead_ready,
        }:
            break
        if session.stage == Stage.safety_escalated:
            break
        reply, used = _next_reply(scenario, _assistant_text(session), used)
        agent.handle_user_message(session, reply)
        user_turns += 1

    if session.stage == Stage.safety_escalated:
        for reply in scenario.get("hold_replies") or []:
            agent.handle_user_message(session, reply)
            user_turns += 1

    pre_lock_category = agent.effective_category(session)
    pre_lock_summary = session.analysis.problem_summary if session.analysis else None

    if session.stage == Stage.safety_escalated and scenario.get("expect_escalation"):
        pass
    elif session.stage == Stage.safety_escalated:
        pass
    elif session.providers:
        agent.handle_select(session, session.providers[0].place_id)
        agent.handle_contact(session, DEFAULT_CONTACT)
        user_turns += 1

    lock_ok = True
    if scenario.get("after_complete"):
        agent.handle_user_message(session, scenario["after_complete"])
        user_turns += 1
        lock_ok = (
            session.stage == Stage.lead_ready
            and agent.effective_category(session) == pre_lock_category
            and (session.analysis.problem_summary if session.analysis else None) == pre_lock_summary
        )

    lead = session.lead
    chosen = lead.selected_provider if lead else None
    category = agent.effective_category(session)
    trade_confirmed = bool(
        chosen
        and (
            getattr(chosen, "trade_confirmed", False)
            or is_trade_match(chosen, category)
        )
    )
    reasons = chosen.match_reasons if chosen else []
    call_center_flag = any("call center" in reason for reason in reasons)
    expected_categories = _as_list(scenario.get("expected_category"))
    expected_urgency = _as_list(scenario.get("expected_urgency"))
    category_ok = category.value in expected_categories if expected_categories else True
    if scenario.get("allow_unknown_until_followup") and category.value in expected_categories:
        category_ok = True
    urgency = session.analysis.urgency.value if session.analysis else None
    urgency_ok = urgency in expected_urgency if expected_urgency else True
    if scenario.get("expect_escalation") and not session.analysis:
        urgency_ok = True
    escalated = session.stage == Stage.safety_escalated or (
        lead is not None and lead.status == LeadStatus.safety_escalated
    )
    expect_escalation = bool(scenario.get("expect_escalation"))
    still_escalated = session.stage == Stage.safety_escalated
    expect_still = scenario.get("expect_still_escalated")
    if expect_still is None:
        still_ok = True if not expect_escalation else still_escalated
    else:
        still_ok = still_escalated == bool(expect_still)
    escalation_ok = (escalated == expect_escalation) and still_ok
    if scenario.get("expect_caution"):
        caution_ok = _has_caution(session) and not escalated
    else:
        caution_ok = True
    if scenario.get("expect_911"):
        nine_ok = _mentions_911(session)
    else:
        nine_ok = True
    no_search_ok = True
    if scenario.get("expect_no_search"):
        no_search_ok = len(session.providers) == 0
    if scenario.get("expect_lock"):
        lock_checked = lock_ok
    else:
        lock_checked = True
    complete = lead is not None and lead.status == LeadStatus.complete
    simulated_conversion = complete and not expect_escalation
    search_reached = session.stage in {
        Stage.showing_providers,
        Stage.no_results,
        Stage.collecting_contact,
        Stage.lead_ready,
    }
    edge_ok = caution_ok and nine_ok and no_search_ok and lock_checked

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "notes": scenario.get("notes") or "",
        "category": category.value,
        "category_ok": category_ok,
        "urgency": urgency or "n/a",
        "urgency_ok": urgency_ok,
        "escalated": escalated,
        "escalation_ok": escalation_ok,
        "caution_ok": caution_ok,
        "nine_ok": nine_ok,
        "no_search_ok": no_search_ok,
        "lock_ok": lock_checked,
        "edge_ok": edge_ok,
        "questions_asked": session.questions_asked,
        "user_turns": user_turns,
        "providers": len(session.providers),
        "search_source": session.search_source or "none",
        "lead_status": lead.status.value if lead else "none",
        "missing_required": ",".join(lead.missing_required) if lead else "",
        "llm_fallback_used": session.llm_fallback_used,
        "simulated_conversion": simulated_conversion,
        "search_reached": search_reached,
        "stage": session.stage.value,
        "provider_name": chosen.name if chosen else "",
        "trade_confirmed": trade_confirmed,
        "quality_ok": simulated_conversion and trade_confirmed and not call_center_flag,
        "last_assistant": _assistant_text(session)[:220],
    }


def render_results(rows: list[dict], record_note: str) -> str:
    converted = sum(1 for row in rows if row["simulated_conversion"])
    eligible = [row for row in rows if not _scenario_expects_escalation(row["id"])]
    converted_eligible = sum(1 for row in eligible if row["simulated_conversion"])
    category_acc = sum(1 for row in rows if row["category_ok"]) / len(rows)
    urgency_acc = sum(1 for row in rows if row["urgency_ok"]) / len(rows)
    escalation_acc = sum(1 for row in rows if row["escalation_ok"]) / len(rows)
    edge_acc = sum(1 for row in rows if row["edge_ok"]) / len(rows)
    quality_ok = sum(1 for row in eligible if row["quality_ok"])
    lines = [
        "# Prototype evaluation results",
        "",
        "Ten **real-life edge cases**, measured live against this prototype.",
        "",
        "- **Funnel completion** = the scenario reached a `complete` lead. The script answers",
        "  follow-ups from a fixed list, auto-selects the top-ranked listing, and submits",
        "  contact + address + consent. It is **not** a human conversion rate.",
        "- **Quality-checked lead** = funnel completed **and** the chosen provider's trade is",
        "  confirmed **and** it is not flagged as a likely national call center.",
        "- **Edge OK** = caution vs 911-hold, 911 copy on emergencies, no search during a hold,",
        "  and completed-lead lock all matched the scenario.",
        "",
        f"- DeepSeek configured: `{config.deepseek_configured()}` (model `{config.DEEPSEEK_MODEL}`)",
        f"- Places search mode: `{config.search_mode()}`",
        f"- Scenarios: {len(rows)}",
        f"- Category match: {category_acc:.0%} ({sum(1 for r in rows if r['category_ok'])}/{len(rows)})",
        f"- Urgency in expected set: {urgency_acc:.0%} ({sum(1 for r in rows if r['urgency_ok'])}/{len(rows)})",
        f"- Escalation correctness: {escalation_acc:.0%} ({sum(1 for r in rows if r['escalation_ok'])}/{len(rows)})",
        f"- Edge-case checks: {edge_acc:.0%} ({sum(1 for r in rows if r['edge_ok'])}/{len(rows)})",
        f"- Funnel completion (all scenarios): {converted}/{len(rows)}",
        f"- Funnel completion (non-emergency scenarios): {converted_eligible}/{len(eligible)}",
        f"- Quality-checked leads (non-emergency scenarios): {quality_ok}/{len(eligible)}",
        f"- Non-emergency scenarios that reached provider search: {sum(1 for r in eligible if r['search_reached'])}/{len(eligible)}",
        "",
        record_note,
        "",
        "| Scenario | Category | Cat OK | Urgency | Esc | Edge | Qs | Turns | Providers | Source | Lead | Chosen provider | Trade | Quality |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {title} | {category} | {category_ok} | {urgency} | {escalated} | {edge_ok} | {questions_asked} | {user_turns} | {providers} | {search_source} | {lead_status} | {provider_name} | {trade_confirmed} | {quality_ok} |".format(
                **row
            )
        )
    lines.extend([
        "",
        "## Per-scenario notes",
        "",
    ])
    for row in rows:
        missing = row["missing_required"] or "none"
        extra = row["notes"]
        lines.append(
            f"- **{row['title']}**: {extra} Stage `{row['stage']}`; missing `{missing}`; "
            f"fallback `{row['llm_fallback_used']}`; caution `{row['caution_ok']}`; "
            f"911 `{row['nine_ok']}`; no-search `{row['no_search_ok']}`; lock `{row['lock_ok']}`."
        )
        if row["last_assistant"]:
            snippet = row["last_assistant"].replace("\n", " ")
            lines.append(f"  Last assistant: {snippet}")
    lines.append("")
    return "\n".join(lines)


def _scenario_expects_escalation(scenario_id: str) -> bool:
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    for item in scenarios:
        if item["id"] == scenario_id:
            return bool(item.get("expect_escalation"))
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record-fixture",
        action="store_true",
        help="If live Places search works, save listings into the fallback fixture (dev-only).",
    )
    args = parser.parse_args()
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    rows = [run_scenario(item) for item in scenarios]

    record_note = "Fallback fixture was not updated."
    if args.record_fixture:
        live, source, error = places.search_text(ServiceCategory.plumbing, "Austin, TX")
        if source == "google_places" and live:
            places.write_fallback_fixture(live)
            record_note = f"Recorded {len(live)} live Places listings into `fixtures/fallback_providers.json` (dev-only cache)."
        else:
            record_note = f"Did not record fixture (source={source}, error={error})."

    RESULTS_PATH.write_text(render_results(rows, record_note), encoding="utf-8")
    print(RESULTS_PATH.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
