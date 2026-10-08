"""Hazard detection. Phrase match first, then MiniLM recall, then negation."""

from __future__ import annotations

import re

from app.models import ESCALATE_HAZARDS, CAUTION_HAZARDS, Hazard

# Negation in the 48 characters before a phrase. Used so "not everyone is safe"
# does not count as safe, and "I no longer smell gas" does not re-trigger gas.
_NEGATION_BEFORE = re.compile(
    r"(?i)\b("
    r"not|no|never|don't|dont|do not|doesn't|doesnt|didn't|didnt|"
    r"isn't|isnt|wasn't|wasnt|without|no longer|can't|cannot"
    r")\b"
)

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


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 1:
        return 2
    prev = list(range(len(right) + 1))
    for i, ch in enumerate(left, start=1):
        curr = [i]
        for j, other in enumerate(right, start=1):
            ins = curr[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ch != other)
            curr.append(min(ins, delete, sub))
        prev = curr
    return prev[-1]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _token_close(needle: str, hay: str) -> bool:
    if needle == hay:
        return True
    if min(len(needle), len(hay)) < 3:
        return False
    return _levenshtein(needle, hay) <= 1


def _affirmed_at(text: str, idx: int) -> bool:
    prefix = (text or "").lower()[max(0, idx - 48) : idx]
    return not _NEGATION_BEFORE.search(prefix)


def _phrase_is_affirmed(text: str, phrase: str) -> bool:
    """True if `phrase` appears without a negation immediately before it.

    Exact substring first, then ordered tokens with edit distance 1 so
    'smell gass' still matches 'smell gas'. 'gas stove' does not match
    'gas leak' because leak is missing.
    """
    lowered = (text or "").lower()
    needle = (phrase or "").lower().strip()
    if not needle:
        return False
    start = 0
    while True:
        idx = lowered.find(needle, start)
        if idx < 0:
            break
        if _affirmed_at(lowered, idx):
            return True
        start = idx + 1
    needles = _tokens(needle)
    words = _tokens(lowered)
    if not needles or len(words) < len(needles):
        return False
    cursor = 0
    for i in range(len(words) - len(needles) + 1):
        if all(_token_close(needles[j], words[i + j]) for j in range(len(needles))):
            idx = lowered.find(words[i], cursor)
            if idx < 0:
                idx = lowered.find(words[i])
            if idx >= 0 and _affirmed_at(lowered, idx):
                return True
            cursor = max(cursor, idx + 1)
    return False


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [part.strip() for part in parts if part.strip()]


def _embedding_affirms_hazard(text: str, phrases: tuple[str, ...]) -> bool:
    """Paraphrase/typo recall. Skip sentences that already contain a negation."""
    try:
        from app.safety_embed import MIN_COSINE, best_phrase_score, encoder
    except Exception:
        return False
    if encoder() is None:
        return False
    for sentence in _sentences(text):
        if _NEGATION_BEFORE.search(sentence):
            continue
        if best_phrase_score(sentence, phrases) >= MIN_COSINE:
            return True
    return False


def detect_hazards(text: str) -> list[Hazard]:
    found: list[Hazard] = []
    for hazard, phrases in HAZARD_PHRASES.items():
        if any(_phrase_is_affirmed(text, phrase) for phrase in phrases):
            found.append(hazard)
            continue
        if _embedding_affirms_hazard(text, phrases):
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
    return any(_phrase_is_affirmed(text, phrase) for phrase in SAFE_PHRASES)
