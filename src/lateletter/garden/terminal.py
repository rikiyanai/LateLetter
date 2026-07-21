"""Canonical terminal Garden session, persistence, and semantic input routing."""

from __future__ import annotations

import curses
from dataclasses import dataclass, replace
from pathlib import Path
import time
from typing import Any, Mapping

from .input_adapters import InputEnvelope, InputModality, InputNormalizationError, normalize_input
from .state import TerminalViewport
from .world.clock import OfflineReport, reconcile_offline
from .world.engine import CommandResult, activate_memorial, dispatch
from .world.generation import generate_initial_world
from .world.model import WorldState
from .world.persistence import WorldPersistenceError, WorldStore
from .world.projection import SceneProjection, project_scene


TERMINAL_WORLD_WIRED = True
FULL_GARDEN_PARITY = False
_VISIT_PREFIX = "terminal-visit:"
_DEFAULT_WORLD_DIR = Path.home() / ".lateletter" / "recipient" / "worlds"


@dataclass
class TerminalWorldSession:
    world: WorldState
    store: WorldStore
    viewport: TerminalViewport
    offline_report: OfflineReport

    @classmethod
    def open(
        cls,
        *,
        world_id: str,
        seed: int | str,
        width: int,
        height: int,
        path: str | Path | None = None,
        observed_wall_time: int | None = None,
        record_visit: bool = True,
    ) -> TerminalWorldSession:
        world_path = Path(path) if path is not None else _DEFAULT_WORLD_DIR / f"{world_id}.json"
        store = WorldStore(world_path)
        if world_path.exists():
            world = store.load()
            if world.world_id != world_id:
                raise WorldPersistenceError("stored Garden world ID does not match requested world")
        else:
            world = generate_initial_world(world_id, seed)
        observed = int(time.time()) if observed_wall_time is None else int(observed_wall_time)
        world, report = reconcile_offline(world, observed)
        world = activate_memorial(world)
        session = cls(world, store, TerminalViewport(width, height), report)
        if record_visit:
            session.record_visit()
        else:
            session.save()
        return session

    @property
    def total_visits(self) -> int:
        return sum(1 for receipt in self.world.milestone_receipts if receipt.startswith(_VISIT_PREFIX))

    def record_visit(self) -> None:
        next_visit = self.total_visits + 1
        receipt = f"{_VISIT_PREFIX}{next_visit}"
        self.world = replace(
            self.world,
            milestone_receipts=tuple(sorted(set(self.world.milestone_receipts).union({receipt}))),
        )
        self.save()

    def save(self) -> None:
        self.store.save(self.world)

    def mark_story_complete(self, completed_at: int | None = None) -> bool:
        """Persist the same lasting canonical memorial as the browser runtime."""
        if self.world.program_state.get("story_complete") is True:
            return False
        program_state = dict(self.world.program_state)
        program_state["story_complete"] = True
        if completed_at is not None:
            program_state["memorial"] = {
                "active": True,
                "completed_at": int(completed_at),
                "examined_gifts": sorted(
                    entry.object_id for entry in self.world.journal
                    if entry.status == "examined"
                ),
                "lasting": True,
            }
        self.world = activate_memorial(replace(self.world, program_state=program_state))
        self.save()
        return True

    def resize(self, width: int, height: int) -> None:
        """Resize presentation only; canonical world bytes remain unchanged."""
        self.viewport.resize(width, height)

    def projection(self) -> SceneProjection:
        return project_scene(self.world)

    def dispatch(
        self,
        kind: str,
        *,
        target_id: str | None = None,
        args: Mapping[str, Any] | None = None,
    ) -> CommandResult:
        envelope = InputEnvelope(
            modality=InputModality.TERMINAL,
            world_id=self.world.world_id,
            sequence=self.world.command_sequence + 1,
            raw={
                "command": kind,
                "target_id": target_id,
                "args": dict(args or {}),
            },
        )
        try:
            garden_command = normalize_input(envelope)
        except InputNormalizationError as exc:
            return CommandResult(accepted=False, changed=False, reason=str(exc))
        updated, result = dispatch(self.world, garden_command)
        if result.accepted:
            self.world = updated
            if result.changed:
                self.save()
        return result

    def focused_id(self) -> str | None:
        return self.world.ui.focus_id

    def center_world_position(self) -> tuple[int, int]:
        x = min(
            self.world.world_width - 1,
            self.world.ui.camera.x + max(0, self.viewport.width // 2),
        )
        y = min(
            self.world.world_height - 1,
            self.world.ui.camera.y + max(0, (self.viewport.height - 4) // 2),
        )
        return x, y

    def focused_projection(self):
        focus = self.focused_id()
        return next((item for item in self.projection().objects if item.object_id == focus), None)

    def place_catalog(
        self,
        object_kind: str,
        catalog_id: str,
        x: int,
        y: int,
        *,
        rotation: int = 0,
    ) -> CommandResult:
        """Semantic terminal placement front door for every runtime catalog."""
        return self.dispatch("place", args={
            "object_kind": object_kind,
            "catalog_id": catalog_id,
            "x": int(x),
            "y": int(y),
            "rotation": int(rotation),
        })


TERMINAL_HELP_LINES = (
    "o objects · a actions · 1–9 choose action · enter primary · i inspect · w water/tend · x prune · f feed · p play · c collect",
    "t train · y transplant · s rest · n place copy · m move · v rotate · u undo · j journal · arrows pan · space pause · esc back · q quit",
)


def dispatch_terminal_action(
    session: TerminalWorldSession,
    action: str,
    *,
    target_id: str | None = None,
) -> CommandResult:
    """Translate a discoverable action label to one canonical command."""
    target = target_id or session.focused_id()
    item = next((row for row in session.projection().objects if row.object_id == target), None)
    if item is None:
        return CommandResult(False, False, "no action target")
    action = str(action)
    if action == "inspect":
        return session.dispatch("inspect", target_id=target)
    if item.kind == "plant" and action in {"observe", "water", "prune", "train", "rest"}:
        return session.dispatch("tend", target_id=target, args={"care_action": action})
    if item.kind == "plant" and action == "transplant":
        x, y = session.center_world_position()
        return session.dispatch("tend", target_id=target, args={"care_action": action, "x": x, "y": y})
    if item.kind == "fixture" and action in item.semantic_state.get("interaction_verbs", []):
        return session.dispatch("primary_interact", target_id=target, args={"fixture_action": action})
    if action == "move" or (item.kind == "plant" and action == "transplant"):
        x, y = session.center_world_position()
        return session.dispatch("move_fixture", target_id=target, args={"x": x, "y": y})
    if action == "rotate" and item.kind == "fixture":
        x, y = item.position.x, item.position.y
        rotation = int(item.semantic_state.get("rotation", 0)) + 90
        return session.dispatch("move_fixture", target_id=target, args={"x": x, "y": y, "rotation": rotation})
    if action in {"feed", "play", "collect", "open_journal"}:
        return session.dispatch(action, target_id=target)
    return CommandResult(False, False, f"unsupported action {action}")


def handle_terminal_key(session: TerminalWorldSession, key: int) -> CommandResult | None:
    focus = session.focused_id()
    if ord("1") <= key <= ord("9"):
        item = session.focused_projection()
        if item is None:
            return CommandResult(False, False, "no action target")
        index = key - ord("1")
        if index >= len(item.actions):
            return CommandResult(False, False, "action number is unavailable")
        return dispatch_terminal_action(session, item.actions[index], target_id=item.object_id)
    if key == ord("o"):
        return session.dispatch("move_focus", args={"direction": "next"})
    if key == ord("a"):
        return session.dispatch("open_actions", target_id=focus)
    if key in (10, 13):
        return session.dispatch("primary_interact", target_id=focus)
    if key == ord("i"):
        return session.dispatch("inspect", target_id=focus)
    if key == ord("w"):
        return session.dispatch("tend", target_id=focus, args={"care_action": "water"})
    if key == ord("x"):
        return session.dispatch("tend", target_id=focus, args={"care_action": "prune"})
    if key == ord("t"):
        return session.dispatch("tend", target_id=focus, args={"care_action": "train"})
    if key == ord("y"):
        x, y = session.center_world_position()
        return session.dispatch("tend", target_id=focus, args={"care_action": "transplant", "x": x, "y": y})
    if key == ord("s"):
        return session.dispatch("tend", target_id=focus, args={"care_action": "rest"})
    if key == ord("f"):
        return session.dispatch("feed", target_id=focus)
    if key == ord("p"):
        return session.dispatch("play", target_id=focus)
    if key == ord("c"):
        return session.dispatch("collect", target_id=focus)
    if key == ord("n"):
        item = session.focused_projection()
        if item is None or item.kind not in {"fixture", "plant"}:
            return CommandResult(False, False, "focus a plant or fixture to place another")
        x, y = session.center_world_position()
        catalog_id = str(item.semantic_state.get("catalog_id") or item.semantic_state.get("species_id"))
        return session.place_catalog(item.kind, catalog_id, x, y)
    if key == ord("m"):
        x, y = session.center_world_position()
        return session.dispatch("move_fixture", target_id=focus, args={"x": x, "y": y})
    if key == ord("v"):
        item = session.focused_projection()
        if item is None or item.kind != "fixture":
            return CommandResult(False, False, "rotate target is not a fixture")
        return session.dispatch("move_fixture", target_id=focus, args={
            "x": item.position.x,
            "y": item.position.y,
            "rotation": int(item.semantic_state.get("rotation", 0)) + 90,
        })
    if key == ord("u"):
        return session.dispatch("undo")
    if key == ord("j"):
        return session.dispatch("open_journal")
    if key == ord(" "):
        return session.dispatch("pause_motion")
    if key in (27, ord("b")):
        return session.dispatch("back")
    if key == curses.KEY_LEFT:
        return session.dispatch("pan", args={"dx": -1})
    if key == curses.KEY_RIGHT:
        return session.dispatch("pan", args={"dx": 1})
    if key == curses.KEY_UP:
        return session.dispatch("pan", args={"dy": -1})
    if key == curses.KEY_DOWN:
        return session.dispatch("pan", args={"dy": 1})
    return None
