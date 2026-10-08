"""Rule-based hazard detection. This runs before the LLM and is not probabilistic."""

from __future__ import annotations

from app.models import ESCALATE_HAZARDS, CAUTION_HAZARDS, Hazard

# Phrase lists are intentionally conservative: short generic words like "gas" or
# "smoke" alone are too noisy (gas stove, fireplace smoke, etc.).
HAZARD_PHRASES: dict[Hazard, tuple[str, ...]] = {
    Hazard.gas_leak: (
        "gas leak",
        "smell gas",
        "smells like gas",
        "gas smell",
        "smell of gas",
        "smelling gas",
        "rotten egg",
        "rotten eggs",
        "natural gas odor",
        "smell of natural gas",
    ),
    Hazard.fire_smoke: (
        "on fire",
        "house fire",
        "active fire",
        "flames in",
        "smoke filling",
        "smoke in the house",
        "smoke coming from",
        "something is burning",
        "house is on fire",
    ),
    Hazard.electrical: (
        "sparking",
        "sparks coming",
        "outlet sparking",
        "sparking outlet",
        "wires sparking",
        "burning smell from the outlet",
        "outlet smells like burning",
        "electrical burning smell",
    ),
    Hazard.flood_electrical: (
        "water near electrical",
        "water around the outlet",
        "water by the outlet",
        "flooding near the panel",
        "water by the breaker",
        "water near the breaker",
        "standing water near electrical",
        "water around electrical",
    ),
    Hazard.carbon_monoxide: (
        "carbon monoxide",
        "co detector",
        "co alarm",
        "co2 alarm",
        "carbon monoxide alarm",
        "co detector going off",
    ),
}

SAFETY_ADVICE: dict[Hazard, str] = {
    Hazard.gas_leak: (
        "If you smell gas, leave the home immediately. Do not use lights, appliances, "
        "or phones inside. From a safe place, call 911 and your gas utility. "
        "I will not look up contractors until you confirm everyone is safe."
    ),
    Hazard.fire_smoke: (
        "If there is active fire or smoke, leave the home and call 911. "
        "Do not try to diagnose or repair this yourself. "
        "I will not look up contractors until you confirm everyone is safe."
    ),
    Hazard.carbon_monoxide: (
        "A carbon monoxide alarm is an emergency. Get everyone outside into fresh air "
        "and call 911. Do not re-enter until emergency services say it is safe. "
        "I will not look up contractors until you confirm everyone is safe."
    ),
    Hazard.electrical: (
        "Sparking, smoke, or a burning smell from electrical equipment can be dangerous. "
        "If you can do so safely, shut off power at the breaker and stay away from the outlet. "
        "Call 911 if you see fire or smoke. I can still help you find an electrician."
    ),
    Hazard.flood_electrical: (
        "Water near electrical equipment is hazardous. Do not touch water that may be energized. "
        "If you can reach the breaker without stepping in water, shut off power. "
        "Call 911 if anyone may have been shocked. I can still help you find help."
    ),
}

SAFE_PHRASES = (
    "i'm safe",
    "im safe",
    "i am safe",
    "we're safe",
    "we are safe",
    "everyone is safe",
    "false alarm",
    "no longer smell",
    "don't smell it anymore",
    "do not smell it anymore",
    "it was nothing",
)


def detect_hazards(text: str) -> list[Hazard]:
    lowered = (text or "").lower()
    found: list[Hazard] = []
    for hazard, phrases in HAZARD_PHRASES.items():
        if any(phrase in lowered for phrase in phrases):
            found.append(hazard)
    return found


def is_escalation(hazards: list[Hazard]) -> bool:
    return any(hazard in ESCALATE_HAZARDS for hazard in hazards)


def has_caution(hazards: list[Hazard]) -> bool:
    return any(hazard in CAUTION_HAZARDS for hazard in hazards)


def advice_for(hazards: list[Hazard]) -> str | None:
    if not hazards:
        return None
    # Escalation advice first, then caution, in a stable order.
    ordered = (
        Hazard.fire_smoke,
        Hazard.gas_leak,
        Hazard.carbon_monoxide,
        Hazard.flood_electrical,
        Hazard.electrical,
    )
    parts = [SAFETY_ADVICE[h] for h in ordered if h in hazards]
    return " ".join(parts) if parts else None


def user_says_safe(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in SAFE_PHRASES)
