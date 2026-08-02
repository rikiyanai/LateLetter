"""Deterministic four-species hybrid animal controller."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from .fixtures import (
    blocked_cells,
    fixture_active_affordances,
    fixture_cells,
    layout_is_safe,
)
from .model import AnimalState, Personality, Vec2, WorldState
from .rng import DeterministicRNG, derive_seed


class ChoreographyLockError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnimalSpeciesDefinition:
    species_id: str
    repertoire: tuple[str, ...]
    fixture_affinities: tuple[str, ...]
    weather_response: str
    minimum_dwell_seconds: tuple[tuple[str, int], ...]

    def dwell_for(self, intent: str) -> int:
        return dict(self.minimum_dwell_seconds).get(intent, 12)


ANIMAL_SPECIES: dict[str, AnimalSpeciesDefinition] = {
    "bird": AnimalSpeciesDefinition(
        "bird",
        ("perch", "hop", "sing", "bathe", "forage", "greet"),
        ("fence", "birdbath", "trellis"),
        "shelter_in_heavy_weather",
        (("perch", 18), ("sing", 12), ("bathe", 15), ("hop", 8)),
    ),
    "cat": AnimalSpeciesDefinition(
        "cat",
        ("patrol", "sniff", "nap", "knead", "play", "greet"),
        ("bench", "table", "memory_shrine"),
        "seek_shelter_from_rain",
        (("nap", 45), ("patrol", 20), ("knead", 14), ("play", 12)),
    ),
    "rabbit": AnimalSpeciesDefinition(
        "rabbit",
        ("hop", "forage", "hide", "groom", "play", "greet"),
        ("trellis", "planter", "bench"),
        "hide_during_heavy_rain",
        (("groom", 20), ("hide", 30), ("hop", 10), ("play", 12)),
    ),
    "turtle": AnimalSpeciesDefinition(
        "turtle",
        ("walk", "sunbathe", "paddle", "rest", "forage", "greet"),
        ("pond", "bridge", "stepping_stone"),
        "rest_in_cold_weather",
        (("sunbathe", 60), ("walk", 30), ("paddle", 35), ("rest", 45)),
    ),
}

# The bond tier at which an animal stops being a stranger. Below it, feeding is
# the act that builds trust and is therefore worth surfacing; at and above it
# the animal already trusts the reader and food is no longer the point.
ANIMAL_TRUST_TIER = 3


def animal_display_name(animal: AnimalState) -> str:
    """What to call this animal in a sentence addressed to the reader."""
    return animal.display_name or animal.species_id.replace("_", " ")


def animal_primary_action(animal: AnimalState) -> dict[str, str]:
    """The single act a plain click, tap or Enter on this animal performs.

    SPEC 7.8.3.1, and the operator's decision of 2026-07-31: interaction with a
    living thing is DIRECT. Clicking the cat does something to the cat; it does
    not open a menu about the cat.

    The verb is `play`, which is this world model's existing safe, resource-free
    animal interaction -- it costs nothing, cannot be got wrong, and is
    reversible in the only sense that matters, which is that doing it again is
    fine. The decision text says "click to pet cat"; `pet` is not a canonical
    command here, and inventing one so the label could match the example would
    have meant the renderer dispatching something the world does not implement.
    The model's word for the same gesture is `play`.

    Feeding is deliberately NOT the primary. It is state-dependent -- it means
    something entirely different to a stray than to a companion -- and
    7.8.3.2 reserves state-dependent acts for spawned opportunities.

    :param animal: The animal being projected.
    :returns: `{verb, label}`; the projection turns it into a command record.
    """
    return {
        "verb": "play",
        "label": f"Play with the {animal_display_name(animal)}",
    }


def animal_opportunities(animal: AnimalState) -> tuple[dict[str, str], ...]:
    """The spawned opportunities this animal is currently offering.

    SPEC 7.8.3.2, and the operator's decision: "Feeding is a spawned
    beside-object opportunity, not the cat's primary action. A spawned
    affordance represents a state-dependent opportunity such as feeding an
    eligible animal."

    Eligibility is exactly what the browser HUD used to test for privately
    before this moved into the world model: an animal below the trust tier. The
    difference is that the browser is no longer the one deciding. It draws what
    this returns, so the terminal offers the same thing from the same state, and
    an opportunity cannot appear in one surface and not the other.

    :param animal: The animal whose current state decides what is on offer.
    :returns: Records of `{opportunity_id, verb, label}` sorted by
        `opportunity_id`; empty when nothing is on offer.
    """
    offers: list[dict[str, str]] = []
    if animal.bond_tier < ANIMAL_TRUST_TIER:
        offers.append({
            "verb": "feed",
            "label": f"Feed the {animal_display_name(animal)}",
        })
    return tuple(sorted(
        (
            {
                "opportunity_id": f"{animal.animal_id}:{offer['verb']}",
                "verb": offer["verb"],
                "label": offer["label"],
            }
            for offer in offers
        ),
        key=lambda offer: offer["opportunity_id"],
    ))


TIER_REPERTOIRES: dict[str, tuple[tuple[str, ...], ...]] = {
    "bird": (
        ("watch_from_branch", "startle_flutter", "explore_edge"),
        ("pause_approach", "perch_nearby", "bathe"),
        ("initiate_song_play", "follow_overhead", "rest_near", "recall_perch"),
        ("return_greet", "bring_feather", "share_perch", "deliver_song"),
    ),
    "cat": (
        ("watch_from_cover", "startle_retreat", "explore_edge"),
        ("pause_approach", "sniff_nearby", "use_bench"),
        ("initiate_string_play", "follow_path", "rest_near", "recall_knead"),
        ("return_greet", "bring_whisker", "share_bench", "settled_knead"),
    ),
    "rabbit": (
        ("watch_from_hide", "startle_hop", "explore_edge"),
        ("pause_approach", "forage_nearby", "use_trellis"),
        ("initiate_hop_play", "follow_briefly", "rest_near", "recall_treat"),
        ("return_greet", "bring_track", "share_planter", "settled_flop"),
    ),
    "turtle": (
        ("watch_from_water", "withdraw_gently", "explore_edge"),
        ("pause_approach", "walk_nearby", "use_pond"),
        ("initiate_follow", "follow_briefly", "rest_near", "recall_sunspot"),
        ("return_greet", "bring_scute", "share_bridge", "settled_sunbathe"),
    ),
}

ANIMAL_GIFT_CATALOG: dict[str, tuple[str, str, str]] = {
    "bird": ("bird_feather", "Bird feather", "A feather offered from a favorite perch."),
    "cat": ("cat_whisker", "Cat whisker", "A whisker found where a trusted cat settled nearby."),
    "rabbit": ("rabbit_track", "Rabbit track", "A soft print left beside a shared garden path."),
    "turtle": ("turtle_scute", "Turtle scute", "A naturally shed scute left by a familiar turtle."),
}

INTENT_AFFORDANCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "bathe": ("bathe",),
    "paddle": ("pond", "water-visitor"),
    "perch": ("perch",),
    "perch_nearby": ("perch",),
    "use_bench": ("bench", "animal-rest"),
    "share_bench": ("bench", "animal-rest"),
    "use_trellis": ("trellis", "animal-hide"),
    "share_planter": ("planter", "plant-container"),
    "use_pond": ("pond", "water-visitor"),
    "share_bridge": ("bridge", "animal-route"),
    "follow_path": ("path", "route"),
}

RECENT_MEMORY_LIMIT = 16
_CARDINAL_STEPS = (Vec2(0, -1), Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0))
_MOVING_INTENT_TOKENS = (
    "approach", "bathe", "bring", "cross", "explore", "follow", "forage",
    "greet", "hop", "paddle", "patrol", "play", "sniff", "walk",
)
_MEMORY_INTENT_TOKENS: dict[str, tuple[str, ...]] = {
    "feed": ("approach", "bring", "forage", "greet", "recall", "sniff"),
    "play": ("flop", "follow", "hop", "knead", "play", "sing", "song"),
    "observe": ("groom", "near", "perch", "rest", "watch"),
}
_SEASON_INTENT_TOKENS: dict[str, tuple[str, ...]] = {
    "spring": ("forage", "greet", "sing", "song"),
    "summer": ("bathe", "paddle", "play", "sunbathe"),
    "autumn": ("explore", "forage", "patrol", "sniff"),
    "winter": ("hide", "nap", "rest", "settled"),
}


@dataclass(frozen=True)
class AnimalContext:
    effective_time: int
    time_of_day: str = "day"
    season: str = "spring"
    weather: str = "calm"
    recipient_focus_id: str | None = None
    nearby_affordances: tuple[str, ...] = ()
    interrupted_animal_id: str | None = None
    returning: bool = False


@dataclass(frozen=True)
class AnimalDecision:
    animal_id: str
    high_level_state: str
    intent: str
    score: int
    retained_by_hysteresis: bool = False
    priority_reason: str = "utility"


def personality_for(world_seed: int | str | bytes, animal_id: str) -> Personality:
    rng = DeterministicRNG(derive_seed(world_seed, "animal", animal_id, "personality"))
    return Personality(*[rng.randint(20, 80) for _ in range(8)])


def create_animal(
    world_seed: int | str | bytes,
    animal_id: str,
    species_id: str,
    position: Vec2,
) -> AnimalState:
    if species_id not in ANIMAL_SPECIES:
        raise ValueError(f"unknown animal species {species_id}")
    return AnimalState(
        animal_id=animal_id,
        species_id=species_id,
        position=position,
        personality=personality_for(world_seed, animal_id),
    )


def acquire_choreography(
    animal: AnimalState,
    scene_id: str,
    effective_time: int,
) -> AnimalState:
    if animal.choreography_lock not in (None, scene_id):
        raise ChoreographyLockError(
            f"animal {animal.animal_id} is locked by {animal.choreography_lock}",
        )
    if animal.choreography_lock == scene_id:
        return animal
    return replace(
        animal,
        choreography_lock=scene_id,
        high_level_state="authored_scene",
        current_intent=f"choreography:{scene_id}",
        intent_started_at=effective_time,
        minimum_dwell_until=effective_time,
    )


def release_choreography(
    animal: AnimalState,
    scene_id: str,
    effective_time: int,
) -> AnimalState:
    if animal.choreography_lock != scene_id:
        raise ChoreographyLockError(
            f"scene {scene_id} does not own animal {animal.animal_id}",
        )
    return replace(
        animal,
        choreography_lock=None,
        high_level_state="awake",
        current_intent="recover",
        intent_started_at=effective_time,
        minimum_dwell_until=effective_time + 5,
    )


def _utility_score(
    animal: AnimalState,
    intent: str,
    context: AnimalContext,
    world_seed: int | str | bytes,
) -> int:
    personality = animal.personality
    score = 20
    if any(token in intent for token in ("play", "hop", "knead", "flop")):
        score += personality.playfulness + animal.play_appetite
    if any(token in intent for token in ("patrol", "sniff", "forage", "walk", "paddle", "explore")):
        score += personality.curiosity
    if any(token in intent for token in ("greet", "song", "sing", "approach")):
        score += personality.sociability + animal.bond_tier * 12
    if any(token in intent for token in ("rest", "nap", "sunbathe", "perch", "groom", "hide", "settled")):
        score += animal.rest_appetite + max(0, 60 - animal.energy)
    if intent == "forage":
        score += personality.food_motivation
    if intent in animal.authored_preferences:
        score += 60
    definition = ANIMAL_SPECIES[animal.species_id]
    required = INTENT_AFFORDANCE_REQUIREMENTS.get(intent, ())
    if required and not any(value in context.nearby_affordances for value in required):
        score -= 2_000
    if any(affordance in context.nearby_affordances for affordance in definition.fixture_affinities):
        score += 20
    cooldown_until = dict(animal.cooldowns).get(intent, 0)
    if cooldown_until > context.effective_time:
        score -= 1_000
    recent = sorted(
        animal.recent_memories,
        key=lambda memory: (memory.timestamp, memory.memory_id),
    )[-RECENT_MEMORY_LIMIT:]
    for memory in recent:
        tokens = _MEMORY_INTENT_TOKENS.get(memory.kind, ())
        if tokens and any(token in intent for token in tokens):
            magnitude = 8 + min(12, max(0, memory.salience) // 10)
            score += magnitude if memory.valence >= 0 else -magnitude
    weather = context.weather.casefold()
    if weather in {"rain", "heavy_rain", "storm"}:
        if any(token in intent for token in ("bathe", "hide", "nap", "paddle", "rest")):
            score += 35
        if any(token in intent for token in ("play", "sing", "sunbathe")):
            score -= 35
    elif weather in {"clear", "sunny"}:
        if any(token in intent for token in ("play", "sing", "sunbathe")):
            score += 25
    elif weather in {"cold", "snow", "blizzard"}:
        if any(token in intent for token in ("hide", "nap", "rest", "settled")):
            score += 40
        if any(token in intent for token in ("bathe", "paddle", "sunbathe")):
            score -= 40
    season_tokens = _SEASON_INTENT_TOKENS.get(context.season.casefold(), ())
    if any(token in intent for token in season_tokens):
        score += 30
    noise = DeterministicRNG(derive_seed(
        world_seed,
        "animal",
        animal.animal_id,
        "utility",
        animal.decision_index,
        intent,
    )).randint(0, 9)
    return score + noise


def decide_animal(
    animal: AnimalState,
    context: AnimalContext,
    world_seed: int | str | bytes,
) -> AnimalDecision:
    definition = ANIMAL_SPECIES[animal.species_id]
    if context.interrupted_animal_id == animal.animal_id or animal.energy <= 15:
        return AnimalDecision(
            animal.animal_id,
            "resting",
            "rest",
            9_000,
            priority_reason="safety_or_interruption",
        )
    severe_weather = context.weather.casefold() in {"heavy_rain", "storm", "blizzard"}
    cold_turtle = (
        animal.species_id == "turtle"
        and context.weather.casefold() in {"cold", "snow", "blizzard"}
    )
    if severe_weather or cold_turtle:
        safe_intent = {
            "bird": "perch",
            "cat": "nap",
            "rabbit": "hide",
            "turtle": "rest",
        }[animal.species_id]
        return AnimalDecision(
            animal.animal_id,
            "resting",
            safe_intent,
            9_500,
            priority_reason="weather_safety",
        )
    if animal.choreography_lock:
        return AnimalDecision(
            animal.animal_id,
            "authored_scene",
            f"choreography:{animal.choreography_lock}",
            9_000,
            priority_reason="authored_choreography",
        )
    if (
        animal.current_intent not in ("idle", "recover")
        and context.effective_time < animal.minimum_dwell_until
    ):
        return AnimalDecision(
            animal.animal_id,
            animal.high_level_state,
            animal.current_intent,
            0,
            retained_by_hysteresis=True,
            priority_reason="minimum_dwell",
        )
    if context.recipient_focus_id == animal.animal_id and animal.bond_tier >= 1:
        return AnimalDecision(
            animal.animal_id,
            "awake",
            "greet",
            8_000,
            priority_reason="relationship_response",
        )
    tier_repertoire = TIER_REPERTOIRES[animal.species_id][animal.bond_tier]
    if context.returning:
        return AnimalDecision(
            animal.animal_id,
            "awake",
            tier_repertoire[0],
            7_500,
            priority_reason="positive_return_greeting",
        )
    if context.time_of_day == "night" and animal.personality.day_preference >= 65:
        return AnimalDecision(
            animal.animal_id,
            "sleeping",
            "rest",
            7_000,
            priority_reason="routine",
        )
    candidates = tuple(
        intent for intent in definition.repertoire
        if intent not in animal.authored_prohibitions
    ) + tuple(intent for intent in tier_repertoire if intent not in animal.authored_prohibitions)
    scored = [
        (_utility_score(animal, intent, context, world_seed), intent)
        for intent in candidates
    ]
    score, intent = max(scored, key=lambda item: (item[0], item[1]))
    high_level = "resting" if any(
        token in intent for token in ("rest", "nap", "sunbathe", "perch", "groom", "hide", "settled")
    ) else "awake"
    return AnimalDecision(animal.animal_id, high_level, intent, score)


def step_animal(
    animal: AnimalState,
    context: AnimalContext,
    world_seed: int | str | bytes,
) -> tuple[AnimalState, AnimalDecision]:
    decision = decide_animal(animal, context, world_seed)
    if decision.retained_by_hysteresis:
        return animal, decision
    definition = ANIMAL_SPECIES[animal.species_id]
    dwell = definition.dwell_for(decision.intent)
    # Safety and a recipient's direct semantic interruption release authored
    # choreography before the resting decision is published.  The projection
    # must never claim an animal is still performing while safety owns it.
    source = replace(animal, choreography_lock=None) if decision.priority_reason in {
        "safety_or_interruption", "weather_safety",
    } else animal
    updated = replace(
        source,
        high_level_state=decision.high_level_state,
        current_intent=decision.intent,
        intent_started_at=context.effective_time,
        minimum_dwell_until=context.effective_time + dwell,
        decision_index=animal.decision_index + 1,
        cooldowns=tuple(sorted({
            **dict(animal.cooldowns),
            decision.intent: context.effective_time + dwell,
        }.items())),
    )
    return updated, decision


def _fixture_target_cells(
    state: WorldState,
    animal: AnimalState,
    intent: str,
) -> tuple[Vec2, ...]:
    definition = ANIMAL_SPECIES[animal.species_id]
    desired = set(INTENT_AFFORDANCE_REQUIREMENTS.get(intent, ()))
    desired.update(definition.fixture_affinities)
    candidates = []
    for fixture in state.fixtures:
        active = {fixture.catalog_id, *fixture_active_affordances(fixture)}
        if not desired.intersection(active):
            continue
        candidates.append((fixture.fixture_id, fixture))
    if not candidates:
        return ()
    _, target = min(
        candidates,
        key=lambda item: (
            min(
                abs(animal.position.x - cell.x) + abs(animal.position.y - cell.y)
                for cell in fixture_cells(item[1])
            ),
            item[0],
        ),
    )
    return tuple(sorted(fixture_cells(target), key=lambda cell: (cell.y, cell.x)))


def _move_animal(
    state: WorldState,
    animal: AnimalState,
    decision: AnimalDecision,
) -> AnimalState:
    if decision.high_level_state != "awake" or not any(
        token in decision.intent for token in _MOVING_INTENT_TOKENS
    ):
        return animal
    rng = DeterministicRNG(derive_seed(
        state.seed,
        "animal",
        animal.animal_id,
        "locomotion",
        animal.decision_index,
        decision.intent,
    ))
    rotation = rng.randbelow(len(_CARDINAL_STEPS))
    steps = _CARDINAL_STEPS[rotation:] + _CARDINAL_STEPS[:rotation]
    targets = _fixture_target_cells(state, animal, decision.intent)
    ranked: list[tuple[int, int, Vec2]] = []
    blockers = blocked_cells(state)
    other_animals = {
        item.position for item in state.animals if item.animal_id != animal.animal_id
    }
    for rank, step in enumerate(steps):
        candidate = Vec2(animal.position.x + step.x, animal.position.y + step.y)
        if not (0 <= candidate.x < state.world_width and 0 <= candidate.y < state.world_height):
            continue
        if candidate in blockers or candidate in other_animals:
            continue
        distance = min(
            (abs(candidate.x - cell.x) + abs(candidate.y - cell.y) for cell in targets),
            default=0,
        )
        ranked.append((distance, rank, candidate))
    for _, _, candidate in sorted(ranked, key=lambda item: (item[0], item[1])):
        moved = replace(animal, position=candidate)
        animals = tuple(
            moved if item.animal_id == animal.animal_id else item
            for item in state.animals
        )
        if layout_is_safe(replace(state, animals=animals)):
            return moved
    return animal


def step_animals(
    state: WorldState,
    context: AnimalContext,
) -> tuple[WorldState, tuple[AnimalDecision, ...]]:
    if not state.animals:
        return state, ()
    scene = state.program_state.get("scene", {})
    if isinstance(scene, Mapping) and "season" in scene:
        context = replace(context, season=str(scene["season"]))
    current = state
    updated: list[AnimalState] = []
    decisions: list[AnimalDecision] = []
    decision_records: dict[str, dict[str, object]] = {}
    for animal in state.animals:
        next_animal, decision = step_animal(animal, context, state.seed)
        before = next_animal.position
        next_animal = _move_animal(current, next_animal, decision)
        current = replace(
            current,
            animals=tuple(
                next_animal if item.animal_id == animal.animal_id else item
                for item in current.animals
            ),
        )
        updated.append(next_animal)
        decisions.append(decision)
        decision_records[animal.animal_id] = {
            "intent": decision.intent,
            "priority_reason": decision.priority_reason,
            "score": decision.score,
            "retained_by_hysteresis": decision.retained_by_hysteresis,
            "moved": next_animal.position != before,
            "from_position": before.to_list(),
            "to_position": next_animal.position.to_list(),
            "weather": context.weather,
            "season": context.season,
            "memory_count": min(RECENT_MEMORY_LIMIT, len(animal.recent_memories)),
        }
    program_state = {
        **dict(state.program_state),
        "animal_decisions": decision_records,
    }
    return replace(current, animals=tuple(updated), program_state=program_state), tuple(decisions)
