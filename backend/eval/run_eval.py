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
from app.models import ContactInfo, LeadStatus, ServiceCategory, Stage  # noqa: E402

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

    if session.stage == Stage.safety_escalated and not scenario.get("expect_escalation"):
        pass
    elif session.stage == Stage.safety_escalated and scenario.get("expect_escalation"):
        # Optional: continue after "I'm safe" if answers remain, but do not force a lead.
        pass
    elif session.providers:
        agent.handle_select(session, session.providers[0].place_id)
        agent.handle_contact(session, DEFAULT_CONTACT)
        user_turns += 1  # select + contact are UI actions; count contact as one completion step

    lead = session.lead
    chosen = lead.selected_provider if lead else None
    reasons = chosen.match_reasons if chosen else []
    trade_confirmed = any(
        "Listing type matches" in reason or "name indicates" in reason for reason in reasons
    )
    call_center_flag = any("call center" in reason for reason in reasons)
    category = agent.effective_category(session).value
    urgency = session.analysis.urgency.value if session.analysis else None
    expected_categories = _as_list(scenario.get("expected_category"))
    expected_urgency = _as_list(scenario.get("expected_urgency"))
    category_ok = category in expected_categories if expected_categories else True
    if scenario.get("allow_unknown_until_followup") and category in expected_categories:
        category_ok = True
    urgency_ok = urgency in expected_urgency if expected_urgency else True
    escalated = session.stage == Stage.safety_escalated or (
        lead is not None and lead.status == LeadStatus.safety_escalated
    )
    escalation_ok = escalated == bool(scenario.get("expect_escalation"))
    complete = lead is not None and lead.status == LeadStatus.complete
    simulated_conversion = complete and not scenario.get("expect_escalation")
    search_reached = session.stage in {
        Stage.showing_providers,
        Stage.no_results,
        Stage.collecting_contact,
        Stage.lead_ready,
    }

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "category": category,
        "category_ok": category_ok,
        "urgency": urgency,
        "urgency_ok": urgency_ok,
        "escalated": escalated,
        "escalation_ok": escalation_ok,
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
    }


def render_results(rows: list[dict], record_note: str) -> str:
    converted = sum(1 for row in rows if row["simulated_conversion"])
    eligible = [row for row in rows if not _scenario_expects_escalation(row["id"])]
    converted_eligible = sum(1 for row in eligible if row["simulated_conversion"])
    category_acc = sum(1 for row in rows if row["category_ok"]) / len(rows)
    urgency_acc = sum(1 for row in rows if row["urgency_ok"]) / len(rows)
    escalation_acc = sum(1 for row in rows if row["escalation_ok"]) / len(rows)
    quality_ok = sum(1 for row in eligible if row["quality_ok"])
    lines = [
        "# Prototype evaluation results",
        "",
        "These numbers are **measured on this prototype**, from scripted scenarios.",
        "",
        "- **Funnel completion** = the scenario reached a `complete` lead. The script answers",
        "  follow-ups from a fixed list, auto-selects the top-ranked listing, and submits",
        "  contact + address + consent. It shows the agent never gets stuck; it is **not** a",
        "  human conversion rate (real users can drop off at any step).",
        "- **Quality-checked lead** = funnel completed **and** the chosen provider's trade is",
        "  confirmed (Google type or business name) **and** it is not flagged as a likely",
        "  national call center. This is a proxy for \"would a provider act on it\", not",
        "  provider acceptance.",
        "",
        f"- DeepSeek configured: `{config.deepseek_configured()}` (model `{config.DEEPSEEK_MODEL}`)",
        f"- Places search mode: `{config.search_mode()}`",
        f"- Scenarios: {len(rows)}",
        f"- Category match: {category_acc:.0%} ({sum(1 for r in rows if r['category_ok'])}/{len(rows)})",
        f"- Urgency in expected set: {urgency_acc:.0%} ({sum(1 for r in rows if r['urgency_ok'])}/{len(rows)})",
        f"- Escalation correctness: {escalation_acc:.0%} ({sum(1 for r in rows if r['escalation_ok'])}/{len(rows)})",
        f"- Funnel completion (all scenarios): {converted}/{len(rows)}",
        f"- Funnel completion (non-emergency scenarios): {converted_eligible}/{len(eligible)}",
        f"- Quality-checked leads (non-emergency scenarios): {quality_ok}/{len(eligible)}",
        f"- Non-emergency scenarios that reached provider search: {sum(1 for r in eligible if r['search_reached'])}/{len(eligible)}",
        "",
        record_note,
        "",
        "| Scenario | Category | Cat OK | Urgency | Esc | Qs | Turns | Providers | Source | Lead | Chosen provider | Trade confirmed | Quality OK |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {title} | {category} | {category_ok} | {urgency} | {escalated} | {questions_asked} | {user_turns} | {providers} | {search_source} | {lead_status} | {provider_name} | {trade_confirmed} | {quality_ok} |".format(
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
        lines.append(
            f"- **{row['title']}**: stage `{row['stage']}`; missing required: `{missing}`; "
            f"LLM fallback used: `{row['llm_fallback_used']}`"
        )
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
