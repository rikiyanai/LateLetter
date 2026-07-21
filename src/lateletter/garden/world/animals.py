"""Deterministic four-species hybrid animal controller."""

from __future__ import annotations

from dataclasses import dataclass, replace

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


@dataclass(frozen=True)
class AnimalContext:
    effective_time: int
    time_of_day: str = "day"
    season: str = "spring"
    weather: str = "calm"
    recipient_focus_id: str | None = None
    nearby_affordances: tuple[str, ...] = ()
    interrupted: bool = False
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
    if any(affordance in context.nearby_affordances for affordance in definition.fixture_affinities):
        score += 20
    cooldown_until = dict(animal.cooldowns).get(intent, 0)
    if cooldown_until > context.effective_time:
        score -= 1_000
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
    if animal.choreography_lock:
        return AnimalDecision(
            animal.animal_id,
            "authored_scene",
            f"choreography:{animal.choreography_lock}",
            10_000,
            priority_reason="authored_choreography",
        )
    if context.interrupted or animal.energy <= 15:
        return AnimalDecision(
            animal.animal_id,
            "resting",
            "rest",
            9_000,
            priority_reason="safety_or_interruption",
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
    updated = replace(
        animal,
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


def step_animals(
    state: WorldState,
    context: AnimalContext,
) -> tuple[WorldState, tuple[AnimalDecision, ...]]:
    updated: list[AnimalState] = []
    decisions: list[AnimalDecision] = []
    for animal in state.animals:
        next_animal, decision = step_animal(animal, context, state.seed)
        updated.append(next_animal)
        decisions.append(decision)
    return replace(state, animals=tuple(updated)), tuple(decisions)
