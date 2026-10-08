from app.models import Hazard
from app.safety import detect_hazards, is_escalation, has_caution, user_says_safe


def test_gas_smell_escalates():
    hazards = detect_hazards("I smell gas in the kitchen near the stove.")
    assert Hazard.gas_leak in hazards
    assert is_escalation(hazards)


def test_fire_escalates():
    hazards = detect_hazards("There is smoke coming from the heater closet.")
    assert Hazard.fire_smoke in hazards
    assert is_escalation(hazards)


def test_carbon_monoxide_escalates():
    hazards = detect_hazards("Our carbon monoxide alarm is going off.")
    assert Hazard.carbon_monoxide in hazards
    assert is_escalation(hazards)


def test_sparking_outlet_is_caution_not_escalation():
    hazards = detect_hazards("The kitchen outlet is sparking when I plug anything in.")
    assert Hazard.electrical in hazards
    assert has_caution(hazards)
    assert not is_escalation(hazards)


def test_basement_flood_is_not_an_emergency_hazard():
    hazards = detect_hazards(
        "Water started coming into my basement last night after the storm."
    )
    assert hazards == []
    assert not is_escalation(hazards)


def test_floodwater_near_electrical_is_caution():
    hazards = detect_hazards("There is water near electrical outlets in the basement.")
    assert Hazard.flood_electrical in hazards
    assert has_caution(hazards)
    assert not is_escalation(hazards)


def test_user_says_safe():
    assert user_says_safe("I'm safe, it was a false alarm.")
    assert not user_says_safe("The basement is still flooding.")
