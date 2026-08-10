"""Canonical terminal Garden session, persistence, and semantic input routing."""

from __future__ import annotations

import curses
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import time
from typing import Any, Mapping

from .input_adapters import InputEnvelope, InputModality, InputNormalizationError, normalize_input
from .materializer import seed_program_state
from .program import GardenProgram
from .state import TerminalViewport
from .world.clock import OfflineReport, reconcile_offline
from .world.engine import CommandResult, activate_memorial, advance_live_world, dispatch
from .world.generation import generate_initial_world, upgrade_untouched_legacy_starter
from .world.model import WorldState
from .world.model import MILESTONE_RECEIPT_LIMIT, compact_recent_strings
from .world.persistence import WorldPersistenceError, WorldStore
from .world.projection import SceneProjection, project_scene


TERMINAL_WORLD_WIRED = True
FULL_GARDEN_PARITY = False
_VISIT_PREFIX = "terminal-visit:"
_DEFAULT_WORLD_DIR = Path.home() / ".lateletter" / "recipient" / "worlds"


@dataclass
class TerminalWorldSession:
    world: WorldState
    store: WorldStore | None
    viewport: TerminalViewport
    offline_report: OfflineReport
    journal_offset: int = 0
    persistence_enabled: bool = True

    @classmethod
    def preview(
        cls,
        *,
        width: int,
        height: int,
        observed_wall_time: int | None = None,
    ) -> TerminalWorldSession:
        """Return a generic in-memory Garden that cannot touch recipient state.

        Recipient bundles use this session until their HMAC has authenticated.
        Its fixed identity and seed ensure that neither an encrypted program nor
        a previously decrypted persistent world can influence the pre-auth view.
        """
        observed = int(time.time()) if observed_wall_time is None else int(observed_wall_time)
        world = generate_initial_world(
            "recipient-preview",
            "lateletter-recipient-preview-v1",
        )
        # Pre-auth recipient space is not the standalone sandbox. Relationship
        # animals belong to the encrypted author program and remain absent
        # until authentication supplies that roster.
        world = replace(world, animals=())
        world, report = reconcile_offline(world, observed)
        return cls(world, None, TerminalViewport(width, height), report)

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
        defer_persistence: bool = False,
        program: GardenProgram | None = None,
    ) -> TerminalWorldSession:
        """Open or restore a persistent Garden session.

        Deliberately NOT a place to choose starter content. This session opens
        whatever world already exists at `path`, and generates a default one
        only when none does. Two content mechanisms already exist and cover the
        real cases: an author's `program` supplies the relationship-animal
        roster below, and any caller wanting a specific world can build it with
        `generate_initial_world` and persist it through `WorldStore` before
        opening. Adding a third, narrower content knob here would have served
        only the tests that use it, so it does not live on this surface.
        """
        # A world ID can contain author-controlled identifiers.  Persistence
        # filenames are fixed-length digests, never raw bundle IDs or paths.
        safe_name = hashlib.sha256(world_id.encode("utf-8")).hexdigest()
        world_path = Path(path) if path is not None else _DEFAULT_WORLD_DIR / f"{safe_name}.json"
        store = WorldStore(world_path)
        if world_path.exists():
            world = store.load()
            if world.world_id != world_id:
                raise WorldPersistenceError("stored Garden world ID does not match requested world")
            world = upgrade_untouched_legacy_starter(world, seed)
        else:
            world = generate_initial_world(world_id, seed)
        # The author program owns the complete relationship-animal roster.
        # Apply it before offline reconciliation so generic sandbox animals do
        # not create recipient-facing return receipts or absence summaries.
        if program is not None:
            world = seed_program_state(world, program)
        observed = int(time.time()) if observed_wall_time is None else int(observed_wall_time)
        world, report = reconcile_offline(world, observed)
        world = activate_memorial(world)
        session = cls(
            world,
            store,
            TerminalViewport(width, height),
            report,
            persistence_enabled=not defer_persistence,
        )
        if record_visit:
            session.record_visit()
        else:
            session.save()
        return session

    @property
    def total_visits(self) -> int:
        receipt_total = sum(
            1 for receipt in self.world.milestone_receipts
            if receipt.startswith(_VISIT_PREFIX)
        )
        persisted = self.world.program_state.get("visit_total")
        if isinstance(persisted, int) and not isinstance(persisted, bool):
            return max(0, persisted, receipt_total)
        return receipt_total

    def record_visit(self) -> None:
        next_visit = self.total_visits + 1
        receipt = f"{_VISIT_PREFIX}{next_visit}"
        prior_receipts = tuple(self.world.milestone_receipts)
        program_state = dict(self.world.program_state)
        program_state["visit_total"] = next_visit
        program_state["milestone_receipt_total"] = max(
            len(prior_receipts),
            int(program_state.get("milestone_receipt_total", 0)),
        ) + (0 if receipt in prior_receipts else 1)
        self.world = replace(
            self.world,
            milestone_receipts=compact_recent_strings(
                (*prior_receipts, receipt), MILESTONE_RECEIPT_LIMIT,
            ),
            program_state=program_state,
        )
        self.save()

    def save(self) -> None:
        if self.store is not None and self.persistence_enabled:
            self.store.save(self.world)

    def commit_persistence(self, *, enable: bool = True) -> None:
        """Write a deferred authenticated transaction exactly once."""
        if self.store is not None:
            self.store.save(self.world)
        self.persistence_enabled = bool(enable)

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
        self.journal_offset = min(self.journal_offset, self._max_journal_offset())

    def _journal_row_count(self) -> int:
        missed = self.world.program_state.get("missed_event_summaries", ())
        missed_count = len(missed) if isinstance(missed, (list, tuple)) else 0
        return (
            2
            + max(1, len(self.world.inventory))
            + max(1, len(self.world.journal))
            + (1 + min(3, missed_count) if missed_count else 0)
        )

    def _max_journal_offset(self) -> int:
        visible_rows = max(1, self.viewport.height - 6)
        return max(0, self._journal_row_count() - visible_rows)

    def scroll_journal(self, delta: int) -> CommandResult:
        previous = self.journal_offset
        self.journal_offset = min(
            self._max_journal_offset(), max(0, previous + int(delta)),
        )
        return CommandResult(
            accepted=True,
            changed=False,
            reason="",
            summary=(
                f"Journal row {self.journal_offset + 1}."
                if self.journal_offset != previous else "Journal edge reached."
            ),
        )

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
            if (
                kind == "pause_motion"
                and self.world.ui.motion_paused
                and not updated.ui.motion_paused
                and updated.last_observed_wall_time is not None
            ):
                # Discard wall time spent paused even when continuous key input
                # prevents the idle loop from advancing its live baseline.
                updated = replace(
                    updated,
                    last_observed_wall_time=max(
                        updated.last_observed_wall_time, int(time.time()),
                    ),
                )
            self.world = updated
            if result.changed:
                self.save()
        return result

    def focused_id(self) -> str | None:
        return self.world.ui.focus_id

    def center_world_position(self) -> tuple[int, int]:
        """Return the canonical world cell at the camera's screen center."""
        return self.world.ui.camera.x, self.world.ui.camera.y

    def dwell(self, seconds: int = 30) -> CommandResult:
        """Advance the deterministic living-world loop while the reader dwells."""
        prior_effective_time = self.world.effective_time
        updated = advance_live_world(self.world, max(0, int(seconds)))
        persistence_changed = updated.canonical_bytes() != self.world.canonical_bytes()
        changed = updated.effective_time != prior_effective_time
        self.world = updated
        if persistence_changed:
            self.save()
        message = (
            f"Dwelled for {max(0, int(seconds))} Garden seconds."
            if changed else "The paused Garden stayed still."
        )
        return CommandResult(
            accepted=True,
            changed=changed,
            reason="",
            summary=message,
        )

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
    "t train · y transplant · s rest · d dwell · n place copy · m move · v rotate · u undo · j journal · arrows pan · space pause · esc back · q quit",
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
    if session.world.ui.journal_open and key == curses.KEY_UP:
        return session.scroll_journal(-1)
    if session.world.ui.journal_open and key == curses.KEY_DOWN:
        return session.scroll_journal(1)
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
    if key == ord("d"):
        return session.dwell(30)
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
        if session.world.ui.journal_open:
            session.journal_offset = 0
            return session.dispatch("back")
        session.journal_offset = 0
        return session.dispatch("open_journal")
    if key == ord(" "):
        return session.dispatch("pause_motion")
    if key in (27, ord("b")):
        if session.world.ui.journal_open:
            session.journal_offset = 0
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
