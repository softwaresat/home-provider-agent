"""DeepSeek integration: JSON in, Pydantic out, retry once, then keyword fallback."""

from __future__ import annotations

import json
import re
from typing import Optional

from openai import OpenAI

from app import config
from app.models import ChatMessage, Hazard, LLMAnalysis, ServiceCategory, Urgency

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
  "missing_details": ["dispatch-critical unknowns only"],
  "next_question": "ONE targeted question, or null if a provider can be matched",
  "dispatch_ready": false
}

Valid hazards: gas_leak, fire_smoke, electrical, flood_electrical, carbon_monoxide.

Dispatch readiness — maximize information per question, not question count:
A lead is ready when you know the main symptom, roughly where/how widespread it is,
urgency/timing, and any safety issue that would change routing. You do not need a
root cause, a full diagnosis, or a catalog checklist.
Set dispatch_ready true and next_question null as soon as a dispatcher could pick a
trade and brief a contractor. Typical jobs need 0–3 follow-ups. Vague jobs may need
a few more. Do not keep asking because extra diagnostic detail would be nice.
Do not ask about water pressure, neighbors, flushing fixtures, brand/model, or
"have you tried…" unless the answer would change the trade, urgency, or safety.
If the opening message is already enough, ask nothing.
If the homeowner does not know, record that slot as unknown in facts (not as a
negative finding). Keep every fact and the problem_summary already collected —
never replace problem_summary with a shrug ("I am not sure") or a chat transcript.
If a trade can already be briefed, set next_question to null and dispatch_ready
true. Otherwise ask a different useful question — never the same slot, never a
canned leak/clog substitute. Explicit "no" / "not leaking" belongs in facts as a
confirmed negative, distinct from unknown.
Extract every useful detail they already said into facts and problem_summary.

Question rules: never ask two questions; never repeat; never ask city, ZIP, name,
phone, email, or any address.
A short optional "intake hints" block may appear after a trade is known. It lists
example jobs, not a match and not a script. Use at most one hint, and only if it
would change dispatch. Ignore hints for unusual or mixed-trade jobs.
If the user described an emergency (gas, fire, CO), set the matching hazard and urgency emergency.
"""

SAFETY_REPLY_PROMPT = """You write the in-chat message for a home-services intake agent after Python
already classified a safety emergency. You do not decide whether it is actually dangerous.

Rules:
- Do NOT give repair, DIY, or diagnostic steps (no valves, sniff tests, "check the stove", mixing anything).
- Do NOT name, invent, or recommend businesses.
- Do NOT ask for name, phone, email, city, ZIP, or any address.
- Do NOT use markdown, bullets, or a greeting.

Write 3-6 short sentences in second person, calm, and specific to what the homeowner said.
You MUST tell them to get to safety now, call 911 from a safe place, and that we will not
look up contractors until they confirm everyone is safe.
Return ONLY the message text.
"""

CAUTION_REPLY_PROMPT = """You write a short caution for a home-services intake agent.
Python already flagged an electrical or water-near-electrical hazard. Contractor search may continue.

Rules:
- Do NOT give detailed DIY repair steps.
- You MAY say to stay away from the hazard and call 911 if there is fire, smoke, or a shock.
- Do NOT name or recommend businesses.
- Do NOT ask for contact details or an address.

Write 2-4 short sentences in second person, specific to what they said.
Return ONLY the message text.
"""

RESUME_REPLY_PROMPT = """You write a short resume message after a homeowner confirmed they are safe.
Python already cleared the emergency hold. Continue toward finding a contractor.

Rules:
- Do NOT diagnose or give repair steps.
- Do NOT name businesses.
- Acknowledge they are safe. Say you can keep helping find a provider.
- Do not ask for name, phone, email, city, ZIP, or address.

Write 2-3 short sentences. Return ONLY the message text.
"""

EMAIL_PROBLEM_PROMPT = """You write the problem paragraph of a homeowner's email to a contractor.
Python already has the greeting, service timing, address, phone, and signature. You write
ONLY the description of the problem.

Rules:
- First person (I/my), as the homeowner would write it.
- Use only the chat transcript and any collected notes. Do not invent symptoms, causes,
  or a diagnosis.
- Include contractor-useful details they already gave (what they notice, where/how
  widespread, timing). If they said they do not know something, say that it is unknown
  rather than turning it into a no.
- Do not name, invent, or recommend businesses.
- Do not include name, phone, email, city, ZIP, or any street address.
- Do not greet, sign off, or use markdown or bullet labels.
- 2-6 short sentences. Return ONLY the paragraph text.
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
        "pest", "termite", "roach", "cockroach", "ants", "ant", "rodent",
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


def _keyword_hit(text: str, keyword: str) -> bool:
    """Match a keyword as a token, not a substring of another word (ant vs want)."""
    needle = (keyword or "").strip().lower()
    if not needle:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


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
    lowered = blob.lower()
    category = ServiceCategory.unknown
    confidence = 0.2
    for candidate, keywords in CATEGORY_KEYWORDS:
        if any(_keyword_hit(lowered, keyword) for keyword in keywords):
            category = candidate
            confidence = 0.75
            break

    urgency, urgency_reason = _urgency_from_text(lowered)

    summary = blob.strip() or user_text.strip()
    if len(summary) > 280:
        summary = summary[:277] + "..."

    words = len(re.findall(r"[a-z0-9]+", blob.lower()))
    detailed = category != ServiceCategory.unknown and words >= 16
    if detailed:
        next_question = None
        missing_details: list[str] = []
        dispatch_ready = True
    else:
        next_question = _fallback_question(category)
        missing_details = ["problem details"]
        dispatch_ready = False
    return LLMAnalysis(
        service_category=category,
        category_confidence=confidence,
        urgency=urgency,
        urgency_reason=urgency_reason,
        problem_summary=summary or "Home problem reported.",
        facts={},
        next_question=next_question,
        missing_details=missing_details,
        dispatch_ready=dispatch_ready,
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


def _client(timeout: float = 30.0) -> Optional[OpenAI]:
    if not config.deepseek_configured():
        return None
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=timeout,
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


def _urgency_from_text(lowered: str) -> tuple[Urgency, str]:
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
    return urgency, urgency_reason


def analyze(
    history: list[ChatMessage],
    intake_guidance: str | None = None,
) -> tuple[LLMAnalysis, bool]:
    """Return (analysis, used_fallback).

    DeepSeek always runs when configured. Keyword fallback is last resort
    if the model is missing or returns invalid JSON.
    """
    last_user = ""
    for message in reversed(history):
        if message.role == "user":
            last_user = message.content
            break

    client = _client()
    if client is None:
        return fallback_analysis(last_user, history), True

    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if intake_guidance:
        api_messages.append({"role": "system", "content": intake_guidance})
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


def _hazard_labels(hazards: list[Hazard]) -> str:
    labels = {
        Hazard.gas_leak: "gas leak / gas odor",
        Hazard.fire_smoke: "fire or smoke",
        Hazard.carbon_monoxide: "carbon monoxide",
        Hazard.electrical: "electrical sparking or burning",
        Hazard.flood_electrical: "water near electrical equipment",
    }
    names = [labels.get(h, h.value) for h in hazards]
    return ", ".join(names) if names else "unspecified hazard"


def fallback_safety_reply(hazards: list[Hazard], mode: str = "escalate") -> str:
    from app.safety import advice_for

    if mode == "resume":
        return (
            "Thanks for confirming you are safe. I can continue helping you find a provider. "
            "I still will not diagnose the problem."
        )
    canned = advice_for(hazards)
    if canned:
        if mode == "escalate":
            return (
                canned
                + " If you have reached safety and still need a contractor, tell me you are safe."
            )
        return canned
    return (
        "Please get to safety and call 911 if this is an emergency. "
        "I will not look up contractors until you confirm everyone is safe."
    )


def _sanitize_safety_text(raw: str, mode: str) -> str:
    text = strip_fences(raw).strip().strip('"')
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 20:
        raise ValueError("Safety reply too short")
    if len(text) > 900:
        text = text[:897].rsplit(" ", 1)[0] + "..."
    lowered = text.lower()
    if mode == "escalate" and "911" not in lowered and "emergency" not in lowered:
        text = text.rstrip(".") + ". From a safe place, call 911."
    return text


def fallback_problem_paragraph(
    history: list[ChatMessage] | None,
    problem_summary: str = "",
) -> str:
    """Homeowner's own words when DeepSeek is unavailable. Not a scripted symptom list."""
    lines: list[str] = []
    for message in history or []:
        if message.role != "user":
            continue
        text = " ".join((message.content or "").split())
        if text:
            lines.append(text)
    if lines:
        return " ".join(lines)
    return " ".join((problem_summary or "").split())


def _transcript_packet(
    history: list[ChatMessage] | None,
    problem_summary: str,
    facts: dict[str, str] | None,
) -> str:
    blocks: list[str] = ["Homeowner chat:"]
    if history:
        for message in history:
            if message.role not in {"user", "assistant"}:
                continue
            content = " ".join((message.content or "").split())
            if not content:
                continue
            label = "Homeowner" if message.role == "user" else "Assistant"
            blocks.append(f"{label}: {content}")
    else:
        blocks.append("(no chat messages)")
    summary = " ".join((problem_summary or "").split())
    if summary:
        blocks.extend(["", f"Collected summary: {summary}"])
    if facts:
        note_lines = [f"- {key}: {value}" for key, value in facts.items() if value]
        if note_lines:
            blocks.extend(["", "Collected notes:"] + note_lines)
    return "\n".join(blocks)


def _sanitize_problem_paragraph(raw: str) -> str:
    text = strip_fences(raw).strip().strip('"')
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(("hello ", "dear ", "hi ")):
            continue
        if lowered.startswith(("sincerely", "thank you", "thanks,")):
            continue
        kept.append(stripped)
    text = " ".join(kept)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 8:
        raise ValueError("Problem paragraph too short")
    if len(text) > 1500:
        text = text[:1497].rsplit(" ", 1)[0] + "..."
    return text


def draft_problem_paragraph(
    history: list[ChatMessage] | None,
    problem_summary: str = "",
    facts: dict[str, str] | None = None,
) -> tuple[str, bool]:
    """Return (paragraph, used_fallback) from the intake transcript."""
    fallback = fallback_problem_paragraph(history, problem_summary)
    client = _client(timeout=12.0)
    if client is None:
        return fallback, True

    api_messages = [
        {"role": "system", "content": EMAIL_PROBLEM_PROMPT},
        {"role": "user", "content": _transcript_packet(history, problem_summary, facts)},
    ]
    try:
        raw = _complete(client, api_messages, use_json_mode=False)
        return _sanitize_problem_paragraph(raw), False
    except Exception:  # noqa: BLE001 — envelope still ships; wording may fall back
        return fallback, True


def safety_reply(
    user_text: str,
    hazards: list[Hazard],
    mode: str = "escalate",
) -> tuple[str, bool]:
    """Return (message, used_fallback). Python owns the hold; this is copy only."""
    prompt = {
        "escalate": SAFETY_REPLY_PROMPT,
        "caution": CAUTION_REPLY_PROMPT,
        "resume": RESUME_REPLY_PROMPT,
    }.get(mode, SAFETY_REPLY_PROMPT)
    client = _client(timeout=12.0)
    if client is None:
        return fallback_safety_reply(hazards, mode), True

    api_messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": (
                f"Classified hazards: {_hazard_labels(hazards)}.\n"
                f"Homeowner said: {user_text.strip() or '(no text)'}"
            ),
        },
    ]
    try:
        raw = _complete(client, api_messages, use_json_mode=False)
        return _sanitize_safety_text(raw, mode), False
    except Exception:  # noqa: BLE001 — copy may fall back; the hold still applies
        return fallback_safety_reply(hazards, mode), True
