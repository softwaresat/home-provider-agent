"""Optional follow-up hints, looked up from the current problem and known facts.

The LLM still writes the question. This file is not a questionnaire and not a
limit on which problems the agent can handle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import ServiceCategory

MAX_HINTS = 3

PRIORITY_SAFETY = 0
PRIORITY_DISPATCH = 1
PRIORITY_OPTIONAL = 2

_BAND = {
    PRIORITY_SAFETY: "safety",
    PRIORITY_DISPATCH: "dispatch",
    PRIORITY_OPTIONAL: "optional",
}


@dataclass(frozen=True)
class CatalogQuestion:
    id: str
    collects: str
    question: str
    priority: int
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProblemType:
    id: str
    category: ServiceCategory
    label: str
    match_keywords: tuple[str, ...]
    questions: tuple[CatalogQuestion, ...]


# High-frequency home-service jobs. Unmatched text is left to the LLM
# (solar, pool, septic, EV charger, well pump, smart home, etc.).
PROBLEMS: tuple[ProblemType, ...] = (
    ProblemType(
        id="leaking_fixture",
        category=ServiceCategory.plumbing,
        label="leaking pipe or fixture",
        match_keywords=("leak", "leaking", "dripping", "pipe", "faucet", "sink", "shower valve"),
        questions=(
            CatalogQuestion(
                id="still_active",
                collects="still_running",
                question="Is water still leaking right now?",
                priority=PRIORITY_SAFETY,
                aliases=("still dripping", "still leaking", "still running", "shut off", "stopped leaking"),
            ),
            CatalogQuestion(
                id="where",
                collects="location",
                question="Which fixture is leaking, and which room is it in?",
                priority=PRIORITY_DISPATCH,
                aliases=("kitchen", "bathroom", "basement", "laundry", "sink", "toilet", "shower", "tub"),
            ),
            CatalogQuestion(
                id="shutoff",
                collects="shutoff_access",
                question="Can a technician reach the shutoff valve?",
                priority=PRIORITY_DISPATCH,
                aliases=("shutoff", "shut off", "valve under", "turned it off"),
            ),
        ),
    ),
    ProblemType(
        id="clogged_drain",
        category=ServiceCategory.plumbing,
        label="clogged drain or toilet",
        match_keywords=("clog", "clogged", "drain", "backup", "overflow", "won't flush"),
        questions=(
            CatalogQuestion(
                id="overflowing",
                collects="overflowing",
                question="Is it overflowing, or did you stop it in time?",
                priority=PRIORITY_SAFETY,
                aliases=("overflow", "overflowed", "not overflowing", "shut the water"),
            ),
            CatalogQuestion(
                id="which_drain",
                collects="location",
                question="Which drain or toilet, and is more than one fixture backing up?",
                priority=PRIORITY_DISPATCH,
                aliases=("toilet", "shower", "sink", "tub", "downstairs", "bathroom"),
            ),
        ),
    ),
    ProblemType(
        id="water_heater",
        category=ServiceCategory.plumbing,
        label="water heater or no hot water",
        match_keywords=("water heater", "no hot water", "hot water"),
        questions=(
            CatalogQuestion(
                id="any_hot",
                collects="any_hot_water",
                question="Is there any hot water at all, or is every faucet cold?",
                priority=PRIORITY_DISPATCH,
                aliases=("no hot water", "completely cold", "every faucet", "all faucets"),
            ),
            CatalogQuestion(
                id="heater_place",
                collects="location",
                question="Where is the water heater (garage, closet, attic)?",
                priority=PRIORITY_DISPATCH,
                aliases=("garage", "closet", "attic", "basement", "tank water heater", "tankless"),
            ),
        ),
    ),
    ProblemType(
        id="toilet_issue",
        category=ServiceCategory.plumbing,
        label="toilet running or not flushing",
        match_keywords=("running toilet", "toilet running", "won't flush", "will not flush", "toilet"),
        questions=(
            CatalogQuestion(
                id="symptom",
                collects="toilet_symptom",
                question="Is the toilet running, not flushing, leaking at the base, or overflowing?",
                priority=PRIORITY_DISPATCH,
                aliases=("running", "won't flush", "overflow", "leaking at the base", "clogged"),
            ),
            CatalogQuestion(
                id="which_bath",
                collects="location",
                question="Which bathroom, and do other toilets in the home still work?",
                priority=PRIORITY_DISPATCH,
                aliases=("downstairs", "upstairs", "guest", "master", "only toilet", "other toilets"),
            ),
        ),
    ),
    ProblemType(
        id="garbage_disposal",
        category=ServiceCategory.plumbing,
        label="garbage disposal",
        match_keywords=("garbage disposal", "disposal"),
        questions=(
            CatalogQuestion(
                id="disposal_symptom",
                collects="symptom",
                question="Is the disposal jammed, humming, leaking, or dead?",
                priority=PRIORITY_DISPATCH,
                aliases=("jammed", "humming", "leaking", "won't turn on", "dead"),
            ),
            CatalogQuestion(
                id="reset",
                collects="reset_tried",
                question="Have you tried the reset button on the bottom of the unit?",
                priority=PRIORITY_OPTIONAL,
                aliases=("reset", "reset button"),
            ),
        ),
    ),
    ProblemType(
        id="sewer_or_sump",
        category=ServiceCategory.plumbing,
        label="sewer backup or sump pump",
        match_keywords=("sewer", "sewage", "sump", "main line", "floor drain"),
        questions=(
            CatalogQuestion(
                id="how_many_fixtures",
                collects="scope",
                question="Is more than one drain backing up, or only one fixture?",
                priority=PRIORITY_DISPATCH,
                aliases=("multiple", "only one", "whole house", "floor drain", "basement drain"),
            ),
            CatalogQuestion(
                id="sewage_present",
                collects="sewage",
                question="Is sewage or standing water on the floor right now?",
                priority=PRIORITY_SAFETY,
                aliases=("sewage", "standing water", "on the floor", "sump"),
            ),
        ),
    ),
    ProblemType(
        id="hvac_not_conditioning",
        category=ServiceCategory.hvac,
        label="heating or cooling not working",
        match_keywords=(
            "not cooling", "not heating", "no heat", "no air", "ac", "a/c",
            "air condition", "furnace", "hvac", "thermostat", "outdoor unit",
            "blows warm", "ice on",
        ),
        questions=(
            CatalogQuestion(
                id="heat_or_cool",
                collects="heat_or_cool",
                question="Is this a heating problem, a cooling problem, or both?",
                priority=PRIORITY_DISPATCH,
                aliases=("cooling", "heating", "ac", "air condition", "furnace", "heat"),
            ),
            CatalogQuestion(
                id="unit_runs",
                collects="unit_runs",
                question="Does the system run at all, or is it completely off?",
                priority=PRIORITY_DISPATCH,
                aliases=("runs but", "blows warm", "won't turn on", "not running", "completely dead", "outdoor unit"),
            ),
            CatalogQuestion(
                id="whole_home",
                collects="scope",
                question="Is the whole home affected, or only some rooms?",
                priority=PRIORITY_DISPATCH,
                aliases=("upstairs", "whole house", "one room", "90 degree", "entire home"),
            ),
        ),
    ),
    ProblemType(
        id="sparking_outlet",
        category=ServiceCategory.electrical,
        label="sparking outlet or burning electrical smell",
        match_keywords=("spark", "sparking", "outlet", "burning smell"),
        questions=(
            CatalogQuestion(
                id="smoke_now",
                collects="smoke_or_burning",
                question="Is there smoke, flame, or a burning smell right now?",
                priority=PRIORITY_SAFETY,
                aliases=("no smoke", "no burning", "burning smell", "smoke", "flame"),
            ),
            CatalogQuestion(
                id="which_circuit",
                collects="location",
                question="Which room and which outlet or switch is involved?",
                priority=PRIORITY_DISPATCH,
                aliases=("kitchen", "bathroom", "bedroom", "outlet", "switch", "toaster"),
            ),
        ),
    ),
    ProblemType(
        id="power_issue",
        category=ServiceCategory.electrical,
        label="power outage, breaker, or flickering lights",
        match_keywords=(
            "no power", "breaker", "flicker", "buzzing", "lights out", "power out",
            "gfci", "no lights", "ceiling fan", "wiring", "panel",
        ),
        questions=(
            CatalogQuestion(
                id="scope",
                collects="power_scope",
                question="Is the whole home out, or only some lights or rooms?",
                priority=PRIORITY_DISPATCH,
                aliases=("whole home", "entire home", "one room", "few lights", "all lights"),
            ),
            CatalogQuestion(
                id="breaker_state",
                collects="breaker",
                question="Did a breaker trip, and have you already reset it?",
                priority=PRIORITY_DISPATCH,
                aliases=("breaker", "tripped", "reset", "panel"),
            ),
        ),
    ),
    ProblemType(
        id="roof_leak",
        category=ServiceCategory.roofing,
        label="roof leak or interior ceiling stain",
        match_keywords=(
            "roof", "shingle", "ceiling stain", "ceiling leak", "wet stain",
            "gutter", "missing shingle", "hail",
        ),
        questions=(
            CatalogQuestion(
                id="interior_spot",
                collects="location",
                question="Where in the home do you see the stain or drip?",
                priority=PRIORITY_DISPATCH,
                aliases=("guest", "bedroom", "living", "kitchen", "ceiling"),
            ),
            CatalogQuestion(
                id="after_storm",
                collects="storm",
                question="Did this start after a recent storm, and is it dripping now?",
                priority=PRIORITY_DISPATCH,
                aliases=("storm", "not dripping", "still dripping", "after the rain"),
            ),
        ),
    ),
    ProblemType(
        id="water_intrusion",
        category=ServiceCategory.water_damage,
        label="water entering the home",
        match_keywords=(
            "flood", "flooding", "standing water", "water coming in",
            "water started coming", "burst pipe", "mold", "wet basement",
            "water in the basement", "water near",
        ),
        questions=(
            CatalogQuestion(
                id="still_entering",
                collects="still_entering",
                question="Is water still coming in?",
                priority=PRIORITY_SAFETY,
                aliases=("still coming", "seeping", "stopped coming", "not coming in"),
            ),
            CatalogQuestion(
                id="near_electrical",
                collects="near_electrical",
                question="Is the water near any outlets, the breaker panel, or appliances?",
                priority=PRIORITY_SAFETY,
                aliases=("near electrical", "near any outlet", "not near", "outlets", "breaker"),
            ),
            CatalogQuestion(
                id="which_rooms",
                collects="location",
                question="Which rooms or areas are wet?",
                priority=PRIORITY_DISPATCH,
                aliases=("basement", "living room", "bedroom", "kitchen", "foundation"),
            ),
        ),
    ),
    ProblemType(
        id="indoor_pest",
        category=ServiceCategory.pest_control,
        label="indoor pest problem",
        match_keywords=(
            "pest", "ant", "ants", "roach", "cockroach", "mouse", "mice", "rat",
            "rodent", "termite", "droppings", "wasp", "bed bug", "bed bugs",
            "infestation", "bee",
        ),
        questions=(
            CatalogQuestion(
                id="pest_kind",
                collects="pest_type",
                question="What kind of pest have you seen?",
                priority=PRIORITY_DISPATCH,
                aliases=(
                    "mice", "mouse", "ants", "ant", "roach", "cockroach", "termite",
                    "droppings", "wasp", "bed bug", "bed bugs", "rat", "bee",
                ),
            ),
            CatalogQuestion(
                id="where_seen",
                collects="location",
                question="Where have you seen them, and is it inside the home?",
                priority=PRIORITY_DISPATCH,
                aliases=("kitchen", "pantry", "garage", "indoor", "inside", "counters"),
            ),
        ),
    ),
    ProblemType(
        id="broken_appliance",
        category=ServiceCategory.appliance_repair,
        label="broken appliance",
        match_keywords=(
            "dishwasher", "washer", "dryer", "fridge", "refrigerator", "oven",
            "stove", "microwave", "ice maker", "range",
        ),
        questions=(
            CatalogQuestion(
                id="which_appliance",
                collects="appliance",
                question="Which appliance is broken?",
                priority=PRIORITY_DISPATCH,
                aliases=(
                    "dishwasher", "washer", "dryer", "fridge", "oven", "stove",
                    "microwave", "ice maker", "range",
                ),
            ),
            CatalogQuestion(
                id="symptom",
                collects="symptom",
                question="What happens when you try to use it?",
                priority=PRIORITY_DISPATCH,
                aliases=("won't start", "leaking", "error", "not draining", "not heating"),
            ),
        ),
    ),
    ProblemType(
        id="general_home_repair",
        category=ServiceCategory.handyman,
        label="door, drywall, garage door, or similar repair",
        match_keywords=(
            "garage door", "drywall", "hole in the wall", "fence", "deck",
            "stuck door", "sliding door", "window cracked", "window won't",
            "locked out", "deadbolt",
        ),
        questions=(
            CatalogQuestion(
                id="what_broke",
                collects="what_broke",
                question="What exactly is broken or not working?",
                priority=PRIORITY_DISPATCH,
                aliases=("garage door", "drywall", "fence", "deck", "door", "window", "deadbolt"),
            ),
            CatalogQuestion(
                id="where",
                collects="location",
                question="Which part of the home is it on?",
                priority=PRIORITY_DISPATCH,
                aliases=("garage", "front", "back", "bedroom", "bathroom", "living"),
            ),
        ),
    ),
)


def _token_hit(text: str, keyword: str) -> bool:
    needle = (keyword or "").strip().lower()
    if not needle:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _normalize(text: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).split())


def already_asked(question: str, asked: list[str] | None) -> bool:
    current = _normalize(question)
    if not current:
        return True
    for previous in asked or []:
        prev = _normalize(previous)
        if not prev:
            continue
        if len(current & prev) / max(len(current), 1) >= 0.6:
            return True
    return False


def _slot_answered(item: CatalogQuestion, facts: dict[str, str], blob: str) -> bool:
    value = (facts or {}).get(item.collects)
    if value and str(value).strip():
        return True
    for alias in (item.collects,) + item.aliases:
        if alias in (facts or {}) and str(facts[alias]).strip():
            return True
        if _token_hit(blob, alias):
            return True
    return False


def match_problem(category: ServiceCategory, text: str) -> ProblemType | None:
    """Return a problem type when keywords clearly fit. Never force a match."""
    blob = (text or "").lower()
    pool = PROBLEMS
    if category not in {ServiceCategory.unknown, ServiceCategory.handyman}:
        pool = tuple(p for p in PROBLEMS if p.category == category)

    scored: list[tuple[int, int, ProblemType]] = []
    for problem in pool:
        hits = [kw for kw in problem.match_keywords if _token_hit(blob, kw)]
        if not hits:
            continue
        specificity = sum(len(kw) for kw in hits)
        scored.append((len(hits), specificity, problem))
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], -row[1], row[2].id))
    best_hits = scored[0][0]
    top = [row[2] for row in scored if row[0] == best_hits]
    if category in {ServiceCategory.unknown, ServiceCategory.handyman}:
        cats = {p.category for p in top}
        if len(cats) > 1:
            return None
    return scored[0][2]


def unanswered_questions(
    problem: ProblemType | None,
    facts: dict[str, str] | None = None,
    asked: list[str] | None = None,
    blob: str = "",
) -> list[CatalogQuestion]:
    if problem is None:
        return []
    remaining: list[CatalogQuestion] = []
    for item in problem.questions:
        if _slot_answered(item, facts or {}, blob):
            continue
        if already_asked(item.question, asked):
            continue
        remaining.append(item)
    remaining.sort(key=lambda item: (item.priority, item.id))
    return remaining


def format_guidance(problem: ProblemType, remaining: list[CatalogQuestion]) -> str:
    header = (
        "Optional intake hints for this turn. Not a script. Ask at most ONE question. "
        "Skip anything already answered. If the job is unusual or spans trades, ignore these hints."
    )
    if not remaining:
        return (
            f"{header}\nMatched type: {problem.category.value} / {problem.label}. "
            "No unanswered catalog slots. Set next_question to null unless a safety or "
            "dispatch fact is still missing from the chat."
        )
    lines = [
        header,
        f"Matched type: {problem.category.value} / {problem.label}",
        "Unanswered slots (highest priority first):",
    ]
    for item in remaining[:MAX_HINTS]:
        band = _BAND.get(item.priority, "dispatch")
        lines.append(f"- [{band}] {item.collects}: {item.question}")
    return "\n".join(lines)


def turn_guidance(
    category: ServiceCategory,
    text: str,
    facts: dict[str, str] | None = None,
    asked: list[str] | None = None,
) -> str | None:
    """Hints to inject for this turn, or None when the catalog does not apply."""
    problem = match_problem(category, text)
    if problem is None:
        return None
    remaining = unanswered_questions(problem, facts=facts, asked=asked, blob=text)
    return format_guidance(problem, remaining)


def conversation_blob(messages, extra: str = "", facts: dict[str, str] | None = None, summary: str = "") -> str:
    parts: list[str] = []
    for message in messages or []:
        if getattr(message, "role", None) == "user":
            parts.append(message.content)
    if extra:
        parts.append(extra)
    if summary:
        parts.append(summary)
    if facts:
        parts.extend(str(value) for value in facts.values() if value)
    return " ".join(parts)
