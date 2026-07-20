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
from .world.engine import CommandResult, dispatch
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


TERMINAL_HELP_LINES = (
    "o objects · a actions · enter primary · i inspect · t tend · f feed · p play · c collect",
    "n place · m move · u undo · j journal · arrows pan · space pause · esc back · q quit",
)


def handle_terminal_key(session: TerminalWorldSession, key: int) -> CommandResult | None:
    focus = session.focused_id()
    if key == ord("o"):
        return session.dispatch("move_focus", args={"direction": "next"})
    if key == ord("a"):
        return session.dispatch("open_actions", target_id=focus)
    if key in (10, 13):
        return session.dispatch("primary_interact", target_id=focus)
    if key == ord("i"):
        return session.dispatch("inspect", target_id=focus)
    if key == ord("t"):
        return session.dispatch("tend", target_id=focus, args={"care_action": "water"})
    if key == ord("f"):
        return session.dispatch("feed", target_id=focus)
    if key == ord("p"):
        return session.dispatch("play", target_id=focus)
    if key == ord("c"):
        return session.dispatch("collect", target_id=focus)
    if key == ord("n"):
        x, y = session.center_world_position()
        return session.dispatch(
            "place",
            args={"object_kind": "fixture", "catalog_id": "bench", "x": x, "y": y},
        )
    if key == ord("m"):
        x, y = session.center_world_position()
        return session.dispatch("move_fixture", target_id=focus, args={"x": x, "y": y})
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
