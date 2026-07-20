from __future__ import annotations

import os

import pytest

from lateletter.garden.world.persistence import WorldPersistenceError, WorldStore


def test_atomic_round_trip_uses_canonical_bytes_and_private_mode(tmp_path, world):
    path = tmp_path / "recipient" / "world.json"
    store = WorldStore(path)
    store.save(world)
    assert path.read_bytes() == world.canonical_bytes()
    assert store.load() == world
    assert not path.with_name(".world.json.tmp").exists()
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_corrupt_snapshot_is_reported_not_silently_reset(tmp_path):
    path = tmp_path / "world.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorldPersistenceError, match="could not load"):
        WorldStore(path).load()


def test_unsupported_schema_is_reported(tmp_path, world):
    path = tmp_path / "world.json"
    data = world.to_dict()
    data["schema_version"] = 999
    import json
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(WorldPersistenceError, match="unsupported Garden world schema"):
        WorldStore(path).load()
