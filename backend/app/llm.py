"""DeepSeek integration: JSON in, Pydantic out, retry once, then keyword fallback."""

from __future__ import annotations

import json
import re
from typing import Optional

from openai import OpenAI

from app import config
from app.models import ChatMessage, LLMAnalysis, ServiceCategory, Urgency

SYSTEM_PROMPT = """You are an intake analyst for a home-services marketplace.
You do NOT name, invent, or recommend businesses.
You do NOT give repair instructions for hazardous situations.
You do NOT ask for the homeowner's name, phone, email, or service address.
You do NOT ask for city or ZIP — those are collected in a separate location field.

Return ONLY a JSON object with this shape:
{
  "service_category": "plumbing|hvac|electrical|roofing|water_damage|pest_control|appliance_repair|handyman|unknown",
  "category_confidence": 0.0,
  "urgency": "emergency|same_day|within_week|flexible",
  "urgency_reason": "short reason",
  "problem_summary": "1-3 first-person sentences as the homeowner would write to a contractor (I/my). No snake_case. Do not say 'the homeowner'.",
  "facts": {"short_key": "human phrase, never snake_case (living room not living_room)"},
  "city": null,
  "zip_code": null,
  "hazards": [],
  "missing_details": ["important unknown facts"],
  "next_question": "ONE targeted question, or null if enough is known to search providers"
}

Valid hazards: gas_leak, fire_smoke, electrical, flood_electrical, carbon_monoxide.

Question guidance — ask only what is still missing; never ask two questions; never repeat:
Keep asking while important dispatch or safety details are missing. Do not stop after
one question if the job is still vague. Messy jobs may need several turns (what is
broken, where in the home, whether it is still happening, access, shutoff, storm, etc.).
Set next_question to null only when a dispatcher could search and brief a provider.
Never ask for city, ZIP, name, phone, email, or any address.
- Plumbing: where in the home, which fixture, whether it is still running, shutoff access
- HVAC: heating vs cooling, whether the unit is completely nonfunctional, thermostat/error
- Electrical: sparking, smoke, burning smell (safety), which room/circuit
- Roofing: leak location in the home, whether a recent storm caused it, interior dripping
- Water damage: source if known, still entering, near electrical equipment, which rooms
- Pest: type of pest if known, indoor vs outdoor, where seen
- Appliance: which appliance, what happens when they use it, age/error if known
- Vague: what they noticed, which part of the home, whether it is ongoing
- Access: crawlspace, locked gate, occupied unit — only if it would change dispatch

Prioritize safety-relevant missing details, then dispatch details.
If the user described an emergency (gas, fire, CO), set the matching hazard and urgency emergency.
"""

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

# Keyword fallback is deterministic and used when the LLM is missing or malformed.
CATEGORY_KEYWORDS: list[tuple[ServiceCategory, tuple[str, ...]]] = [
    (ServiceCategory.water_damage, (
        "flood", "flooding", "basement", "standing water", "water coming in",
        "water started coming", "water in the basement", "storm water",
    )),
    (ServiceCategory.plumbing, (
        "leak", "leaking", "pipe", "drain", "toilet", "faucet", "clog",
        "clogged", "sink", "water heater", "hot water", "sewer", "sump",
    )),
    (ServiceCategory.hvac, (
        "ac ", "a/c", "air condition", "furnace", "heater", "hvac",
        "not cooling", "not heating", "no cool air", "thermostat",
    )),
    (ServiceCategory.electrical, (
        "outlet", "breaker", "spark", "wiring", "electrician", "power out",
        "no power", "circuit", "panel",
    )),
    (ServiceCategory.roofing, (
        "roof", "shingle", "ceiling stain", "stain on the ceiling",
        "wet stain", "ceiling leak", "gutter", "ceiling",
    )),
    (ServiceCategory.pest_control, (
        "pest", "termite", "roach", "cockroach", "ant", "rodent",
        "mouse", "mice", "rat", "bed bug", "wasp", "infestation",
    )),
    (ServiceCategory.appliance_repair, (
        "dishwasher", "washer", "dryer", "fridge", "refrigerator",
        "oven", "stove", "microwave",
    )),
]


def strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = FENCE_RE.sub("", cleaned).strip()
    return cleaned


def parse_analysis(raw: str) -> LLMAnalysis:
    cleaned = strip_fences(raw)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM output is not a JSON object")
    return LLMAnalysis.model_validate(data)


def _history_blob(history: list[ChatMessage] | None, user_text: str) -> str:
    parts: list[str] = []
    if history:
        parts.extend(message.content for message in history if message.role == "user")
    if user_text and user_text not in parts:
        parts.append(user_text)
    return " ".join(parts).strip()


def fallback_analysis(user_text: str, history: list[ChatMessage] | None = None) -> LLMAnalysis:
    """Rule-based classifier used when DeepSeek is unavailable or invalid."""
    blob = _history_blob(history, user_text)
    lowered = f" {blob.lower()} "
    category = ServiceCategory.unknown
    confidence = 0.2
    for candidate, keywords in CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            category = candidate
            confidence = 0.75
            break

    urgency = Urgency.flexible
    urgency_reason = "Not enough information to judge timing."
    if any(bit in lowered for bit in (
        "flood", "spark", "gas leak", "smell gas", "smells like gas",
        "on fire", "carbon monoxide", "no cooling", "not cooling",
    )):
        urgency = Urgency.same_day
        urgency_reason = "The description suggests a problem that should be addressed soon."
    if any(bit in lowered for bit in (
        "flood", "spark", "gas leak", "smell gas", "on fire", "carbon monoxide",
    )):
        urgency = Urgency.emergency
        urgency_reason = "The description includes an urgent or hazardous signal."
    elif any(bit in lowered for bit in (
        "leak", "clog", "no hot water", "this morning", "overflow",
        "last night", "right now", "90 degree",
    )):
        urgency = Urgency.same_day
        urgency_reason = "The description suggests a problem that should be addressed soon."

    summary = blob.strip() or user_text.strip()
    if len(summary) > 280:
        summary = summary[:277] + "..."

    next_question = _fallback_question(category)
    return LLMAnalysis(
        service_category=category,
        category_confidence=confidence,
        urgency=urgency,
        urgency_reason=urgency_reason,
        problem_summary=summary or "Home problem reported.",
        facts={},
        next_question=next_question,
        missing_details=["location", "problem details"],
    )


def _fallback_question(category: ServiceCategory) -> str:
    questions = {
        ServiceCategory.plumbing: "Where is the leak or clog, and is water still running?",
        ServiceCategory.water_damage: "Is water still coming in, and is it near any electrical outlets or the breaker panel?",
        ServiceCategory.hvac: "Is this a heating or cooling problem, and is the unit completely nonfunctional?",
        ServiceCategory.electrical: "Is there sparking, smoke, or a burning smell?",
        ServiceCategory.roofing: "Where is the roof leaking, and did it start after a recent storm?",
        ServiceCategory.pest_control: "What kind of pest have you seen, and is it inside the home?",
        ServiceCategory.appliance_repair: "Which appliance is broken, and what happens when you try to use it?",
        ServiceCategory.handyman: "Which part of the home is affected, and what did you notice?",
        ServiceCategory.unknown: "Which part of the home is affected, and what did you notice happening?",
    }
    return questions[category]


def _client() -> Optional[OpenAI]:
    if not config.deepseek_configured():
        return None
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=30.0,
    )


def _complete(client: OpenAI, messages: list[dict], use_json_mode: bool) -> str:
    kwargs = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }
    if use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty model response")
    return content


def analyze(history: list[ChatMessage]) -> tuple[LLMAnalysis, bool]:
    """Return (analysis, used_fallback)."""
    last_user = ""
    for message in reversed(history):
        if message.role == "user":
            last_user = message.content
            break

    client = _client()
    if client is None:
        return fallback_analysis(last_user, history), True

    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for message in history:
        if message.role in {"user", "assistant"}:
            api_messages.append({"role": message.role, "content": message.content})

    last_error = None
    use_json_mode = True
    for attempt in range(2):
        try:
            if attempt == 1 and last_error:
                api_messages = api_messages + [{
                    "role": "user",
                    "content": (
                        "Your previous output failed validation: "
                        f"{last_error}. Return ONLY a valid JSON object matching the schema."
                    ),
                }]
            raw = _complete(client, api_messages, use_json_mode=use_json_mode)
            return parse_analysis(raw), False
        except Exception as exc:  # noqa: BLE001 — we intentionally fall back
            last_error = str(exc)
            lowered = last_error.lower()
            if "response_format" in lowered or "json_object" in lowered:
                use_json_mode = False

    return fallback_analysis(last_user, history), True
