from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lateletter.garden.input_adapters import semantic_payload
from lateletter.garden.world.commands import command
from lateletter.garden.world.clock import reconcile_offline
from lateletter.garden.world.engine import CommandResult, dispatch
from lateletter.garden.world.model import WorldState, canonical_json_bytes
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
