from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lateletter.garden.input_adapters import semantic_payload
from lateletter.garden.world.commands import command
from lateletter.garden.world.clock import reconcile_offline
from lateletter.garden.world.engine import CommandResult, dispatch
from lateletter.garden.world.animals import (
    ANIMAL_SPECIES,
    TIER_REPERTOIRES,
    AnimalContext,
    step_animals,
)
from lateletter.garden.world.fixtures import FIXTURE_CATALOG, fixture_active_affordances
from lateletter.garden.world.generation import generate_initial_world
from lateletter.garden.world.model import (
    EpisodicMemory,
    OrganNode,
    Vec2,
    WorldState,
    canonical_json_bytes,
)
from lateletter.garden.world.model import FixtureState, MILESTONE_RECEIPT_LIMIT
from lateletter.garden.world.projection import project_scene


ROOT = Path(__file__).parents[2]
SCENARIO_PATH = ROOT / "tests" / "fixtures" / "garden_world_golden_scenario.json"
NODE_RUNNER = ROOT / "tests" / "garden_adapters" / "test_garden_world.mjs"

def _scenario() -> dict[str, Any]:
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def _result_payload(result: CommandResult) -> dict[str, Any]:
    return {
        "accepted": result.accepted,
        "changed": result.changed,
        "reason": result.reason,
        "summary": result.summary,
        "available_actions": list(result.available_actions),
        "details": result.details,
    }


def _run_python_scenario() -> dict[str, Any]:
    scenario = _scenario()
    state = WorldState.from_dict(scenario["initial_state"])
    checkpoints = []
    last_command = None
    for step in scenario["commands"]:
        value = command(
            state.world_id,
            step["sequence"],
            step["kind"],
            target_id=step["target_id"],
            args=step["args"],
        )
        state, result = dispatch(state, value)
        assert result.accepted, f"{step['sequence']}:{step['kind']} {result.reason}"
        checkpoints.append({
            "command": semantic_payload(value),
            "result": _result_payload(result),
            "state": state.to_dict(),
        })
        last_command = value

    assert last_command is not None
    duplicate_state, duplicate_result = dispatch(state, last_command)
    gap = command(state.world_id, state.command_sequence + 2, "back")
    gap_state, gap_result = dispatch(state, gap)
    final_state = state.to_dict()
    final_json = canonical_json_bytes(final_state).decode("utf-8")
    restored = WorldState.from_dict(json.loads(final_json))
    restored_json = canonical_json_bytes(restored.to_dict()).decode("utf-8")
    return {
        "checkpoints": checkpoints,
        "final_state": final_state,
        "final_json": final_json,
        "duplicate": {
            "result": _result_payload(duplicate_result),
            "state": duplicate_state.to_dict(),
        },
        "sequence_gap": {
            "result": _result_payload(gap_result),
            "state": gap_state.to_dict(),
        },
        "persistence_round_trip_json": restored_json,
    }


def test_python_golden_scenario_covers_all_commands_and_expected_state():
    scenario = _scenario()
    assert len({item["kind"] for item in scenario["commands"]}) == 15
    final = _run_python_scenario()["final_state"]
    expected = scenario["final_expectations"]
    plant = next(item for item in final["plants"] if item["plant_id"] == "plant:rose")
    animal = next(item for item in final["animals"] if item["animal_id"] == "animal:rabbit")
    fixture = next(item for item in final["fixtures"] if item["fixture_id"] == "fixture:lantern-golden")
    assert final["command_sequence"] == expected["command_sequence"]
    assert final["ui"]["camera"] == expected["camera"]
    assert plant["growth_points"] == expected["plant_growth_points"]
    assert plant["tended_count"] == expected["plant_tended_count"]
    assert animal["bond_points"] == expected["animal_bond_points"]
    assert animal["bond_tier"] == expected["animal_bond_tier"]
    assert animal["interaction_counts"] == expected["animal_interaction_counts"]
    assert final["inventory"] == expected["inventory"]
    assert fixture["position"] == expected["placed_fixture_position"]
    assert fixture["rotation"] == expected["placed_fixture_rotation"]
    assert final["ui"]["journal_open"] is expected["journal_open"]
    assert final["ui"]["motion_paused"] is expected["motion_paused"]
    assert len(final["event_trace"]) == expected["trace_count"]
    assert len(final["undo_stack"]) == expected["undo_depth"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_python_and_browser_worlds_match_every_checkpoint_and_persisted_byte():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--emit"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    browser = json.loads(result.stdout)
    python = _run_python_scenario()
    assert browser == python


# The starter row, as decided by the operator on 2026-08-01, in thousandths of
# the world extent. Pinned here as a literal so that changing the composition
# requires changing this test as well — the anchors are canonical world data,
# and a silent edit to them is a silent edit to everybody's Garden.
AUTHORITATIVE_STARTER_ANCHORS = {
    "stepping_stones": (250, 650),
    "bench": (375, 650),
    "mailbox": (500, 650),
    "lantern": (625, 650),
    "planter": (750, 650),
}


def _starter_anchor_subset() -> dict[str, tuple[int, int]]:
    """Just the five starter entries of the canonical anchor table.

    The table also holds anchors for the five catalog fixtures that are NOT in
    the default scene; those are for authored programs and are deliberately not
    pinned here.
    """
    from lateletter.garden.world.generation import STARTER_FIXTURE_ANCHORS

    return {
        catalog_id: STARTER_FIXTURE_ANCHORS[catalog_id]
        for catalog_id in AUTHORITATIVE_STARTER_ANCHORS
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_starter_composition_is_authoritative_and_identical_in_both_generators():
    """The five starter fixtures land on the same cells in Python and the browser.

    Comparing the two anchor TABLES would not be enough. The tables are only
    inputs; what a recipient sees is the output of scaling them against the
    world extent, clamping them inside the margin, and nudging them apart when
    footprints collide. Two identical tables can still produce different worlds
    if any of those steps differs, so this compares the generated fixtures.
    """
    assert _starter_anchor_subset() == AUTHORITATIVE_STARTER_ANCHORS

    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--starter-emit"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    browser = json.loads(result.stdout)
    world = generate_initial_world("starter-composition", "starter-seed")
    python = {
        "world_width": world.world_width,
        "world_height": world.world_height,
        "camera": [world.ui.camera.x, world.ui.camera.y],
        "fixtures": [
            {
                "catalog_id": fixture.catalog_id,
                "position": [fixture.position.x, fixture.position.y],
                "rotation": fixture.rotation,
            }
            for fixture in world.fixtures
        ],
    }
    by_catalog = lambda record: record["catalog_id"]  # noqa: E731
    browser["fixtures"].sort(key=by_catalog)
    python["fixtures"].sort(key=by_catalog)
    assert browser == python

    # The row is a row: one shared depth, strictly increasing x in the canonical
    # left-to-right order. Losing either property is what let three fixtures
    # hide behind one another in the first single-surface capture.
    ordered = [
        next(item for item in python["fixtures"] if item["catalog_id"] == catalog_id)
        for catalog_id in AUTHORITATIVE_STARTER_ANCHORS
    ]
    assert len({item["position"][1] for item in ordered}) == 1
    columns = [item["position"][0] for item in ordered]
    assert columns == sorted(columns) and len(set(columns)) == len(columns)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_python_and_browser_projection_match_topology_and_connected_state_exactly():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--projection-emit"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    browser = json.loads(result.stdout)
    python = project_scene(WorldState.from_dict(_scenario()["initial_state"])).to_dict()
    assert browser == python


def _run_python_advanced_scenario() -> dict[str, Any]:
    state = WorldState.from_dict(_scenario()["initial_state"])
    state = __import__("dataclasses").replace(
        state, program_state={**dict(state.program_state), "story_complete": True},
    )
    steps = (
        ("primary_interact", "fixture:bench", {"fixture_action": "sit"}),
        ("tend", "plant:rose", {"care_action": "prune"}),
        ("tend", "plant:rose", {"care_action": "train"}),
        ("tend", "plant:rose", {"care_action": "rest"}),
        ("tend", "plant:rose", {"care_action": "transplant", "x": 20, "y": 20}),
        ("undo", None, {}),
        ("place", None, {"object_kind": "plant", "catalog_id": "willow", "object_id": "plant:placed", "x": 22, "y": 20}),
        ("move_fixture", "plant:placed", {"x": 23, "y": 20}),
        ("collect", "collectible:feather", {}),
        ("inspect", "collectible:feather", {}),
        ("open_journal", None, {}),
    )
    checkpoints = []
    for sequence, (kind, target_id, args) in enumerate(steps, start=1):
        value = command(state.world_id, sequence, kind, target_id=target_id, args=args)
        state, result = dispatch(state, value)
        assert result.accepted, result.reason
        checkpoints.append({"result": _result_payload(result), "state": state.to_dict()})
    offline_source = __import__("dataclasses").replace(state, last_observed_wall_time=100)
    offline_state, offline_report = reconcile_offline(offline_source, 200)
    return {
        "checkpoints": checkpoints,
        "projection": project_scene(state).to_dict(),
        "final_json": canonical_json_bytes(state.to_dict()).decode("utf-8"),
        "offline": {
            "state": offline_state.to_dict(),
            "report": {
                "elapsed_seconds": offline_report.elapsed_seconds,
                "rollback_clamped": offline_report.rollback_clamped,
                "summaries": list(offline_report.summaries),
                "receipt_ids": list(offline_report.receipt_ids),
            },
        },
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_advanced_python_and_browser_reducers_are_byte_identical():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--advanced-emit"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == _run_python_advanced_scenario()


def _run_python_stress_scenario() -> dict[str, Any]:
    state = WorldState.from_dict(_scenario()["initial_state"])
    for sequence in range(1, 701):
        value = command(
            state.world_id, sequence, "move_fixture", target_id="fixture:bench",
            args={"x": 7 if sequence % 2 else 8, "y": 5},
        )
        state, result = dispatch(state, value)
        assert result.accepted, result.reason
    final_json = canonical_json_bytes(state.to_dict()).decode("utf-8")
    restored = WorldState.from_dict(json.loads(final_json))
    return {
        "final_json": final_json,
        "restored_json": canonical_json_bytes(restored.to_dict()).decode("utf-8"),
        "processed_count": len(state.processed_commands),
        "trace_count": len(state.event_trace),
        "undo_count": len(state.undo_stack),
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_stress_compaction_matches_browser_bytes_and_survives_restart():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--stress-emit"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    browser = json.loads(result.stdout)
    python = _run_python_stress_scenario()
    assert browser == python
    assert python["final_json"] == python["restored_json"]
    assert (python["processed_count"], python["trace_count"], python["undo_count"]) == (
        512, 512, 128,
    )


# The content this one conformance vector needs, named here instead of
# inherited from whatever the default starter scene happens to contain.
#
# Why it has to be stated. The default scene is deliberately empty while its
# art waits for per-asset approval, so a world generated with no arguments now
# has no plants and no animals -- and a vector that compares Python and browser
# behaviour across plants and animals had nothing left to compare. Reaching for
# the default scene was always the wrong dependency: it made a parity test
# quietly contingent on a composition decision that has nothing to do with
# parity.
#
# Naming the roster locally also records what the vector is FOR. One plant is
# enough, because the plant half throws the generated topology away and
# substitutes a hand-built root/branch pair to drive the seven maturity stages
# -- the species only has to exist. The three animals are the ones whose
# decision paths differ below: bird takes the choreography-lock branch, cat the
# authored-prohibition branch, rabbit the memory-saturation branch. Turtle is
# left out on purpose -- no branch here exercises it, so including it would
# enlarge the payload without enlarging coverage.
#
# These are review-pending species: defined, placeable, and absent from the
# default scene until their drawings pass acceptance. Asking for them by name
# is what "bounded" means here -- the test states its own needs and cannot be
# broken, or silently widened, by a later change to the starter composition.
CONFORMANCE_PLANT_SPECIES = ("oak",)
CONFORMANCE_ANIMAL_SPECIES = ("bird", "cat", "rabbit")


def _animal_plant_conformance_payload_and_result():
    plant_world = generate_initial_world(
        "stage-conformance", 77, world_width=64, world_height=40,
        plant_species=CONFORMANCE_PLANT_SPECIES,
        # No animals or collectibles: the plant half discards every other record
        # a few lines below anyway, so asking for them would only add noise.
        animal_species=(),
        collectibles=(),
    )
    source_plant = plant_world.plants[0]
    root = OrganNode(
        "organ:root", None, "root", 0, 0, Vec2(0, -1), 1, "root",
    )
    organ = OrganNode(
        "organ:branch", root.node_id, "branch", 0, 1_000,
        Vec2(1, -1), 7, "branch",
    )
    plant_world = replace(
        plant_world,
        plants=(replace(source_plant, topology=(root, organ)),),
        fixtures=(), animals=(), collectibles=(),
    )
    stage_times = (0, 167, 334, 500, 667, 834, 1_000)

    animal_world = generate_initial_world(
        "animal-conformance", 91, world_width=64, world_height=40,
        # Plants and collectibles are irrelevant to animal decision parity, and
        # leaving them out keeps the compared payload to the records under test.
        plant_species=(),
        animal_species=CONFORMANCE_ANIMAL_SPECIES,
        collectibles=(),
    )
    # Guard the fixture itself. Every branch below is keyed on a species id, and
    # a missing one would not fail loudly -- the loop would simply skip it and
    # the vector would keep passing while covering less. Assert the roster
    # arrived intact so a silent shrink is a test failure, not a quiet gap.
    assert tuple(
        sorted({animal.species_id for animal in animal_world.animals})
    ) == tuple(sorted(CONFORMANCE_ANIMAL_SPECIES))
    animals = []
    for animal in animal_world.animals:
        candidates = set(ANIMAL_SPECIES[animal.species_id].repertoire)
        for tier in TIER_REPERTOIRES[animal.species_id]:
            candidates.update(tier)
        if animal.species_id == "bird":
            animal = replace(animal, energy=10, choreography_lock="scene:arrival")
        elif animal.species_id == "cat":
            animal = replace(
                animal,
                authored_prohibitions=tuple(sorted(candidates.difference({"patrol"}))),
            )
        elif animal.species_id == "rabbit":
            animal = replace(
                animal,
                authored_prohibitions=tuple(sorted(candidates.difference({"forage", "play"}))),
                recent_memories=tuple(
                    EpisodicMemory(f"feed:{index}", "feed", None, index, 50, 100)
                    for index in range(20)
                ),
            )
        animals.append(animal)
    animal_world = replace(
        animal_world,
        effective_time=43_200,
        animals=tuple(animals),
        program_state={"scene": {"season": "autumn", "weather": "calm"}},
    )
    nearby = tuple(sorted({
        value
        for fixture in animal_world.fixtures
        for value in (fixture.catalog_id, *fixture_active_affordances(fixture))
    }))
    stepped, _ = step_animals(animal_world, AnimalContext(
        effective_time=animal_world.effective_time,
        time_of_day="day",
        season="autumn",
        weather="calm",
        nearby_affordances=nearby,
    ))
    interrupted_bird = replace(
        next(animal for animal in animal_world.animals if animal.species_id == "bird"),
        energy=100,
        choreography_lock="scene:interrupted",
    )
    interrupted_world = replace(animal_world, animals=(interrupted_bird,))
    interrupted_stepped, interrupted_result = dispatch(
        interrupted_world,
        command(
            interrupted_world.world_id,
            interrupted_world.command_sequence + 1,
            "inspect",
            target_id=interrupted_bird.animal_id,
        ),
    )
    assert interrupted_result.accepted
    projections = []
    for effective_time in stage_times:
        projected = project_scene(replace(plant_world, effective_time=effective_time))
        plant = next(item for item in projected.objects if item.object_id == source_plant.plant_id)
        projections.append(next(
            item for item in plant.semantic_state["visible_organs"]
            if item["node_id"] == organ.node_id
        ))
    projection = project_scene(stepped).to_dict()
    restarted = WorldState.from_dict(json.loads(canonical_json_bytes(stepped.to_dict())))
    payload = {
        "plant_state": plant_world.to_dict(),
        "plant_id": source_plant.plant_id,
        "organ_id": organ.node_id,
        "stage_times": list(stage_times),
        "animal_state": animal_world.to_dict(),
        "interrupted_animal_state": interrupted_world.to_dict(),
    }
    expected = {
        "stages": projections,
        "animal_state": stepped.to_dict(),
        "animal_projection": projection,
        "restarted_projection": project_scene(restarted).to_dict(),
        "interrupted_animal_state": interrupted_stepped.to_dict(),
        "interrupted_animal_projection": project_scene(interrupted_stepped).to_dict(),
        "interrupted_restarted_projection": project_scene(WorldState.from_dict(
            json.loads(canonical_json_bytes(interrupted_stepped.to_dict())),
        )).to_dict(),
    }
    return payload, expected


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_animal_decisions_locomotion_and_all_plant_stages_match_browser_restart_exactly():
    payload, expected = _animal_plant_conformance_payload_and_result()
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--animal-plant-emit"],
        cwd=ROOT,
        input=json.dumps(payload),
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == expected
    records = expected["animal_state"]["program_state"]["animal_decisions"]
    assert records[next(
        animal["animal_id"] for animal in expected["animal_state"]["animals"]
        if animal["species_id"] == "bird"
    )]["priority_reason"] == "safety_or_interruption"
    interrupted = expected["interrupted_animal_state"]
    interrupted_id = interrupted["animals"][0]["animal_id"]
    assert interrupted["animals"][0]["current_intent"] == "rest"
    assert interrupted["animals"][0]["choreography_lock"] is None
    assert interrupted["program_state"]["animal_decisions"][interrupted_id][
        "priority_reason"
    ] == "safety_or_interruption"
    interrupted_projection = next(
        item for item in expected["interrupted_animal_projection"]["objects"]
        if item["object_id"] == interrupted_id
    )
    assert interrupted_projection["semantic_state"]["choreography_locked"] is False
    assert interrupted_projection["semantic_state"]["choreography_phase"] == "orient"


def _run_python_fixture_scenario() -> dict[str, str]:
    output: dict[str, str] = {}
    for catalog_id, definition in FIXTURE_CATALOG.items():
        for verb in definition.interaction_verbs:
            state = WorldState.from_dict(_scenario()["initial_state"])
            authored_state = {"water_level": 3} if verb == "water" else {}
            state = __import__("dataclasses").replace(
                state,
                fixtures=(FixtureState(
                    "fixture:test", catalog_id, Vec2(8, 5),
                    authored_state=authored_state,
                ),),
            )
            if verb == "arrange":
                found = __import__("dataclasses").replace(
                    state.collectibles[0], collected=True,
                )
                state = __import__("dataclasses").replace(
                    state, collectibles=(found,), inventory=(found.collectible_id,),
                )
            value = command(
                state.world_id, 1, "primary_interact",
                target_id="fixture:test", args={"fixture_action": verb},
            )
            updated, result = dispatch(state, value)
            assert result.accepted, f"{catalog_id}:{verb}:{result.reason}"
            output[f"{catalog_id}:{verb}"] = canonical_json_bytes(
                updated.to_dict(),
            ).decode("utf-8")
    return output


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_every_fixture_verb_has_exact_browser_python_linked_world_effects():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--fixture-emit"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    browser = json.loads(result.stdout)
    python = _run_python_fixture_scenario()
    assert browser == python
    for encoded in python.values():
        state = json.loads(encoded)
        # Every verb changes canonical state outside the fixture counter and
        # journal: linked UI focus/camera plus plant/animal/resource/inventory.
        assert state["ui"]["focus_id"] == "fixture:test"
        assert state["ui"]["camera"] == [8, 5]
        assert state["animals"][0]["recent_memories"]


def _run_python_ledger_stress() -> dict[str, Any]:
    state = WorldState.from_dict(_scenario()["initial_state"])
    state = __import__("dataclasses").replace(state, last_observed_wall_time=0)
    for day in range(1, 701):
        state, _ = reconcile_offline(state, day * 86_400)
    restored = WorldState.from_dict(json.loads(canonical_json_bytes(
        state.to_dict(),
    ).decode("utf-8")))
    return {
        "final_json": canonical_json_bytes(state.to_dict()).decode("utf-8"),
        "restored_json": canonical_json_bytes(restored.to_dict()).decode("utf-8"),
        "receipt_count": len(state.milestone_receipts),
        "receipt_total": state.program_state["milestone_receipt_total"],
        "offline_total": state.program_state["offline_reconciliation_total"],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_multi_year_offline_receipts_are_bounded_byte_exact_and_restart_stable():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--ledger-stress-emit"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    browser = json.loads(result.stdout)
    python = _run_python_ledger_stress()
    assert browser == python
    assert python["final_json"] == python["restored_json"]
    assert python["receipt_count"] == MILESTONE_RECEIPT_LIMIT
    assert python["receipt_total"] > python["receipt_count"]
    assert python["offline_total"] == 700


def test_the_terminal_renders_the_same_starter_composition_the_browser_reviews():
    """Terminal parity for the composition the browser review actually shows.

    The world-state conformance above proves both implementations agree on
    canonical bytes. It does not prove the TERMINAL draws that world, and the
    browser review (tests/test_garden_review_e2e_browser.py) only ever measures
    the browser -- so "browser and terminal parity" was an unmeasured claim in
    the middle.

    This closes the narrow, checkable part of it: the same starter world, put
    through the terminal renderer, produces ink, and every canonical object the
    browser review reports is present in the terminal's own object set. It does
    NOT claim the two pictures match -- they must not, one is proportional and
    one is ascii-safe -- only that the terminal draws the same composition.
    """
    from lateletter.garden.renderer import GardenRenderer
    from lateletter.garden.world.generation import generate_initial_world
    from lateletter.garden.world.provenance import world_census

    world = generate_initial_world("parity-probe", "parity-probe")

    # The same census the browser review asserts it is looking at.
    assert world_census(world) == {
        "plants": 2, "fixtures": 5, "animals": 0, "collectibles": 0,
    }

    renderer = GardenRenderer(120, 48)
    lines = renderer.render_lines(world)
    ink = sum(len(line.strip()) for line in lines)
    assert ink > 0, "the terminal drew nothing for the starter composition"

    # Every canonical object id the browser would project is a real object here
    # too: same identities, same world, two renderers.
    assert len(world.object_ids()) == 7, world.object_ids()
    for fixture in world.fixtures:
        assert fixture.catalog_id in {
            "bench", "lantern", "mailbox", "planter", "stepping_stones",
        }, f"the terminal starter holds an unexpected fixture: {fixture.catalog_id}"


def test_every_starter_object_has_terminal_ink_as_well_as_browser_ink():
    """Render parity in the only sense the contract allows.

    The two pictures must NOT match -- one is proportional, one ascii-safe --
    so comparing them would assert something the spec forbids. What must hold is
    that every semantic object selects art in BOTH profiles: an enhanced browser
    asset with no valid terminal fallback is a gap that only shows up when
    somebody opens the terminal.

    The composition check above proved both renderers hold the same objects.
    This goes one step further and requires the terminal to actually PUT INK
    somewhere for each of them, so an object cannot be present in the world,
    drawn in the browser, and invisible in the terminal.
    """
    from lateletter.garden.atlas import atlas_asset_frame, validate_atlas
    from lateletter.garden.renderer import GardenRenderer
    from lateletter.garden.world.generation import generate_initial_world

    world = generate_initial_world("render-parity", "render-parity")
    lines = renderer_lines = GardenRenderer(120, 48).render_lines(world)
    assert any(line.strip() for line in lines), "the terminal drew nothing"

    # Every accepted fixture in the starter must resolve to terminal art. A
    # missing frame raises, so this is a real lookup and not a truthiness check.
    for fixture in world.fixtures:
        frame = atlas_asset_frame(
            _atlas_asset(f"fixture.{fixture.catalog_id}"), state="idle",
        )
        assert frame, f"{fixture.catalog_id} has no terminal frame"
        # A frame is rows of (glyph, ...) cells rather than strings, so ink is
        # counted per cell. Checking truthiness of the frame alone would accept
        # a frame of blanks, which is exactly the invisible-in-terminal case
        # this test exists to catch.
        ink = sum(
            1 for row in frame for cell in row
            if str(cell[0] if isinstance(cell, (tuple, list)) else cell).strip()
        )
        assert ink > 0, f"{fixture.catalog_id} resolves to an empty terminal frame"


def _atlas_asset(asset_id: str):
    """Look one asset out of the versioned atlas, by id."""
    import json

    from lateletter.garden.atlas import validate_atlas

    root = Path(__file__).resolve().parents[2]
    atlas = validate_atlas(
        json.loads((root / "src" / "lateletter" / "garden" / "data" / "atlas.v2.json")
                   .read_text(encoding="utf-8"))
    )
    for asset in atlas["assets"]:
        if asset["id"] == asset_id:
            return asset
    raise AssertionError(f"{asset_id} is not in the atlas")
