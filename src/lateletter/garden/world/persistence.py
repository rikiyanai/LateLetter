"""Atomic persistence for canonical Garden world snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import WorldState
from .provenance import load_migrated_world


class WorldPersistenceError(RuntimeError):
    pass


class WorldStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> WorldState:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            # Migrate the DOCUMENT before constructing the state.
            # ``WorldState.from_dict`` refuses any schema but the current one,
            # so a migration applied afterwards could never run: by then the
            # load has already succeeded or already thrown. Going through
            # ``load_migrated_world`` is what makes the migration reachable
            # from storage at all, and it stamps nothing about the world's
            # CONTENT -- an older world stays an older world, and reports
            # itself as migrated rather than fresh.
            return load_migrated_world(raw)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise WorldPersistenceError(f"could not load Garden world: {exc}") from exc

    def save(self, state: WorldState) -> None:
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        payload = state.canonical_bytes()
        try:
            with open(
                temporary,
                "wb",
                opener=lambda path, flags: os.open(path, flags, 0o600),
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            try:
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise WorldPersistenceError(f"could not save Garden world: {exc}") from exc
