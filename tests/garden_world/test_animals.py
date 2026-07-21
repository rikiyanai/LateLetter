from __future__ import annotations

from dataclasses import replace

import pytest

from lateletter.garden.world.animals import (
    ANIMAL_SPECIES,
    ANIMAL_GIFT_CATALOG,
    TIER_REPERTOIRES,
    AnimalContext,
    ChoreographyLockError,
    acquire_choreography,
    create_animal,
    decide_animal,
    release_choreography,
    step_animal,
    step_animals,
)
from lateletter.garden.world.clock import reconcile_offline
from lateletter.garden.world.commands import command
from lateletter.garden.world.engine import dispatch
from lateletter.garden.world.fixtures import layout_is_safe
from lateletter.garden.world.model import EpisodicMemory, Vec2
from lateletter.garden.world.projection import project_scene


def test_four_species_have_distinct_repertoires_and_affinities():
    assert set(ANIMAL_SPECIES) == {"bird", "cat", "rabbit", "turtle"}
    assert len({item.repertoire for item in ANIMAL_SPECIES.values()}) == 4
    for definition in ANIMAL_SPECIES.values():
        assert len(definition.repertoire) >= 6
        assert definition.fixture_affinities
        assert definition.weather_response
    assert set(TIER_REPERTOIRES) == set(ANIMAL_SPECIES)
    assert set(ANIMAL_GIFT_CATALOG) == set(ANIMAL_SPECIES)
    for tiers in TIER_REPERTOIRES.values():
        assert len(tiers) == 4
        assert all(len(tier) >= 3 for tier in tiers)


@pytest.mark.parametrize("species_id", sorted(ANIMAL_SPECIES))
def test_controller_is_deterministic_for_each_species(species_id):
    animal = create_animal("seed", f"animal:{species_id}", species_id, Vec2(4, 4))
    context = AnimalContext(100, nearby_affordances=ANIMAL_SPECIES[species_id].fixture_affinities)
    assert decide_animal(animal, context, "seed") == decide_animal(animal, context, "seed")


def test_priority_orders_safety_then_relationship_then_utility():
    animal = create_animal("seed", "animal:cat", "cat", Vec2(4, 4))
    unsafe = replace(animal, energy=10, bond_tier=3)
    decision = decide_animal(
        unsafe,
        AnimalContext(100, recipient_focus_id=unsafe.animal_id),
        "seed",
    )
    assert decision.intent == "rest"
    assert decision.priority_reason == "safety_or_interruption"

    social = replace(animal, bond_tier=1)
    decision = decide_animal(
        social,
        AnimalContext(100, recipient_focus_id=social.animal_id),
        "seed",
    )
    assert decision.intent == "greet"
    assert decision.priority_reason == "relationship_response"


def test_minimum_dwell_hysteresis_prevents_rapid_oscillation():
    animal = create_animal("seed", "animal:rabbit", "rabbit", Vec2(4, 4))
    first, decision = step_animal(animal, AnimalContext(100), "seed")
    assert not decision.retained_by_hysteresis
    second, decision = step_animal(first, AnimalContext(101, weather="rain"), "seed")
    assert decision.retained_by_hysteresis
    assert second == first


def test_choreography_lock_is_exclusive_idempotent_and_released_to_recovery():
    animal = create_animal("seed", "animal:bird", "bird", Vec2(4, 4))
    locked = acquire_choreography(animal, "scene:arrival", 100)
    assert acquire_choreography(locked, "scene:arrival", 101) == locked
    with pytest.raises(ChoreographyLockError):
        acquire_choreography(locked, "scene:other", 101)
    interrupted, decision = step_animal(
        locked,
        AnimalContext(102, interrupted_animal_id=locked.animal_id),
        "seed",
    )
    assert decision.priority_reason == "safety_or_interruption"
    assert decision.intent == "rest"
    assert interrupted.choreography_lock is None
    released = release_choreography(locked, "scene:arrival", 110)
    assert released.choreography_lock is None
    assert released.current_intent == "recover"
    with pytest.raises(ChoreographyLockError):
        release_choreography(released, "scene:arrival", 111)


def test_inspect_command_interrupts_choreography_and_projects_rest(world):
    animal = replace(
        world.animals[0], energy=100, choreography_lock="scene:arrival",
        high_level_state="authored_scene", current_intent="choreography:scene:arrival",
    )
    state = replace(world, animals=(animal,))
    updated, result = dispatch(
        state,
        command(state.world_id, 1, "inspect", target_id=animal.animal_id),
    )
    assert result.accepted
    interrupted = updated.animals[0]
    assert interrupted.current_intent == "rest"
    assert interrupted.choreography_lock is None
    projected = next(
        item for item in project_scene(updated).objects
        if item.object_id == animal.animal_id
    )
    assert projected.semantic_state["choreography_locked"] is False
    assert projected.semantic_state["choreography_phase"] == "orient"


def _only_intents(animal, *allowed):
    candidates = set(ANIMAL_SPECIES[animal.species_id].repertoire)
    for tier in TIER_REPERTOIRES[animal.species_id]:
        candidates.update(tier)
    return replace(
        animal,
        authored_prohibitions=tuple(sorted(candidates.difference(allowed))),
    )


def test_recent_memory_and_season_weather_condition_utility_choice():
    bird = _only_intents(
        create_animal("seed", "animal:bird", "bird", Vec2(4, 4)),
        "forage", "sing",
    )
    feed_memories = tuple(
        EpisodicMemory(f"feed:{index}", "feed", None, index, 50, 100)
        for index in range(20)
    )
    play_memories = tuple(
        EpisodicMemory(f"play:{index}", "play", None, index, 50, 100)
        for index in range(20)
    )
    feed_choice = decide_animal(
        replace(bird, recent_memories=feed_memories),
        AnimalContext(100, season="spring"), "seed",
    )
    play_choice = decide_animal(
        replace(bird, recent_memories=play_memories),
        AnimalContext(100, season="spring"), "seed",
    )
    assert (feed_choice.intent, play_choice.intent) == ("forage", "sing")

    turtle = _only_intents(
        replace(
            create_animal("seed", "animal:turtle", "turtle", Vec2(4, 4)),
            energy=100, rest_appetite=0,
        ),
        "sunbathe", "rest",
    )
    assert decide_animal(
        turtle, AnimalContext(100, season="summer", weather="clear"), "seed",
    ).intent == "sunbathe"
    assert decide_animal(
        turtle, AnimalContext(100, season="winter", weather="calm"), "seed",
    ).intent == "rest"


def test_routine_locomotion_is_deterministic_safe_and_visible(world):
    rabbit = _only_intents(replace(world.animals[0], current_intent="idle"), "hop")
    source = replace(
        world,
        animals=(rabbit,),
        program_state={"scene": {"season": "autumn", "weather": "calm"}},
    )
    first, decisions = step_animals(source, AnimalContext(source.effective_time))
    second, _ = step_animals(source, AnimalContext(source.effective_time))
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.animals[0].position != rabbit.position
    assert layout_is_safe(first)
    record = first.program_state["animal_decisions"][rabbit.animal_id]
    assert record["intent"] == decisions[0].intent == "hop"
    assert record["moved"] is True
    assert record["from_position"] == rabbit.position.to_list()
    assert record["to_position"] == first.animals[0].position.to_list()


def test_humane_absence_preserves_bond_memories_and_personality(world):
    original = replace(
        world.animals[0],
        bond_points=25,
        bond_tier=2,
        session_interactions=("feed", "play"),
    )
    state = replace(world, animals=(original,), last_observed_wall_time=100)
    returned, _ = reconcile_offline(state, 100 + 365 * 86_400)
    animal = returned.animals[0]
    assert animal.bond_points == original.bond_points
    assert animal.bond_tier == original.bond_tier
    assert animal.personality == original.personality
    assert animal.recent_memories == original.recent_memories
    assert animal.session_interactions == ()


def test_varied_interactions_create_bounded_episodic_memories(world):
    state = world
    for sequence, kind in enumerate(("feed", "play", "feed"), start=1):
        value = command(
            state.world_id,
            sequence,
            kind,
            target_id="animal:rabbit",
        )
        state, result = dispatch(state, value)
        assert result.accepted
    memories = state.animals[0].recent_memories
    assert [memory.kind for memory in memories] == ["feed", "play", "feed"]
    assert all(memory.timestamp == state.effective_time for memory in memories)
    assert len({memory.memory_id for memory in memories}) == 3


def test_full_bond_creates_one_species_specific_humane_gift(world):
    rabbit = replace(
        world.animals[0], bond_points=39, bond_tier=2,
        interaction_counts=(("feed", 1), ("observe", 1)), session_interactions=(),
    )
    state = replace(world, animals=(rabbit,))
    value = command(state.world_id, 1, "play", target_id=rabbit.animal_id)
    state, result = dispatch(state, value)
    assert result.accepted
    assert state.animals[0].bond_tier == 3
    gifts = [item for item in state.collectibles if item.provenance == "animal-given"]
    assert any(item.label == "Rabbit track" for item in gifts)
    value = command(state.world_id, 2, "play", target_id=rabbit.animal_id)
    state, result = dispatch(state, value)
    assert result.accepted
    assert len([item for item in state.collectibles if item.label == "Rabbit track"]) == 1
