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


def test_a_world_from_a_newer_build_is_reported_rather_than_downgraded(tmp_path, world):
    """A future document may hold fields this build does not understand.

    Loading it by ignoring them would silently discard whatever they meant, so
    the store refuses instead. This replaces the older
    ``test_unsupported_schema_is_reported``, which asserted that EVERY
    non-current schema was refused -- true before there was a migration, and
    now only true in this one direction.
    """
    path = tmp_path / "world.json"
    data = world.to_dict()
    data["schema_version"] = 999
    import json
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(WorldPersistenceError, match="newer build"):
        WorldStore(path).load()


def test_an_older_shape_with_no_registered_transform_is_refused(tmp_path, world):
    """Renumbering a document is not migrating it.

    Schema 1 is the only shape this project has ever written, so there is no
    transform to run and nothing honest to do with a document claiming an older
    one. An earlier draft "migrated" such a document by assigning it the current
    number, which proves only that a number can be reassigned.
    """
    import json

    from lateletter.garden.world.model import WORLD_SCHEMA_VERSION

    path = tmp_path / "world.json"
    data = world.to_dict()
    data["schema_version"] = WORLD_SCHEMA_VERSION - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(WorldPersistenceError, match="no migration is registered"):
        WorldStore(path).load()


def test_the_store_reports_how_a_world_arrived(tmp_path, world):
    """Being loaded is an event; no field inside the document can record it.

    A caller needing a freshly generated world -- a visual review above all --
    has to be able to tell, and reading it off the state is impossible because
    a stored world's stamps can be perfectly current.
    """
    from lateletter.garden.world.provenance import LOAD_STORED, characterize_world

    path = tmp_path / "world.json"
    store = WorldStore(path)
    store.save(world)

    loaded, origin = store.load_with_origin()
    assert origin == LOAD_STORED
    assert loaded == world
    assert characterize_world(loaded).schema_version == world.schema_version
