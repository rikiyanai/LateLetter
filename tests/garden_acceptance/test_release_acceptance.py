"""Automated subset of SPEC §7.8.13.

Passing this module is deliberately not equivalent to release acceptance.
The status matrix at the bottom names the human and integration evidence that
automation cannot supply, so fixture evidence cannot silently become a ship
claim.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, read_bundle, verify_checksum,
    write_bundle,
)
from lateletter.garden.astronomy import (
    CoarseLocation, ra_dec_to_alt_az, resolve_sky_mode,
)
from lateletter.garden.camera import Camera, Point, Rect, cells
from lateletter.garden.authoring import (
    ActionCard, BeatCard, Timeline, When, compile_timeline, preview_timeline,
)
from lateletter.garden.evaluator import evaluate_program
from lateletter.garden.materializer import apply_program
from lateletter.garden.program import parse_program
from lateletter.garden.schedule import expand_schedule, parse_schedule
from lateletter.garden.world.animals import ANIMAL_SPECIES, AnimalContext, decide_animal
from lateletter.garden.world.clock import reconcile_offline
from lateletter.garden.world.commands import command
from lateletter.garden.world.engine import dispatch
from lateletter.garden.world.fixtures import (
    CONNECTED_GROUPS, connected_tile_key, layout_is_safe,
)
from lateletter.garden.world.generation import generate_initial_world
from lateletter.garden.world.model import canonical_json_bytes, new_world
from lateletter.garden.world.projection import project_scene
from lateletter.sealed import (
    open_garden_program, seal_bundle, seal_garden_program, seal_message,
    verify_bundle_hmac,
)


ROOT = Path(__file__).parents[2]
NODE_RUNNER = Path(__file__).with_name("garden_acceptance_runner.mjs")
ASTRONOMY_FIXTURES = ROOT / "tests/garden_contract/fixtures/astronomy_vectors.v1.json"
GATE_MATRIX = Path(__file__).with_name("gate_matrix.json")
VIEWER = ROOT / "viewer-bnw.html"
DAY = 86_400


def _mapping(program) -> dict:
    def condition(value):
        if value.kind in {"all", "any"}:
            return {value.kind: [condition(child) for child in value.children]}
        if value.kind == "not":
            return {"not": condition(value.children[0])}
        result = {"fact": value.fact, "op": value.op}
        if value.ref is not None:
            result["ref"] = value.ref
        else:
            result["value"] = value.value
        return result

    return {
        "version": program.version,
        "evaluator_version": program.evaluator_version,
        "world_state_version": program.world_state_version,
        "atlas_version": program.atlas_version,
        "astronomy_catalog_version": program.astronomy_catalog_version,
        "author_timezone": program.author_timezone,
        "variables": dict(program.variables),
        "entities": [dict(value) for value in program.entities],
        "animals": [dict(value) for value in program.animals],
        "events": [{
            "id": event.id,
            "conditions": condition(event.conditions),
            "schedule": dict(event.schedule) if event.schedule is not None else None,
            "occurrence": event.occurrence,
            "priority": event.priority,
            "exclusive_group": event.exclusive_group,
            "cooldown": dict(event.cooldown) if event.cooldown is not None else None,
            "actions": [{
                "type": action.type, "target": action.target,
                "params": dict(action.params),
            } for action in event.actions],
        } for event in program.events],
    }


def _authored_arc(letter_id: str) -> Timeline:
    timeline = Timeline("America/New_York")
    timeline.entities.extend([
        {
            "id": "memory-rose", "kind": "plant", "catalog_id": "plant.rose",
            "initial_state": {"planted": True}, "placement": "random",
        },
        {
            "id": "autumn-keepsake", "kind": "collectible",
            "catalog_id": "collectible.pressed_flower",
            "initial_state": {"revealed": False}, "placement": "random",
        },
        {
            "id": "garden-bench", "kind": "fixture", "catalog_id": "fixture.bench",
            "initial_state": {"revealed": False}, "placement": "path",
        },
    ])
    timeline.animals.append({
        "id": "rabbit-clover", "species": "rabbit", "catalog_id": "animal.rabbit",
        "name": "Clover", "personality": "cautious and curious",
        "routine": "forage at dawn and rest beside the bench",
        "favorite_places": ["garden-bench"],
        "prohibited_behaviors": ["leave the garden"],
        "initial_state": {"present": False},
    })
    timeline.beats.extend([
        BeatCard(
            "letter-opens-garden", "Clover arrives", "animals",
            When.fact("letter.read", "contains", reference=letter_id),
            (
                ActionCard("entity.reveal", "garden-bench", {"position": "path"}),
                ActionCard("animal.arrive", "rabbit-clover", {
                    "position": "near_bench", "routine": "forage at dawn",
                }),
            ),
            priority=30,
        ),
        BeatCard(
            "third-revisit-growth", "The rose grows", "plants",
            When.every(
                When.fact("visit.total", ">=", 3),
                When.fact("animal.arrived", "contains", reference="rabbit-clover"),
            ),
            (ActionCard("plant.grow", "memory-rose", {"stage": 2, "amount": 1}),),
            priority=20,
        ),
        BeatCard(
            "bonded-autumn-gift", "Clover brings the autumn keepsake", "gifts",
            When.every(
                When.fact("animal.bond_tier", ">=", 3),
                When.fact("season.current", "==", "autumn"),
            ),
            (
                ActionCard.reveal("autumn-keepsake", position="near_bench"),
                ActionCard("animal.present_gift", "rabbit-clover", {
                    "gift_id": "autumn-keepsake",
                }),
            ),
            priority=10,
        ),
    ])
    return timeline


def test_normal_sealed_v2_bundle_drives_authored_arc_with_exact_preview_trace(tmp_path):
    passphrase = "normal sealed acceptance passphrase"
    message = seal_message(
        passphrase, message_id="letter-welcome", date="2026-09-22",
        label="Welcome", body="The garden is yours to tend.",
    )
    timeline = _authored_arc(message.id)
    program = compile_timeline(
        timeline,
        known_letter_ids={message.id},
        known_asset_ids={
            "plant.rose", "collectible.pressed_flower", "fixture.bench",
        },
    )
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        author_name="Synthetic acceptance author",
        passphrase_hint="synthetic acceptance phrase",
        garden_seed=20260721,
        messages=[message],
        garden_gifts=[],
        garden_program=seal_garden_program(passphrase, _mapping(program)),
    )
    seal_bundle(bundle, passphrase)
    assert bundle.hmac and bundle.checksum
    path = tmp_path / "normal-production-v2.lateletter"
    write_bundle(bundle, path)

    loaded = read_bundle(path)
    assert verify_checksum(loaded)
    assert verify_bundle_hmac(loaded, passphrase)
    assert loaded.garden_program is not None
    runtime_program = parse_program(open_garden_program(passphrase, loaded.garden_program))
    assert canonical_json_bytes(_mapping(runtime_program)) == canonical_json_bytes(_mapping(program))

    state: dict = {"applied_occurrences": [], "variables": {}}
    contexts = [
        {"seed": loaded.garden_seed, "facts": {
            "letter.read": [message.id], "visit.total": 1,
            "animal.arrived": [], "animal.bond_tier": 0, "season.current": "summer",
        }},
        {"seed": loaded.garden_seed, "facts": {
            "letter.read": [message.id], "visit.total": 3,
            "animal.arrived": ["rabbit-clover"], "animal.bond_tier": 1,
            "season.current": "summer",
        }},
        {"seed": loaded.garden_seed, "facts": {
            "letter.read": [message.id], "visit.total": 4,
            "animal.arrived": ["rabbit-clover"], "animal.bond_tier": 3,
            "season.current": "autumn",
        }},
    ]
    applied = []
    for context in contexts:
        preview = preview_timeline(
            timeline, state, context,
            known_letter_ids={message.id},
            known_asset_ids={
                "plant.rose", "collectible.pressed_flower", "fixture.bench",
            },
        )
        runtime = evaluate_program(runtime_program, state, context)
        assert preview == runtime
        state = runtime.state
        applied.extend(row["event_id"] for row in runtime.trace if row["status"] == "applied")

    assert applied == [
        "letter-opens-garden", "third-revisit-growth", "bonded-autumn-gift",
    ]
    assert state["entities"]["rabbit-clover"]["present"] is True
    assert state["entities"]["memory-rose"]["stage"] == 2
    assert state["entities"]["autumn-keepsake"]["revealed"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_one_hundred_topology_hashes_and_stable_ids_match_browser_runtime():
    completed = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER)], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    browser = json.loads(completed.stdout)
    python = []
    for seed in range(100):
        world = generate_initial_world(
            f"acceptance:{seed}", seed, world_width=64, world_height=40,
        )
        early = project_scene(replace(world, effective_time=0))
        late = project_scene(replace(world, effective_time=1_000_000))
        early_hashes = {
            item.object_id: item.semantic_state["topology_hash"]
            for item in early.objects if item.kind == "plant"
        }
        late_hashes = {
            item.object_id: item.semantic_state["topology_hash"]
            for item in late.objects if item.kind == "plant"
        }
        plants = []
        for plant in sorted(world.plants, key=lambda item: item.plant_id):
            early_ids = {
                node.node_id for node in plant.topology if node.birth_time <= 0
            }
            late_ids = {
                node.node_id for node in plant.topology if node.birth_time <= 1_000_000
            }
            assert early_ids <= late_ids
            plants.append({
                "plant_id": plant.plant_id,
                "node_ids": sorted(node.node_id for node in plant.topology),
                "early_hash": early_hashes[plant.plant_id],
                "late_hash": late_hashes[plant.plant_id],
            })
        python.append({"seed": seed, "plants": plants})
    assert browser == python


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_authored_program_materializes_byte_identical_world_and_trace_cross_runtime():
    world = new_world("materialization-audit", 4242, world_width=64, world_height=40)
    program = parse_program({
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1", "author_timezone": "UTC",
        "variables": {},
        "entities": [{
            "id": "authored-bench", "kind": "fixture", "catalog_id": "bench",
            "initial_state": {"revealed": False},
        }, {
            "id": "authored-keepsake", "kind": "item", "catalog_id": "seed_packet",
            "initial_state": {"revealed": False},
        }],
        "animals": [{
            "id": "authored-rabbit", "species": "rabbit", "name": "Juniper",
            "personality": {"curiosity": 72}, "routine": "edge patrol",
            "favorite_places": ["authored-bench"], "prohibited_behaviors": [],
        }],
        "events": [{
            "id": "bench-memory", "conditions": {
                "all": [
                    {"fact": "visit.total", "op": ">=", "value": 2},
                    {"fact": "season.current", "op": "==", "value": "autumn"},
                ],
            },
            "schedule": None, "occurrence": "once", "priority": 1,
            "exclusive_group": None, "cooldown": None,
            "actions": [
                {"type": "entity.reveal", "target": "authored-bench",
                 "params": {"position": "near_tallest_tree"}},
                {"type": "entity.reveal", "target": "authored-keepsake",
                 "params": {"position": "near_bench", "state": "Synthetic seeds."}},
                {"type": "animal.arrive", "target": "authored-rabbit",
                 "params": {"position": "by_edge", "routine": "edge patrol"}},
                {"type": "narrative.show", "target": None,
                 "params": {"kind": "memory", "label": "The bench",
                            "text": "A synthetic authored memory."}},
            ],
        }],
    })
    facts = {"visit.total": 2, "season.current": "autumn"}
    python_result = apply_program(world, program, facts=facts)
    payload = {
        "world": world.to_dict(),
        "program": _mapping(program),
        "evaluation": {
            "state": python_result.evaluation.state,
            "effects": list(python_result.evaluation.effects),
            "trace": list(python_result.evaluation.trace),
        },
    }
    completed = subprocess.run(
        [shutil.which("node") or "node", str(NODE_RUNNER), "--materialize"],
        cwd=ROOT, input=json.dumps(payload), check=True,
        capture_output=True, text=True,
    )
    browser = json.loads(completed.stdout)
    python_world = json.loads(python_result.world.canonical_bytes())
    assert browser["world"] == python_world
    assert browser["world"]["event_trace"] == python_world["event_trace"]
    assert browser["receipts"] == list(python_result.effect_receipts)


def test_one_thousand_layouts_are_safe_and_all_connected_masks_resolve():
    for seed in range(1_000):
        world = generate_initial_world(
            f"release-layout:{seed}", seed, world_width=64, world_height=40,
        )
        assert layout_is_safe(world), seed
        object_ids = [
            *(item.plant_id for item in world.plants),
            *(item.fixture_id for item in world.fixtures),
            *(item.animal_id for item in world.animals),
            *(item.collectible_id for item in world.collectibles),
        ]
        assert len(object_ids) == len(set(object_ids))
    assert {
        connected_tile_key(group, mask)
        for group in CONNECTED_GROUPS for mask in range(16)
    } == {
        f"{group}:{mask:02x}"
        for group in CONNECTED_GROUPS for mask in range(16)
    }


def test_four_species_personality_hysteresis_and_all_absence_windows_are_humane():
    world = generate_initial_world("absence-audit", 42, world_width=64, world_height=40)
    assert set(ANIMAL_SPECIES) == {"bird", "cat", "rabbit", "turtle"}
    assert len({definition.repertoire for definition in ANIMAL_SPECIES.values()}) == 4
    for animal in world.animals:
        preferred = replace(animal, authored_preferences=(ANIMAL_SPECIES[animal.species_id].repertoire[0],))
        decision = decide_animal(preferred, AnimalContext(100), world.seed)
        assert decision.intent in ANIMAL_SPECIES[animal.species_id].repertoire
        for tier in range(4):
            bonded = replace(animal, bond_tier=tier)
            focused = decide_animal(
                bonded, AnimalContext(100, recipient_focus_id=animal.animal_id),
                world.seed,
            )
            if tier >= 1:
                assert focused.intent == "greet"
                assert focused.priority_reason == "relationship_response"
        tired = decide_animal(
            replace(animal, energy=10), AnimalContext(100), world.seed,
        )
        assert tired.intent == "rest" and tired.priority_reason == "safety_or_interruption"

    baseline = replace(world, last_observed_wall_time=1_000)
    for days in (1, 7, 30, 365):
        returned, report = reconcile_offline(baseline, 1_000 + days * DAY)
        assert report.elapsed_seconds == days * DAY
        assert [animal.bond_points for animal in returned.animals] == [
            animal.bond_points for animal in baseline.animals
        ]
        assert [animal.recent_memories for animal in returned.animals] == [
            animal.recent_memories for animal in baseline.animals
        ]
        assert returned.inventory == baseline.inventory
        assert [item.collected for item in returned.collectibles] == [
            item.collected for item in baseline.collectibles
        ]
        assert all("sorry" not in text.lower() and "neglect" not in text.lower()
                   for text in report.summaries)


def test_temporal_order_idempotency_dst_missed_year_catchup_and_rollback():
    rule = parse_schedule({
        "start": "2026-03-08T02:30:00", "timezone": "America/New_York",
        "recurrence": {"frequency": "daily", "count": 3,
                       "dst_gap": "shift_forward", "dst_fold": "first"},
        "exceptions": [], "missed": "summarize_then_current",
    })
    now = datetime(2026, 3, 10, 12, tzinfo=timezone.utc)
    result = expand_schedule(
        rule, event_id="dst-audit",
        last_seen_utc=now - timedelta(days=365), now_utc=now,
    )
    assert len(result.occurrences) == 1
    assert result.summarized_missed == 2
    rollback = expand_schedule(
        rule, event_id="dst-audit", last_seen_utc=now,
        now_utc=now - timedelta(seconds=1),
    )
    assert rollback.rollback_detected and not rollback.occurrences

    program = parse_program({
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1", "author_timezone": "UTC",
        "variables": {"order": 0}, "entities": [], "animals": [],
        "events": [
            {"id": event_id, "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
             "schedule": None, "occurrence": "once", "priority": priority,
             "exclusive_group": None, "cooldown": None,
             "actions": [{"type": "variable.increment", "target": None,
                          "params": {"name": "order", "amount": amount}}]}
            for event_id, priority, amount in (("later", 1, 1), ("first", 2, 10))
        ],
    })
    first = evaluate_program(program, {}, {"facts": {"visit.total": 1}})
    second = evaluate_program(program, first.state, {"facts": {"visit.total": 1}})
    assert [row["event_id"] for row in first.trace] == ["first", "later"]
    assert first.state["variables"]["order"] == 11
    assert second.state == first.state
    assert all(row["reason"] == "already_applied" for row in second.trace)


def test_replay_camera_pan_and_hit_testing_are_deterministic_but_not_a_p95_claim():
    initial = generate_initial_world("replay-audit", 81, world_width=64, world_height=40)
    commands = [
        command(initial.world_id, index, "pan", args={"dx": 1, "dy": index % 2})
        for index in range(1, 601)
    ]
    outcomes = []
    for _ in range(2):
        state = initial
        for value in commands:
            state, result = dispatch(state, value)
            assert result.accepted
        outcomes.append(state.canonical_bytes())
    assert outcomes[0] == outcomes[1]

    at_sixty = Camera(Point(0, 0), cells(80), cells(24))
    at_one_twenty = at_sixty
    for _ in range(60):
        at_sixty = at_sixty.pan(cells(2), cells(1))
    for _ in range(120):
        at_one_twenty = at_one_twenty.pan(cells(1), cells(1) // 2)
    assert at_sixty.center == at_one_twenty.center
    target = Rect(cells(121), cells(59), cells(2), cells(2))
    screen = at_sixty.world_to_screen(Point(cells(122), cells(60)))
    assert at_sixty.hit_test(screen, target)


def test_accessibility_static_contract_keeps_motion_controls_without_rejected_action_chrome():
    source = VIEWER.read_text(encoding="utf-8")
    required = {
        '@media (prefers-reduced-motion: reduce)',
        'id="garden-scene-summary"',
        'role="status" aria-live="polite"',
        'min-width: 44px; min-height: 44px',
        'data-garden-action="pause_motion"',
        'data-garden-action="open_journal"',
        'data-garden-action="undo"',
    }
    missing = sorted(value for value in required if value not in source)
    assert not missing

    # SPEC 7.8.3 leaves nonvisual secondary-action parity OPEN; it explicitly
    # forbids concealing that gap by painting the rejected list/sheet over the
    # Garden. Accessibility requirements cannot be used to revive that UI.
    forbidden = {
        'id="garden-object-list" aria-label="Garden objects"',
        'id="garden-action-sheet" role="group"',
        'id="garden-invitation"',
        'class="garden-opportunity"',
        'More actions',
    }
    returned = sorted(value for value in forbidden if value in source)
    assert not returned


def test_sky_audit_covers_twelve_trusted_privacy_safe_vectors():
    coarse = CoarseLocation.from_raw(35.681236, 139.767125)
    assert coarse.to_mapping() == {
        "latitude_cell": 36, "longitude_cell": 140, "grid_degrees": 1,
    }
    assert not {"latitude", "longitude", "raw_latitude", "raw_longitude"}.intersection(
        coarse.to_mapping()
    )
    denied = resolve_sky_mode("reader_live")
    assert denied.mode == "storybook_fallback" and denied.location is None

    payload = json.loads(ASTRONOMY_FIXTURES.read_text(encoding="utf-8"))
    assert payload["authority"]
    assert len(payload["vectors"]) == 12
    for vector in payload["vectors"]:
        altitude, azimuth = ra_dec_to_alt_az(
            when=datetime.fromisoformat(vector["timestamp"]),
            location=CoarseLocation(int(vector["latitude"]), int(vector["longitude"])),
            right_ascension_hours=vector["ra_hours"],
            declination_degrees=vector["dec_degrees"],
        )
        assert altitude == pytest.approx(vector["altitude_degrees"], abs=0.25)
        assert azimuth == pytest.approx(vector["azimuth_degrees"], abs=0.25)


def test_gate_status_matrix_never_converts_proxy_evidence_into_release_claims():
    audit = json.loads(GATE_MATRIX.read_text(encoding="utf-8"))
    rows = {row["gate"]: row for row in audit["gates"]}
    assert set(rows) == set(range(1, 15))
    assert rows[3]["status"] == rows[14]["status"] == "BLOCKED"
    assert all(row["status"] in {"PASS", "PARTIAL", "BLOCKED"} for row in rows.values())
    assert all(row["blocker"] for row in rows.values() if row["status"] != "PASS")
    assert all(not row["blocker"] for row in rows.values() if row["status"] == "PASS")
    assert all(row["automated_checks"] for row in rows.values() if row["status"] == "PASS")
    for row in rows.values():
        for selector in row["automated_checks"]:
            relative, function = selector.split("::", 1)
            source = (ROOT / relative).read_text(encoding="utf-8")
            assert f"def {function}(" in source


def test_the_gate_matrix_agrees_with_the_browser_e2e_defects():
    """The matrix must not claim what the executed review disproves.

    Its other tests check the matrix's internal shape, which a stale claim
    satisfies perfectly: gate 12 read "target sizing and narrow layout pass"
    while the browser E2E was recording that every target is 15x17 px and that
    two accepted fixtures are unreachable on mobile. Formatting checks cannot
    catch that, so this ties the prose to the tests that measure it.

    Deliberately a link check rather than a re-measurement. It asserts the gate
    cites the file that holds the evidence and does not assert the opposite of
    what that file records; measuring the product twice would just give the two
    places somewhere new to disagree.
    """
    matrix = json.loads(GATE_MATRIX.read_text(encoding="utf-8"))
    e2e = ROOT / "tests" / "test_garden_review_e2e_browser.py"
    assert e2e.exists(), "the browser E2E named by the gate matrix is missing"
    recorded = e2e.read_text(encoding="utf-8")

    # Each defect the E2E records as a strict expected failure, with the phrase
    # a gate must therefore not be claiming.
    for marker, forbidden_claim in (
        ("under the 44px floor", "target sizing"),
        ("no interaction rectangle", "narrow layout"),
    ):
        assert marker in recorded or "44px floor" in recorded, (
            f"the E2E no longer records {marker!r}; this check needs rewriting"
        )
        for gate in matrix["gates"]:
            blocker = gate.get("blocker", "")
            claims_pass = f"{forbidden_claim} and" in blocker or f"and {forbidden_claim}" in blocker
            if claims_pass:
                assert "DO NOT" in blocker or "do not" in blocker, (
                    f"gate {gate['gate']} claims {forbidden_claim!r} passes while "
                    "the browser E2E records it as a defect"
                )

    accessibility = next(g for g in matrix["gates"] if g["name"] == "Accessibility")
    parity = next(g for g in matrix["gates"] if g["name"] == "Input parity")
    for gate in (accessibility, parity):
        assert "tests/test_garden_review_e2e_browser.py" in gate["evidence"], (
            f"gate {gate['gate']} does not cite the browser review that measures it"
        )
        assert gate["status"] != "PASS", (
            f"gate {gate['gate']} is PASS while the browser review records defects in it"
        )
