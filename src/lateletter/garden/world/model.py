"""Versioned immutable data model for the internal Garden world core."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


WORLD_SCHEMA_VERSION = 1
ENGINE_VERSION = "garden-world-internal-v1"
PROCESSED_COMMAND_LIMIT = 512
EVENT_TRACE_LIMIT = 512
LIVE_TRACE_LIMIT = 120
UNDO_STACK_LIMIT = 128
MILESTONE_RECEIPT_LIMIT = 512


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonical_value(item) for item in value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes without relying on Python hash order."""
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def stable_id(namespace: str, *parts: Any) -> str:
    """Create a compact stable ID from explicit, canonically encoded inputs."""
    digest = hashlib.sha256(
        canonical_json_bytes([namespace, *parts])
    ).hexdigest()[:24]
    return f"{namespace}:{digest}"


def compact_recent_strings(values: Iterable[str], limit: int) -> tuple[str, ...]:
    """Keep a bounded insertion-ordered idempotency window.

    Sorting receipt IDs destroys recency and makes a bounded ledger unable to
    retain the entries most likely to be replayed.  Remove an older duplicate
    in favour of its newest occurrence, then retain the newest fixed window.
    """
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return ()
    recent: dict[str, None] = {}
    for value in values:
        item = str(value)
        recent.pop(item, None)
        recent[item] = None
    return tuple(recent)[-bounded_limit:]


@dataclass(frozen=True, order=True)
class Vec2:
    x: int
    y: int

    def to_list(self) -> list[int]:
        return [self.x, self.y]

    @classmethod
    def from_value(cls, value: Iterable[int]) -> Vec2:
        x, y = value
        return cls(int(x), int(y))


@dataclass(frozen=True)
class OrganNode:
    node_id: str
    parent_id: str | None
    kind: str
    birth_time: int
    maturity_time: int
    final_direction: Vec2
    final_length: int
    glyph_family: str
    bloom_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "birth_time": self.birth_time,
            "maturity_time": self.maturity_time,
            "final_direction": self.final_direction.to_list(),
            "final_length": self.final_length,
            "glyph_family": self.glyph_family,
            "bloom_state": self.bloom_state,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OrganNode:
        return cls(
            node_id=str(data["node_id"]),
            parent_id=(str(data["parent_id"]) if data.get("parent_id") else None),
            kind=str(data["kind"]),
            birth_time=int(data["birth_time"]),
            maturity_time=int(data["maturity_time"]),
            final_direction=Vec2.from_value(data["final_direction"]),
            final_length=int(data["final_length"]),
            glyph_family=str(data["glyph_family"]),
            bloom_state=(str(data["bloom_state"]) if data.get("bloom_state") else None),
        )


@dataclass(frozen=True)
class PlantState:
    plant_id: str
    species_id: str
    position: Vec2
    topology: tuple[OrganNode, ...] = ()
    growth_points: int = 0
    tended_count: int = 0
    last_tended_at: int | None = None
    growth_period_seconds: int = 86_400
    dormant: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plant_id": self.plant_id,
            "species_id": self.species_id,
            "position": self.position.to_list(),
            "topology": [node.to_dict() for node in sorted(self.topology, key=lambda n: n.node_id)],
            "growth_points": self.growth_points,
            "tended_count": self.tended_count,
            "last_tended_at": self.last_tended_at,
            "growth_period_seconds": self.growth_period_seconds,
            "dormant": self.dormant,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlantState:
        return cls(
            plant_id=str(data["plant_id"]),
            species_id=str(data["species_id"]),
            position=Vec2.from_value(data["position"]),
            topology=tuple(OrganNode.from_dict(item) for item in data.get("topology", [])),
            growth_points=int(data.get("growth_points", 0)),
            tended_count=int(data.get("tended_count", 0)),
            last_tended_at=(int(data["last_tended_at"]) if data.get("last_tended_at") is not None else None),
            growth_period_seconds=max(1, int(data.get("growth_period_seconds", 86_400))),
            dormant=bool(data.get("dormant", False)),
        )


@dataclass(frozen=True)
class FixtureState:
    fixture_id: str
    catalog_id: str
    position: Vec2
    rotation: int = 0
    authored: bool = False
    interaction_count: int = 0
    last_interaction: str | None = None
    authored_state: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "catalog_id": self.catalog_id,
            "position": self.position.to_list(),
            "rotation": self.rotation,
            "authored": self.authored,
            "interaction_count": self.interaction_count,
            "last_interaction": self.last_interaction,
            "authored_state": _canonical_value(self.authored_state),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FixtureState:
        return cls(
            fixture_id=str(data["fixture_id"]),
            catalog_id=str(data["catalog_id"]),
            position=Vec2.from_value(data["position"]),
            rotation=int(data.get("rotation", 0)) % 360,
            authored=bool(data.get("authored", False)),
            interaction_count=max(0, int(data.get("interaction_count", 0))),
            last_interaction=(str(data["last_interaction"]) if data.get("last_interaction") else None),
            authored_state=deepcopy(dict(data.get("authored_state", {}))),
        )


@dataclass(frozen=True)
class Personality:
    boldness: int = 50
    sociability: int = 50
    curiosity: int = 50
    playfulness: int = 50
    patience: int = 50
    routine_strength: int = 50
    food_motivation: int = 50
    day_preference: int = 50

    def to_dict(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name))
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Personality:
        return cls(**{
            name: max(0, min(100, int(data.get(name, 50))))
            for name in cls.__dataclass_fields__
        })


@dataclass(frozen=True)
class EpisodicMemory:
    memory_id: str
    kind: str
    target_id: str | None
    timestamp: int
    valence: int
    salience: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind,
            "target_id": self.target_id,
            "timestamp": self.timestamp,
            "valence": self.valence,
            "salience": self.salience,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EpisodicMemory:
        return cls(
            memory_id=str(data["memory_id"]),
            kind=str(data["kind"]),
            target_id=(str(data["target_id"]) if data.get("target_id") else None),
            timestamp=int(data["timestamp"]),
            valence=int(data.get("valence", 0)),
            salience=int(data.get("salience", 0)),
        )


@dataclass(frozen=True)
class AnimalState:
    animal_id: str
    species_id: str
    position: Vec2
    high_level_state: str = "awake"
    bond_points: int = 0
    bond_tier: int = 0
    interaction_counts: tuple[tuple[str, int], ...] = ()
    session_interactions: tuple[str, ...] = ()
    recent_memories: tuple[EpisodicMemory, ...] = ()
    personality: Personality = field(default_factory=Personality)
    energy: int = 60
    social_appetite: int = 50
    play_appetite: int = 50
    rest_appetite: int = 40
    choreography_lock: str | None = None
    current_intent: str = "idle"
    intent_started_at: int = 0
    minimum_dwell_until: int = 0
    decision_index: int = 0
    cooldowns: tuple[tuple[str, int], ...] = ()
    favorite_fixture_ids: tuple[str, ...] = ()
    authored_preferences: tuple[str, ...] = ()
    authored_prohibitions: tuple[str, ...] = ()
    display_name: str | None = None
    personality_note: str | None = None

    def interaction_count(self, kind: str) -> int:
        return dict(self.interaction_counts).get(kind, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "animal_id": self.animal_id,
            "species_id": self.species_id,
            "position": self.position.to_list(),
            "high_level_state": self.high_level_state,
            "bond_points": self.bond_points,
            "bond_tier": self.bond_tier,
            "interaction_counts": {key: value for key, value in sorted(self.interaction_counts)},
            "session_interactions": list(self.session_interactions),
            "recent_memories": [memory.to_dict() for memory in self.recent_memories],
            "personality": self.personality.to_dict(),
            "energy": self.energy,
            "social_appetite": self.social_appetite,
            "play_appetite": self.play_appetite,
            "rest_appetite": self.rest_appetite,
            "choreography_lock": self.choreography_lock,
            "current_intent": self.current_intent,
            "intent_started_at": self.intent_started_at,
            "minimum_dwell_until": self.minimum_dwell_until,
            "decision_index": self.decision_index,
            "cooldowns": {key: value for key, value in sorted(self.cooldowns)},
            "favorite_fixture_ids": sorted(set(self.favorite_fixture_ids)),
            "authored_preferences": sorted(set(self.authored_preferences)),
            "authored_prohibitions": sorted(set(self.authored_prohibitions)),
            "display_name": self.display_name,
            "personality_note": self.personality_note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AnimalState:
        counts = data.get("interaction_counts", {})
        cooldowns = data.get("cooldowns", {})
        return cls(
            animal_id=str(data["animal_id"]),
            species_id=str(data["species_id"]),
            position=Vec2.from_value(data["position"]),
            high_level_state=str(data.get("high_level_state", "awake")),
            bond_points=max(0, int(data.get("bond_points", 0))),
            bond_tier=max(0, min(3, int(data.get("bond_tier", 0)))),
            interaction_counts=tuple(sorted((str(key), int(value)) for key, value in counts.items())),
            session_interactions=tuple(str(item) for item in data.get("session_interactions", [])),
            recent_memories=tuple(EpisodicMemory.from_dict(item) for item in data.get("recent_memories", [])),
            personality=Personality.from_dict(data.get("personality", {})),
            energy=max(0, min(100, int(data.get("energy", 60)))),
            social_appetite=max(0, min(100, int(data.get("social_appetite", 50)))),
            play_appetite=max(0, min(100, int(data.get("play_appetite", 50)))),
            rest_appetite=max(0, min(100, int(data.get("rest_appetite", 40)))),
            choreography_lock=(str(data["choreography_lock"]) if data.get("choreography_lock") else None),
            current_intent=str(data.get("current_intent", "idle")),
            intent_started_at=max(0, int(data.get("intent_started_at", 0))),
            minimum_dwell_until=max(0, int(data.get("minimum_dwell_until", 0))),
            decision_index=max(0, int(data.get("decision_index", 0))),
            cooldowns=tuple(sorted((str(key), int(value)) for key, value in cooldowns.items())),
            favorite_fixture_ids=tuple(str(item) for item in data.get("favorite_fixture_ids", [])),
            authored_preferences=tuple(str(item) for item in data.get("authored_preferences", [])),
            authored_prohibitions=tuple(str(item) for item in data.get("authored_prohibitions", [])),
            display_name=(str(data["display_name"]) if data.get("display_name") else None),
            personality_note=(str(data["personality_note"]) if data.get("personality_note") else None),
        )


@dataclass(frozen=True)
class CollectibleState:
    collectible_id: str
    family: str
    provenance: str
    label: str
    description: str
    position: Vec2
    collected: bool = False
    authored: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "collectible_id": self.collectible_id,
            "family": self.family,
            "provenance": self.provenance,
            "label": self.label,
            "description": self.description,
            "position": self.position.to_list(),
            "collected": self.collected,
            "authored": self.authored,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CollectibleState:
        return cls(
            collectible_id=str(data["collectible_id"]),
            family=str(data["family"]),
            provenance=str(data["provenance"]),
            label=str(data["label"]),
            description=str(data["description"]),
            position=Vec2.from_value(data["position"]),
            collected=bool(data.get("collected", False)),
            authored=bool(data.get("authored", False)),
        )


@dataclass(frozen=True)
class JournalEntry:
    entry_id: str
    object_id: str
    status: str
    label: str
    description: str
    discovered_at: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "object_id": self.object_id,
            "status": self.status,
            "label": self.label,
            "description": self.description,
            "discovered_at": self.discovered_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JournalEntry:
        return cls(
            entry_id=str(data["entry_id"]),
            object_id=str(data["object_id"]),
            status=str(data["status"]),
            label=str(data["label"]),
            description=str(data["description"]),
            discovered_at=int(data["discovered_at"]),
        )


@dataclass(frozen=True)
class UIState:
    focus_id: str | None = None
    camera: Vec2 = field(default_factory=lambda: Vec2(0, 0))
    actions_open_for: str | None = None
    journal_open: bool = False
    motion_paused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "focus_id": self.focus_id,
            "camera": self.camera.to_list(),
            "actions_open_for": self.actions_open_for,
            "journal_open": self.journal_open,
            "motion_paused": self.motion_paused,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UIState:
        return cls(
            focus_id=(str(data["focus_id"]) if data.get("focus_id") else None),
            camera=Vec2.from_value(data.get("camera", [0, 0])),
            actions_open_for=(str(data["actions_open_for"]) if data.get("actions_open_for") else None),
            journal_open=bool(data.get("journal_open", False)),
            motion_paused=bool(data.get("motion_paused", False)),
        )


@dataclass(frozen=True)
class UndoRecord:
    kind: str
    object_id: str
    previous_position: Vec2 | None
    previous_rotation: int | None
    created: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "object_id": self.object_id,
            "previous_position": self.previous_position.to_list() if self.previous_position else None,
            "previous_rotation": self.previous_rotation,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UndoRecord:
        return cls(
            kind=str(data["kind"]),
            object_id=str(data["object_id"]),
            previous_position=(Vec2.from_value(data["previous_position"]) if data.get("previous_position") else None),
            previous_rotation=(int(data["previous_rotation"]) if data.get("previous_rotation") is not None else None),
            created=bool(data.get("created", False)),
        )


@dataclass(frozen=True)
class TraceEntry:
    trace_id: str
    sequence: int
    kind: str
    target_id: str | None
    effective_time: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "target_id": self.target_id,
            "effective_time": self.effective_time,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceEntry:
        return cls(
            trace_id=str(data["trace_id"]),
            sequence=int(data["sequence"]),
            kind=str(data["kind"]),
            target_id=(str(data["target_id"]) if data.get("target_id") else None),
            effective_time=int(data["effective_time"]),
            summary=str(data["summary"]),
        )


def compact_event_trace(entries: Iterable[TraceEntry]) -> tuple[TraceEntry, ...]:
    """Bound diagnostics while retaining the newest command/program history."""
    values = tuple(entries)
    live_indexes = [
        index for index, entry in enumerate(values) if entry.kind == "live_tick"
    ]
    discarded = set(live_indexes[:-LIVE_TRACE_LIMIT])
    bounded_live = tuple(
        entry for index, entry in enumerate(values) if index not in discarded
    )
    return bounded_live[-EVENT_TRACE_LIMIT:]


@dataclass(frozen=True)
class WorldState:
    world_id: str
    seed: str
    schema_version: int = WORLD_SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    world_width: int = 120
    world_height: int = 80
    effective_time: int = 0
    last_observed_wall_time: int | None = None
    command_sequence: int = 0
    plants: tuple[PlantState, ...] = ()
    fixtures: tuple[FixtureState, ...] = ()
    animals: tuple[AnimalState, ...] = ()
    collectibles: tuple[CollectibleState, ...] = ()
    inventory: tuple[str, ...] = ()
    journal: tuple[JournalEntry, ...] = ()
    ui: UIState = field(default_factory=UIState)
    undo_stack: tuple[UndoRecord, ...] = ()
    milestone_receipts: tuple[str, ...] = ()
    program_state: Mapping[str, Any] = field(default_factory=dict)
    processed_commands: tuple[str, ...] = ()
    event_trace: tuple[TraceEntry, ...] = ()

    def object_ids(self) -> tuple[str, ...]:
        return tuple(sorted(
            [plant.plant_id for plant in self.plants]
            + [fixture.fixture_id for fixture in self.fixtures]
            + [animal.animal_id for animal in self.animals]
            + [item.collectible_id for item in self.collectibles if not item.collected]
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "world_id": self.world_id,
            "seed": self.seed,
            "world_width": self.world_width,
            "world_height": self.world_height,
            "effective_time": self.effective_time,
            "last_observed_wall_time": self.last_observed_wall_time,
            "command_sequence": self.command_sequence,
            "plants": [item.to_dict() for item in sorted(self.plants, key=lambda x: x.plant_id)],
            "fixtures": [item.to_dict() for item in sorted(self.fixtures, key=lambda x: x.fixture_id)],
            "animals": [item.to_dict() for item in sorted(self.animals, key=lambda x: x.animal_id)],
            "collectibles": [item.to_dict() for item in sorted(self.collectibles, key=lambda x: x.collectible_id)],
            "inventory": sorted(set(self.inventory)),
            "journal": [item.to_dict() for item in sorted(self.journal, key=lambda x: x.entry_id)],
            "ui": self.ui.to_dict(),
            "undo_stack": [item.to_dict() for item in self.undo_stack],
            "milestone_receipts": list(compact_recent_strings(
                self.milestone_receipts, MILESTONE_RECEIPT_LIMIT,
            )),
            "program_state": _canonical_value(self.program_state),
            "processed_commands": list(self.processed_commands),
            "event_trace": [item.to_dict() for item in self.event_trace],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldState:
        version = int(data.get("schema_version", 0))
        if version != WORLD_SCHEMA_VERSION:
            raise ValueError(f"unsupported Garden world schema {version}")
        return cls(
            schema_version=version,
            engine_version=str(data.get("engine_version", ENGINE_VERSION)),
            world_id=str(data["world_id"]),
            seed=str(data["seed"]),
            world_width=max(1, int(data.get("world_width", 120))),
            world_height=max(1, int(data.get("world_height", 80))),
            effective_time=max(0, int(data.get("effective_time", 0))),
            last_observed_wall_time=(int(data["last_observed_wall_time"]) if data.get("last_observed_wall_time") is not None else None),
            command_sequence=max(0, int(data.get("command_sequence", 0))),
            plants=tuple(PlantState.from_dict(item) for item in data.get("plants", [])),
            fixtures=tuple(FixtureState.from_dict(item) for item in data.get("fixtures", [])),
            animals=tuple(AnimalState.from_dict(item) for item in data.get("animals", [])),
            collectibles=tuple(CollectibleState.from_dict(item) for item in data.get("collectibles", [])),
            inventory=tuple(str(item) for item in data.get("inventory", [])),
            journal=tuple(JournalEntry.from_dict(item) for item in data.get("journal", [])),
            ui=UIState.from_dict(data.get("ui", {})),
            undo_stack=tuple(
                UndoRecord.from_dict(item) for item in data.get("undo_stack", [])
            )[-UNDO_STACK_LIMIT:],
            milestone_receipts=compact_recent_strings(
                (str(item) for item in data.get("milestone_receipts", [])),
                MILESTONE_RECEIPT_LIMIT,
            ),
            program_state=deepcopy(dict(data.get("program_state", {}))),
            processed_commands=tuple(
                str(item) for item in data.get("processed_commands", [])
            )[-PROCESSED_COMMAND_LIMIT:],
            event_trace=compact_event_trace(
                TraceEntry.from_dict(item) for item in data.get("event_trace", [])
            ),
        )


def new_world(
    world_id: str,
    seed: int | str | bytes,
    *,
    world_width: int = 120,
    world_height: int = 80,
) -> WorldState:
    seed_digest = hashlib.sha256(canonical_json_bytes(["world-seed", str(seed)])).hexdigest()
    return WorldState(
        world_id=world_id,
        seed=seed_digest,
        world_width=max(1, world_width),
        world_height=max(1, world_height),
    )
