"""Optional follow-up hints for a trade the LLM already chose.

Python does not keyword-match or embed the homeowner's words against this
file. After DeepSeek (or the keyword fallback) returns a service category,
we inject example jobs and their questions for that trade. The model still
writes the question and decides what is already answered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import ServiceCategory

PRIORITY_SAFETY = 0
PRIORITY_DISPATCH = 1
PRIORITY_OPTIONAL = 2


@dataclass(frozen=True)
class CatalogQuestion:
    id: str
    collects: str
    question: str
    priority: int


@dataclass(frozen=True)
class ProblemType:
    id: str
    category: ServiceCategory
    label: str
    description: str
    examples: tuple[str, ...]
    match_keywords: tuple[str, ...]
    questions: tuple[CatalogQuestion, ...]


def _q(
    qid: str,
    collects: str,
    question: str,
    priority: int,
) -> CatalogQuestion:
    return CatalogQuestion(
        id=qid,
        collects=collects,
        question=question,
        priority=priority,
    )


# High-frequency jobs used as examples after a trade is known.
# Unusual work (solar, pool, septic, EV charger, smart lock) has no row;
# the LLM should ignore this list for those.
PROBLEMS: tuple[ProblemType, ...] = (
    ProblemType(
        id="leaking_fixture",
        category=ServiceCategory.plumbing,
        label="leaking pipe or fixture",
        description=(
            "Water is dripping or spraying from a faucet, sink, shower valve, "
            "or visible pipe. A plumber needs the fixture, whether it is still "
            "running, and whether a shutoff is reachable."
        ),
        examples=(
            "kitchen sink leaking under the cabinet",
            "the faucet keeps dripping",
            "a pipe is leaking in the house",
            "shower valve is spraying water",
        ),
        match_keywords=("leak", "leaking", "dripping", "pipe", "faucet", "sink"),
        questions=(
            _q("still_active", "still_running", "Is water still leaking right now?", PRIORITY_SAFETY),
            _q("where", "location", "Which fixture is leaking, and which room is it in?", PRIORITY_DISPATCH),
            _q("shutoff", "shutoff_access", "Can a technician reach the shutoff valve?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="clogged_drain",
        category=ServiceCategory.plumbing,
        label="clogged drain",
        description=(
            "A sink, shower, tub, or floor drain is slow or blocked. Backup in "
            "one fixture is usually a local clog; several fixtures at once may "
            "be a main line."
        ),
        examples=(
            "the shower drain is backing up",
            "kitchen sink will not drain",
            "the tub fills with dirty water",
            "slow drain in the bathroom sink",
        ),
        match_keywords=("clog", "clogged", "drain", "slow drain", "won't drain", "will not drain"),
        questions=(
            _q("overflowing", "overflowing", "Is it overflowing, or did you stop it in time?", PRIORITY_SAFETY),
            _q("which_drain", "location", "Which drain, and is more than one fixture backing up?", PRIORITY_DISPATCH),
            _q("tried", "attempted_clear", "Have you already used a snake, chemical cleaner, or plunger?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="toilet_issue",
        category=ServiceCategory.plumbing,
        label="toilet running or not flushing",
        description=(
            "A toilet will not flush, keeps running, leaks at the base, or "
            "overflows. Dispatch needs the symptom and which bathroom."
        ),
        examples=(
            "the downstairs toilet will not flush",
            "the commode is overflowing onto the floor",
            "toilet keeps running all night",
            "water leaking around the toilet base",
        ),
        match_keywords=("running toilet", "toilet running", "won't flush", "will not flush", "toilet", "commode"),
        questions=(
            _q("symptom", "toilet_symptom",
               "Is the toilet running, not flushing, leaking at the base, or overflowing?", PRIORITY_DISPATCH),
            _q("which_bath", "location", "Which bathroom, and do other toilets in the home still work?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="water_heater",
        category=ServiceCategory.plumbing,
        label="water heater or no hot water",
        description=(
            "No hot water, not enough hot water, or a leaking/noisy water "
            "heater. Contractors need whether every faucet is cold and where "
            "the tank or tankless unit sits."
        ),
        examples=(
            "no hot water anywhere in the house",
            "every faucet is ice cold",
            "the water heater is leaking in the garage",
            "we run out of hot water after one shower",
        ),
        match_keywords=("water heater", "no hot water", "hot water", "tankless"),
        questions=(
            _q("any_hot", "any_hot_water", "Is there any hot water at all, or is every faucet cold?", PRIORITY_DISPATCH),
            _q("heater_place", "location", "Where is the water heater (garage, closet, attic)?", PRIORITY_DISPATCH),
            _q("fuel", "fuel_type", "Is it gas or electric, if you know?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="garbage_disposal",
        category=ServiceCategory.plumbing,
        label="garbage disposal",
        description=(
            "A kitchen garbage disposal is jammed, humming, leaking, or dead. "
            "A plumber needs the symptom and whether a reset was already tried."
        ),
        examples=(
            "the garbage disposal is humming and jammed",
            "disposal will not turn on",
            "disposal is leaking under the sink",
            "something is stuck in the disposal",
        ),
        match_keywords=("garbage disposal", "disposal"),
        questions=(
            _q("disposal_symptom", "symptom", "Is the disposal jammed, humming, leaking, or dead?", PRIORITY_DISPATCH),
            _q("reset", "reset_tried", "Have you tried the reset button on the bottom of the unit?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="sewer_or_sump",
        category=ServiceCategory.plumbing,
        label="sewer backup or sump pump",
        description=(
            "Sewage or dirty water backing up through a drain, toilet, or "
            "floor, or a failed sump. Multiple fixtures backing up is a main-line "
            "signal; standing sewage on the floor is urgent."
        ),
        examples=(
            "sewage is backing up through the floor drain",
            "water comes up in the shower when the washer runs",
            "the sump well is overflowing",
            "toilets gurgle and sewage smell in the basement",
        ),
        match_keywords=("sewer", "sewage", "sump", "main line", "floor drain"),
        questions=(
            _q("sewage_present", "sewage", "Is sewage or standing water on the floor right now?", PRIORITY_SAFETY),
            _q("how_many_fixtures", "scope", "Is more than one drain backing up, or only one fixture?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="low_water_pressure",
        category=ServiceCategory.plumbing,
        label="low water pressure",
        description=(
            "Weak flow at one fixture or throughout the home. Whole-house "
            "pressure drops may be a main supply or PRV issue; one fixture is "
            "often a clogged aerator or cartridge."
        ),
        examples=(
            "barely any water pressure in the shower",
            "all the faucets suddenly have weak flow",
            "only the kitchen sink has low pressure",
            "water trickles out of the upstairs taps",
        ),
        match_keywords=("low pressure", "no pressure", "weak flow", "trickle", "water pressure"),
        questions=(
            _q("pressure_scope", "scope", "Is pressure low at one fixture or the whole home?", PRIORITY_DISPATCH),
            _q("hot_cold", "hot_or_cold", "Is it both hot and cold, or only one?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="shower_or_tub",
        category=ServiceCategory.plumbing,
        label="shower or tub valve",
        description=(
            "Shower or tub will not switch from tub to shower, has no hot "
            "water only in that stall, or the cartridge/diverter is failing."
        ),
        examples=(
            "the shower only runs through the tub spout",
            "no hot water in the shower but the sink is fine",
            "the diverter knob does nothing",
            "tub faucet will not shut off",
        ),
        match_keywords=("diverter", "shower valve", "tub spout", "shower cartridge", "tub faucet"),
        questions=(
            _q("shower_symptom", "symptom", "Does it leak, stay cold, or fail to switch from tub to shower?", PRIORITY_DISPATCH),
            _q("which_bath", "location", "Which bathroom or stall is it?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="frozen_or_burst_pipe",
        category=ServiceCategory.plumbing,
        label="frozen or burst pipe",
        description=(
            "A pipe froze, split, or is spraying after a freeze. Dispatch needs "
            "whether water is still flowing and whether a main shutoff was used."
        ),
        examples=(
            "a pipe burst in the crawlspace after the freeze",
            "outdoor pipe split and is spraying",
            "no water upstairs after the hard freeze",
            "I think a pipe froze in the attic",
        ),
        match_keywords=("burst pipe", "frozen pipe", "pipe burst", "pipe froze", "split pipe"),
        questions=(
            _q("still_spraying", "still_running", "Is water still spraying, or did you shut the main off?", PRIORITY_SAFETY),
            _q("where_pipe", "location", "Where is the pipe (attic, crawlspace, exterior wall)?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="outdoor_or_slab_leak",
        category=ServiceCategory.plumbing,
        label="yard, hose bib, or slab leak",
        description=(
            "Water pooling in the yard, a hose bib that will not shut, or a "
            "suspected leak under the slab (warm floor, unexplained high bill)."
        ),
        examples=(
            "the yard is soggy and I can hear water underground",
            "hose bib will not turn off",
            "warm spot on the floor and the water bill spiked",
            "water bubbling up near the foundation",
        ),
        match_keywords=("hose bib", "spigot", "slab leak", "yard leak", "soggy yard", "water bill"),
        questions=(
            _q("where_wet", "location", "Where do you see or hear the water (yard, foundation, indoor floor)?", PRIORITY_DISPATCH),
            _q("meter", "meter_moving", "Is the water meter still spinning with all fixtures off?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="no_cooling",
        category=ServiceCategory.hvac,
        label="air conditioning not cooling",
        description=(
            "The AC runs but blows warm air, or will not keep the home at "
            "setpoint. Techs need whether the outdoor unit runs and how much "
            "of the home is affected."
        ),
        examples=(
            "the AC blows warm air",
            "air conditioner is not cooling the house",
            "it is 90 degrees inside and the AC cannot keep up",
            "upstairs never gets cold",
        ),
        match_keywords=("not cooling", "blows warm", "no cool air", "ac", "a/c", "air condition"),
        questions=(
            _q("unit_runs", "unit_runs", "Does the outdoor unit run, or is the system completely off?", PRIORITY_DISPATCH),
            _q("whole_home", "scope", "Is the whole home warm, or only some rooms?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="no_heat",
        category=ServiceCategory.hvac,
        label="furnace or heat not working",
        description=(
            "No heat, furnace will not ignite, or heat pump blowing cold in "
            "winter. Dispatch needs whether the system tries to start and the "
            "scope of the home."
        ),
        examples=(
            "the furnace will not come on",
            "no heat at all this morning",
            "heater blows cold air",
            "pilot will not stay lit",
        ),
        match_keywords=("no heat", "not heating", "furnace", "heater blows", "pilot", "heat pump"),
        questions=(
            _q("tries_to_start", "unit_runs", "Does the furnace try to start, or is it completely silent?", PRIORITY_DISPATCH),
            _q("whole_home", "scope", "Is the whole home cold, or only some rooms?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="frozen_outdoor_unit",
        category=ServiceCategory.hvac,
        label="iced-over AC or heat pump",
        description=(
            "Ice on the outdoor condenser or indoor coil. Often airflow or "
            "refrigerant related; techs need whether it is still running."
        ),
        examples=(
            "ice all over the condenser outside",
            "the outdoor unit is a block of ice",
            "frozen coils on the AC",
            "ice on the refrigerant lines",
        ),
        match_keywords=("ice on", "frozen coil", "iced over", "condenser", "frozen ac"),
        questions=(
            _q("still_running", "unit_runs", "Is the system still running with ice on it?", PRIORITY_DISPATCH),
            _q("indoor_air", "airflow", "Is air coming from the vents, or did they freeze up too?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="noisy_hvac",
        category=ServiceCategory.hvac,
        label="noisy HVAC equipment",
        description=(
            "Banging, grinding, squealing, or rattling from the furnace, air "
            "handler, or outdoor unit. Location of the noise matters for dispatch."
        ),
        examples=(
            "the furnace is banging on startup",
            "squealing from the air handler",
            "the outdoor unit is rattling loudly",
            "grinding from the blower",
        ),
        match_keywords=("hvac noise", "furnace banging", "squealing", "blower", "air handler"),
        questions=(
            _q("where_noise", "location", "Is the noise from the indoor unit, the outdoor unit, or the vents?", PRIORITY_DISPATCH),
            _q("still_conditions", "unit_runs", "Is it still heating or cooling, or did it stop after the noise?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="thermostat_issue",
        category=ServiceCategory.hvac,
        label="thermostat not controlling the system",
        description=(
            "Blank thermostat, wrong mode, or system ignoring the setpoint. "
            "Often batteries or a bad control, but may be a system fault."
        ),
        examples=(
            "the thermostat screen is blank",
            "thermostat will not turn the AC on",
            "it ignores the temperature I set",
            "thermostat keeps clicking but nothing happens",
        ),
        match_keywords=("thermostat", "blank thermostat", "thermostat batteries"),
        questions=(
            _q("blank", "display", "Is the thermostat screen on, blank, or showing an error?", PRIORITY_DISPATCH),
            _q("mode", "mode", "Is it set to heat, cool, or off, and did that used to work?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="sparking_outlet",
        category=ServiceCategory.electrical,
        label="sparking outlet or burning electrical smell",
        description=(
            "Outlet, switch, or device sparking or smelling like burning "
            "plastic. Safety first: smoke or flame changes the path; otherwise "
            "an electrician needs the room and device."
        ),
        examples=(
            "the outlet sparked when I plugged the toaster in",
            "burning smell from the switch",
            "outlet is popping and scorching the plate",
            "I saw a flash from the receptacle",
        ),
        match_keywords=("spark", "sparking", "outlet", "burning smell", "scorch"),
        questions=(
            _q("smoke_now", "smoke_or_burning", "Is there smoke, flame, or a burning smell right now?", PRIORITY_SAFETY),
            _q("which_circuit", "location", "Which room and which outlet or switch is involved?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="power_issue",
        category=ServiceCategory.electrical,
        label="power outage, breaker, or flickering lights",
        description=(
            "Partial or whole-home outage, tripping breaker, or lights that "
            "flicker or dim. Scope and whether a breaker already tripped are "
            "the dispatch facts."
        ),
        examples=(
            "half the house has no power",
            "the breaker keeps tripping",
            "lights flicker when the AC kicks on",
            "the hall switch buzzes and the lights flicker",
            "whole home went dark but neighbors have power",
        ),
        match_keywords=("no power", "breaker", "flicker", "buzzing", "lights out", "power out", "no lights", "panel"),
        questions=(
            _q("scope", "power_scope", "Is the whole home out, or only some lights or rooms?", PRIORITY_DISPATCH),
            _q("breaker_state", "breaker", "Did a breaker trip, and have you already reset it?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="gfci_or_dead_outlet",
        category=ServiceCategory.electrical,
        label="dead outlet or GFCI",
        description=(
            "One outlet is dead, often in a kitchen, bath, or garage on a GFCI. "
            "An electrician needs which outlet and whether a reset button was tried."
        ),
        examples=(
            "bathroom outlet is dead",
            "GFCI will not reset",
            "kitchen counter outlets have no power",
            "garage receptacle does nothing",
        ),
        match_keywords=("gfci", "gfi", "dead outlet", "outlet is dead", "won't reset"),
        questions=(
            _q("which_outlet", "location", "Which room and which outlet is dead?", PRIORITY_DISPATCH),
            _q("reset_gfci", "reset_tried", "Have you pressed the GFCI reset, and did it stay in?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="light_fixture_or_fan",
        category=ServiceCategory.electrical,
        label="light fixture or ceiling fan",
        description=(
            "A light or ceiling fan is dead, noisy, wobbling, or flickering "
            "after a bulb change. Dispatch needs the fixture type and room."
        ),
        examples=(
            "the ceiling fan stopped and will not start",
            "dining light fixture is dead after changing bulbs",
            "fan wobbles and makes a scraping sound",
            "vanity lights flicker even with new bulbs",
        ),
        match_keywords=("ceiling fan", "light fixture", "vanity light", "chandelier", "fan wobble"),
        questions=(
            _q("fixture", "fixture_type", "Is it a ceiling fan, a light fixture, or both?", PRIORITY_DISPATCH),
            _q("where", "location", "Which room is it in?", PRIORITY_DISPATCH),
            _q("bulb", "bulb_tried", "Have you already tried a new bulb?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="detector_chirp",
        category=ServiceCategory.electrical,
        label="smoke or CO detector chirping",
        description=(
            "A detector chirps or beeps for low battery or end of life. A full "
            "alarm sounding for smoke or CO is a safety emergency, not this job type."
        ),
        examples=(
            "smoke detector chirps every few minutes",
            "CO detector is beeping a single chirp",
            "the hallway detector will not stop chirping",
            "need the detectors replaced, they are 10 years old",
        ),
        match_keywords=("detector chirp", "smoke detector", "co detector", "chirping", "beeping detector"),
        questions=(
            _q("chirp_vs_alarm", "alarm_type", "Is it a short chirp, or a full alarm sounding?", PRIORITY_SAFETY),
            _q("which_unit", "location", "Which detector and which floor?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="roof_leak",
        category=ServiceCategory.roofing,
        label="roof leak or interior ceiling stain",
        description=(
            "Water staining or dripping from a ceiling after rain, usually a "
            "roof or flashing leak. A roofer needs the interior location and "
            "whether it is still dripping."
        ),
        examples=(
            "brown stain on the upstairs ceiling after the rain",
            "ceiling is dripping in the guest bedroom",
            "wet stain appeared on the living room ceiling",
            "water coming through the ceiling when it storms",
        ),
        match_keywords=("roof", "ceiling stain", "ceiling leak", "wet stain", "stain on the ceiling"),
        questions=(
            _q("interior_spot", "location", "Where in the home do you see the stain or drip?", PRIORITY_DISPATCH),
            _q("after_storm", "storm", "Did this start after a recent storm, and is it dripping now?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="missing_shingles",
        category=ServiceCategory.roofing,
        label="missing or storm-damaged shingles",
        description=(
            "Shingles missing, creased, or blown off after wind or hail. "
            "Interior leaking is a separate urgent fact if present."
        ),
        examples=(
            "shingles blew off in the wind",
            "hail dented the roof last night",
            "I can see bare spots on the roof",
            "granules filling the downspouts after hail",
        ),
        match_keywords=("missing shingle", "shingles blew", "hail", "wind damage", "bare spots on the roof"),
        questions=(
            _q("interior", "interior_leak", "Is water coming inside, or is the damage only on the roof?", PRIORITY_DISPATCH),
            _q("when_storm", "storm", "When was the storm, and which slope looks worst?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="gutters",
        category=ServiceCategory.roofing,
        label="gutters or downspouts",
        description=(
            "Gutters pulling off, overflowing, or downspouts dumping at the "
            "foundation. Often bundled with roofing; overflow can also feed "
            "basement water."
        ),
        examples=(
            "a gutter is pulling off after hail",
            "gutters overflow every time it rains",
            "downspout is disconnected and dumping at the foundation",
            "gutter sagging away from the fascia",
        ),
        match_keywords=("gutter", "downspout", "fascia"),
        questions=(
            _q("gutter_symptom", "symptom", "Are they overflowing, pulling off, or dumping at the foundation?", PRIORITY_DISPATCH),
            _q("which_side", "location", "Which side of the house?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="flashing_or_skylight",
        category=ServiceCategory.roofing,
        label="flashing, chimney, or skylight leak",
        description=(
            "Leak concentrated around a chimney, skylight, or wall flashing "
            "rather than a random field of shingles."
        ),
        examples=(
            "skylight is leaking onto the floor",
            "water comes in around the chimney when it rains",
            "flashing around the vent pipe is rusted",
            "leak only around the roof-to-wall joint",
        ),
        match_keywords=("skylight", "chimney leak", "flashing", "pipe boot", "step flashing"),
        questions=(
            _q("feature", "roof_feature", "Is it a skylight, chimney, vent pipe, or wall flashing?", PRIORITY_DISPATCH),
            _q("interior", "location", "Where does the water show up inside?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="water_intrusion",
        category=ServiceCategory.water_damage,
        label="water entering the home",
        description=(
            "Water coming in through a window, foundation, or after a storm. "
            "Restoration techs need whether it is still entering and whether "
            "it is near electrical equipment."
        ),
        examples=(
            "water started coming into my basement last night after the storm",
            "the basement is wet after the rain",
            "water seeping in along the foundation",
            "storm water coming under the back door",
        ),
        match_keywords=(
            "flood", "flooding", "standing water", "water coming in",
            "water started coming", "wet basement", "water in the basement",
        ),
        questions=(
            _q("still_entering", "still_entering", "Is water still coming in?", PRIORITY_SAFETY),
            _q("near_electrical", "near_electrical",
               "Is the water near any outlets, the breaker panel, or appliances?", PRIORITY_SAFETY),
            _q("which_rooms", "location", "Which rooms or areas are wet?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="burst_pipe_damage",
        category=ServiceCategory.water_damage,
        label="water damage after a burst pipe",
        description=(
            "Finished space soaked after a supply line failed. Often needs "
            "extraction plus a plumber; the restoration question is how much "
            "area is wet and whether power is involved."
        ),
        examples=(
            "supply line burst and soaked the ceiling and carpet",
            "upstairs line failed and water ran into the living room",
            "the ceiling collapsed after a pipe burst",
            "floors are warped from the leak overnight",
        ),
        match_keywords=("soaked the", "warped", "extraction", "ceiling collapsed", "water damage"),
        questions=(
            _q("source_stopped", "still_entering", "Is the water source stopped?", PRIORITY_SAFETY),
            _q("how_much", "scope", "Which floors and materials are wet (carpet, drywall, ceiling)?", PRIORITY_DISPATCH),
            _q("near_electrical", "near_electrical", "Is wet material near outlets or lights?", PRIORITY_SAFETY),
        ),
    ),
    ProblemType(
        id="mold_or_damp",
        category=ServiceCategory.water_damage,
        label="mold or persistent dampness",
        description=(
            "Visible mold, musty smell, or a space that will not dry. Often "
            "follows a leak; techs need where it is and whether the source is "
            "still active."
        ),
        examples=(
            "black spots on the bathroom ceiling",
            "musty smell in the closet that will not go away",
            "mold behind the baseboard after the leak",
            "the guest room walls feel damp",
        ),
        match_keywords=("mold", "musty", "mildew", "black spots", "damp walls"),
        questions=(
            _q("still_wet", "still_entering", "Is there still an active leak, or is it leftover dampness?", PRIORITY_DISPATCH),
            _q("where_mold", "location", "Which room and what surface (wall, ceiling, HVAC closet)?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="ants_or_roaches",
        category=ServiceCategory.pest_control,
        label="ants or cockroaches",
        description=(
            "Indoor ants or roaches on counters, in the kitchen, or in baths. "
            "A tech needs the pest and where they are seen."
        ),
        examples=(
            "ants all over the kitchen counters",
            "cockroaches in the bathroom at night",
            "trail of ants from the window to the sink",
            "roaches coming from under the stove",
        ),
        match_keywords=("ant", "ants", "roach", "cockroach", "german roach"),
        questions=(
            _q("pest_kind", "pest_type", "Are they ants, roaches, or something else?", PRIORITY_DISPATCH),
            _q("where_seen", "location", "Where have you seen them, and is it inside the home?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="rodents",
        category=ServiceCategory.pest_control,
        label="mice or rats",
        description=(
            "Mice, rats, scratching in walls, or droppings in a pantry or "
            "attic. Dispatch needs interior vs attic/garage and any pets/kids."
        ),
        examples=(
            "little black pellets in the pantry",
            "mice in the kitchen at night",
            "scratching in the ceiling after dark",
            "rat in the garage",
        ),
        match_keywords=("mouse", "mice", "rat", "rodent", "droppings", "pellets"),
        questions=(
            _q("pest_kind", "pest_type", "Have you seen mice, rats, or only droppings?", PRIORITY_DISPATCH),
            _q("where_seen", "location", "Where — pantry, attic, garage, or living space?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="termites",
        category=ServiceCategory.pest_control,
        label="termites or wood-destroying insects",
        description=(
            "Suspected termites, mud tubes, swarmers, or hollow-sounding wood. "
            "This is an inspection-style lead; location of activity matters."
        ),
        examples=(
            "mud tubes on the foundation",
            "wings all over the windowsill, I think termites",
            "wood in the garage sounds hollow",
            "termite swarm in the living room",
        ),
        match_keywords=("termite", "mud tube", "swarmers", "wood destroying"),
        questions=(
            _q("what_seen", "evidence", "Did you see mud tubes, wings, or damaged wood?", PRIORITY_DISPATCH),
            _q("where_seen", "location", "Where on the house did you see it?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="stinging_insects",
        category=ServiceCategory.pest_control,
        label="wasps, hornets, or bees",
        description=(
            "A nest of wasps, hornets, or bees on the eaves, playground, or "
            "wall. Techs need nest location and whether anyone has been stung."
        ),
        examples=(
            "wasps under the eaves",
            "hornet nest by the back door",
            "bees coming from a hole in the brick",
            "yellowjackets in the playground wall",
        ),
        match_keywords=("wasp", "hornet", "yellowjacket", "bee nest", "bees"),
        questions=(
            _q("pest_kind", "pest_type", "Wasps, hornets, or honeybees, if you know?", PRIORITY_DISPATCH),
            _q("nest_where", "location", "Where is the nest (eaves, wall, ground, playground)?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="bed_bugs",
        category=ServiceCategory.pest_control,
        label="bed bugs",
        description=(
            "Bites after sleeping, bugs in a mattress seam, or a confirmed "
            "bed bug sighting. Heat or chemical treatment depends on which rooms."
        ),
        examples=(
            "we have bed bugs in the mattress",
            "bites in a line after waking up",
            "small bugs in the bed seams",
            "hotel trip and now I see bed bugs",
        ),
        match_keywords=("bed bug", "bed bugs", "mattress bugs"),
        questions=(
            _q("confirmed", "pest_type", "Have you actually seen bed bugs, or only the bites?", PRIORITY_DISPATCH),
            _q("which_rooms", "location", "Which bedrooms or other rooms are involved?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="dishwasher",
        category=ServiceCategory.appliance_repair,
        label="dishwasher",
        description=(
            "Dishwasher will not start, drain, clean, or it leaks. Model and "
            "error code help; leak vs dead machine changes the parts."
        ),
        examples=(
            "the dishwasher won't start and shows an error",
            "standing water in the bottom of the dishwasher",
            "dishwasher leaks onto the kitchen floor",
            "dishes come out still dirty",
        ),
        match_keywords=("dishwasher",),
        questions=(
            _q("symptom", "symptom", "Will it not start, not drain, leak, or fail to clean?", PRIORITY_DISPATCH),
            _q("error", "error_code", "Is there an error code on the display?", PRIORITY_OPTIONAL),
        ),
    ),
    ProblemType(
        id="washer_or_dryer",
        category=ServiceCategory.appliance_repair,
        label="washer or dryer",
        description=(
            "Clothes washer or dryer will not start, spin, drain, or heat. "
            "Need which machine and the symptom; leaking washers are a floor risk."
        ),
        examples=(
            "the washing machine will not spin",
            "dryer runs but the clothes stay wet",
            "washer leaked all over the laundry room",
            "dryer is making a loud thump",
        ),
        match_keywords=("washer", "washing machine", "dryer", "laundry machine"),
        questions=(
            _q("which_machine", "appliance", "Is it the washer, the dryer, or both?", PRIORITY_DISPATCH),
            _q("symptom", "symptom", "What happens when you run it?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="refrigerator",
        category=ServiceCategory.appliance_repair,
        label="refrigerator or freezer",
        description=(
            "Fridge or freezer not cooling, leaking, icing over, or a dead "
            "ice maker. Food loss is time-sensitive; techs need which compartment."
        ),
        examples=(
            "the refrigerator is warm and the food is thawing",
            "freezer is icing over",
            "fridge is leaking water onto the floor",
            "ice maker stopped making ice",
        ),
        match_keywords=("fridge", "refrigerator", "freezer", "ice maker"),
        questions=(
            _q("which_box", "appliance", "Is it the fridge, freezer, or ice maker?", PRIORITY_DISPATCH),
            _q("symptom", "symptom", "Is it warm, leaking, icing, or noisy?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="oven_or_range",
        category=ServiceCategory.appliance_repair,
        label="oven, range, or cooktop",
        description=(
            "Oven will not heat, a burner is dead, or a gas range has ignition "
            "problems. Do not treat a gas smell as this job — that is emergency hold."
        ),
        examples=(
            "the oven will not heat up",
            "one burner on the stove will not light",
            "range display is dead",
            "oven is 50 degrees off the setpoint",
        ),
        match_keywords=("oven", "stove", "range", "cooktop", "burner"),
        questions=(
            _q("which_part", "appliance", "Is it the oven, a cooktop burner, or the whole range?", PRIORITY_DISPATCH),
            _q("symptom", "symptom", "Will it not heat, not ignite, or is the display dead?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="garage_door",
        category=ServiceCategory.handyman,
        label="garage door or opener",
        description=(
            "Garage door off track, opener dead, or door stopped halfway. "
            "Need whether it is the door hardware or the opener, and if it is stuck open."
        ),
        examples=(
            "the garage door opener stopped halfway down",
            "garage door will not close",
            "opener motor runs but the door does not move",
            "garage door came off the track",
        ),
        match_keywords=("garage door", "garage opener", "off the track"),
        questions=(
            _q("what_broke", "what_broke", "Is it the door, the opener, or both?", PRIORITY_DISPATCH),
            _q("stuck_open", "door_state", "Is the door stuck open, closed, or halfway?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="drywall_or_hole",
        category=ServiceCategory.handyman,
        label="drywall hole or interior damage",
        description=(
            "A hole in drywall, cracked plaster, or a patch after a doorknob "
            "or leak. Size and room matter for a handyman vs a larger repair."
        ),
        examples=(
            "doorknob punched a hole in the drywall",
            "need a hole in the wall patched",
            "cracked plaster in the hallway",
            "kids put a hole in the bedroom wall",
        ),
        match_keywords=("drywall", "hole in the wall", "hole in the drywall", "plaster"),
        questions=(
            _q("what_broke", "what_broke", "How large is the hole or crack?", PRIORITY_DISPATCH),
            _q("where", "location", "Which room?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="door_or_window",
        category=ServiceCategory.handyman,
        label="door or window repair",
        description=(
            "A door will not latch, a sliding door is off track, or a window "
            "is cracked or will not open. Not a lockout if they still have keys."
        ),
        examples=(
            "the front door will not latch",
            "sliding door is off track",
            "window cracked and will not stay up",
            "interior door is rubbing the frame",
        ),
        match_keywords=("stuck door", "sliding door", "window cracked", "window won't", "will not latch", "door will not"),
        questions=(
            _q("what_broke", "what_broke", "Is it a door, a window, or sliding glass?", PRIORITY_DISPATCH),
            _q("where", "location", "Which door or window?", PRIORITY_DISPATCH),
        ),
    ),
    ProblemType(
        id="fence_deck_or_lockout",
        category=ServiceCategory.handyman,
        label="fence, deck, or lockout",
        description=(
            "Fence or deck board failure, or a mechanical lockout from lost "
            "keys or a stuck deadbolt."
        ),
        examples=(
            "fence blew down in the wind",
            "deck board is rotten and a nail popped",
            "locked out of the house, deadbolt will not turn",
            "gate will not latch",
        ),
        match_keywords=("fence", "deck", "locked out", "deadbolt", "gate"),
        questions=(
            _q("what_broke", "what_broke", "Is it a fence, deck, gate, or a lockout?", PRIORITY_DISPATCH),
            _q("where", "location", "Which side of the property or which door?", PRIORITY_DISPATCH),
        ),
    ),
)


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


def _slot_answered(item: CatalogQuestion, facts: dict[str, str] | None) -> bool:
    value = (facts or {}).get(item.collects)
    return bool(value and str(value).strip())


def problem_by_id(pid: str) -> ProblemType | None:
    for problem in PROBLEMS:
        if problem.id == pid:
            return problem
    return None


def problems_for_category(category: ServiceCategory) -> tuple[ProblemType, ...]:
    return tuple(problem for problem in PROBLEMS if problem.category == category)


def unanswered_questions(
    problem: ProblemType | None,
    facts: dict[str, str] | None = None,
    asked: list[str] | None = None,
) -> list[CatalogQuestion]:
    if problem is None:
        return []
    remaining: list[CatalogQuestion] = []
    for item in problem.questions:
        if _slot_answered(item, facts):
            continue
        if already_asked(item.question, asked):
            continue
        remaining.append(item)
    remaining.sort(key=lambda item: (item.priority, item.id))
    return remaining


def turn_guidance(
    category: ServiceCategory,
    text: str = "",
    facts: dict[str, str] | None = None,
    asked: list[str] | None = None,
) -> str | None:
    """Compact optional hints for this trade, or None before a category is known.

    `text` is ignored. We do not match the homeowner's wording against the catalog.
    This is not a checklist: do not inject every remaining catalog question.
    """
    del text
    if category in {ServiceCategory.unknown}:
        return None
    pool = problems_for_category(category)
    if not pool:
        return None
    labels = "; ".join(problem.label for problem in pool)
    asked_n = len(asked or [])
    return "\n".join(
        [
            "Optional intake hints for this turn. Not a checklist, not a script, "
            "and not a diagnosis.",
            f"The current trade guess is {category.value}.",
            f"Example jobs (not a confirmed type): {labels}.",
            f"Follow-ups already asked: {asked_n}. Ask at most ONE question, and only "
            "if the answer could change the trade, urgency, or whether a technician "
            "can do the job.",
            "Do not exhaust this list. Skip diagnostic extras (pressure, neighbors, "
            "troubleshooting steps, root cause) once you know the main symptom, "
            "where or how widespread it is, and roughly when it started.",
            "Set dispatch_ready true and next_question null as soon as a dispatcher "
            "could brief a provider. If they do not know an answer, record that slot "
            "as unknown (not a negative). If a trade can already be briefed, stop; "
            "otherwise ask a different useful question, never the same slot, never a "
            "canned leak/clog substitute. If the job is unusual or spans trades, "
            "ignore these hints.",
        ]
    )

