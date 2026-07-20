"""Atomic persistence for canonical Garden world snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import WorldState


class WorldPersistenceError(RuntimeError):
    pass


class WorldStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> WorldState:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            return WorldState.from_dict(raw)
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
