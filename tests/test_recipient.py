"""Recipient regressions for canonical Garden ownership."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from lateletter.bundle import BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, GardenGift, Trigger
from lateletter.garden.renderer import GardenRenderer
from lateletter.garden.program import parse_program
from lateletter.garden.terminal import (
    FULL_GARDEN_PARITY,
    TERMINAL_HELP_LINES,
    TERMINAL_WORLD_WIRED,
    TerminalWorldSession,
    handle_terminal_key,
)
from lateletter.recipient import (
    RecipientStore,
    _apply_legacy_gifts,
    _apply_open_program,
    _build_archive_rows,
    _unlock_content,
    _open_authenticated_program,
    _reapply_after_semantic_change,
    _verify_passphrase,
    gift_catalog_entry,
)
from lateletter.sealed import seal_bundle, seal_garden_program, seal_gift_sentiment, seal_message


@pytest.fixture()
def receipt_store(tmp_path, monkeypatch):
    monkeypatch.setattr("lateletter.recipient._RECIPIENT_DIR", tmp_path)
    monkeypatch.setattr("lateletter.recipient._RECEIPTS_FILE", tmp_path / "receipts.json")
    return RecipientStore("bundle-under-test")


def _session(tmp_path, *, visits: int = 0) -> TerminalWorldSession:
    session = TerminalWorldSession.open(
        world_id="bundle-under-test",
        seed=41,
        width=80,
        height=24,
        path=tmp_path / "world.json",
        observed_wall_time=1_000,
        record_visit=False,
    )
    for _ in range(visits):
        session.record_visit()
    return session


def _gift(gift_id: str, gift_type: str, catalog_id: str, trigger_type: str, value: str):
    return GardenGift(
        id=gift_id,
        type=gift_type,
        catalog_id=catalog_id,
        trigger=Trigger(type=trigger_type, value=value),
    )


def test_real_sealed_bundle_unlocks_exact_message_and_gift():
    passphrase = "correct horse"
    message = seal_message(
        passphrase,
        message_id="m1",
        date=date.today().isoformat(),
        label="Open today",
        body="The real terminal letter.",
    )
    gift = _gift("g1", "item", "coffee_mug", "date", date.today().isoformat())
    seal_gift_sentiment(passphrase, gift, "Two sugars, always.")
    bundle = Bundle(messages=[message], garden_gifts=[gift])
    seal_bundle(bundle, passphrase)

    assert _verify_passphrase(passphrase, bundle, False)
    assert not _verify_passphrase("wrong", bundle, False)
    assert _unlock_content(passphrase, bundle, False) == (
        [("Open today", "The real terminal letter.")],
        {"g1": "Two sugars, always."},
    )


def test_recipient_store_owns_only_read_receipts(receipt_store):
    receipt_store.mark_read("letter.one")
    assert receipt_store.is_read("letter.one")
    assert receipt_store.read_set() == {"letter.one"}
    for stale_owner in ("record_visit", "feed_animal", "discover", "total_visits"):
        assert not hasattr(receipt_store, stale_owner)


def test_archive_uses_canonical_eligibility_receipts():
    gifts = [
        _gift("mug", "item", "coffee_mug", "cumulative_visits", "1"),
        _gift("cat", "animal", "cat", "cumulative_visits", "2"),
    ]
    rows = _build_archive_rows(Bundle(garden_gifts=gifts), {"mug"})
    assert [row[1] for row in rows if row[0] == "gift"] == ["mug"]
    rows = _build_archive_rows(Bundle(garden_gifts=gifts), set(), post_complete=True)
    assert [row[1] for row in rows if row[0] == "gift"] == ["mug", "cat"]


def test_authored_animal_name_is_preserved():
    gift = _gift("cat", "animal", "cat", "cumulative_visits", "1")
    gift.animal_name = "Miso"
    assert gift_catalog_entry(gift)[0] == "Miso"


def test_legacy_gifts_materialize_once_into_canonical_world(tmp_path):
    session = _session(tmp_path, visits=1)
    bundle = Bundle(garden_gifts=[
        _gift("mug", "item", "coffee_mug", "cumulative_visits", "1"),
        _gift("rabbit", "animal", "rabbit", "cumulative_visits", "1"),
        _gift("rose", "plant", "rosebush", "cumulative_visits", "1"),
    ])

    eligible = _apply_legacy_gifts(
        session, bundle, {"mug": "Memory"}, date.today(), set()
    )
    first_ids = session.world.object_ids()
    assert eligible == {"mug", "rabbit", "rose"}
    assert {"legacy-entity.mug", "legacy-entity.rabbit", "legacy-entity.rose"} <= set(first_ids)

    _apply_legacy_gifts(session, bundle, {"mug": "Memory"}, date.today(), set())
    assert session.world.object_ids() == first_ids
    reopened = _session(tmp_path)
    assert reopened.world.object_ids() == first_ids


def test_post_letter_and_completion_release_use_migration_evaluator(tmp_path):
    session = _session(tmp_path)
    letter = seal_message(
        "pw", message_id="last", date=date.today().isoformat(), label="Last", body="Body"
    )
    gift = _gift("keepsake", "item", "old_key", "post_letter", "last")
    future = _gift(
        "future", "item", "book", "date", (date.today() + timedelta(days=100)).isoformat()
    )
    bundle = Bundle(messages=[letter], garden_gifts=[gift, future])

    assert _apply_legacy_gifts(session, bundle, {}, date.today(), set()) == set()
    assert _apply_legacy_gifts(session, bundle, {}, date.today(), {"last"}) == {
        "keepsake", "future"
    }


def test_terminal_session_is_canonical_persistent_owner_and_resize_is_presentation_only(tmp_path):
    session = _session(tmp_path)
    before = session.world.canonical_bytes()
    session.resize(132, 43)
    assert session.world.canonical_bytes() == before

    result = handle_terminal_key(session, ord("o"))
    assert result is not None and result.accepted
    result = handle_terminal_key(session, ord("i"))
    assert result is not None and result.accepted
    trace = session.world.event_trace
    assert trace

    reopened = _session(tmp_path)
    assert reopened.world.event_trace == trace
    rendered_before = reopened.world.canonical_bytes()
    assert GardenRenderer(52, 16).render_lines(reopened.world)
    assert reopened.world.canonical_bytes() == rendered_before


def test_terminal_rejects_missing_target_and_has_no_random_reset(tmp_path):
    session = _session(tmp_path)
    result = session.dispatch("inspect")
    assert not result.accepted
    assert "target_id" in result.reason
    assert handle_terminal_key(session, ord("r")) is None


def test_terminal_controls_are_discoverable_and_flags_are_honest():
    help_text = " ".join(TERMINAL_HELP_LINES)
    for action in (
        "objects", "actions", "primary", "inspect", "tend", "feed", "play",
        "collect", "place", "move", "undo", "journal", "pan", "pause", "back",
    ):
        assert action in help_text
    assert TERMINAL_WORLD_WIRED is True
    assert FULL_GARDEN_PARITY is False


def test_normal_sealed_v2_bundle_opens_and_materializes_program(tmp_path):
    passphrase = "normal production passphrase"
    raw_program = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {},
        "entities": [{"id": "gift.key", "kind": "item", "catalog_id": "old_key"}],
        "animals": [],
        "events": [{
            "id": "sealed-welcome",
            "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
            "schedule": None,
            "occurrence": "once", "priority": 0, "exclusive_group": None,
            "cooldown": None,
            "actions": [
                {"type": "entity.reveal", "target": "gift.key", "params": {"state": "For you"}},
                {"type": "narrative.show", "target": None,
                 "params": {"kind": "memory", "label": "Sealed memory", "text": "Private text"}},
            ],
        }],
    }
    message = seal_message(
        passphrase, message_id="letter.one", date=date.today().isoformat(),
        label="For today", body="Private letter",
    )
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        bundle_id="sealed-v2", garden_seed=99, messages=[message],
        garden_program=seal_garden_program(passphrase, raw_program),
    )
    seal_bundle(bundle, passphrase)

    assert _verify_passphrase(passphrase, bundle, False)
    messages, gifts = _unlock_content(passphrase, bundle, False)
    program = _open_authenticated_program(passphrase, bundle, gifts)
    session = TerminalWorldSession.open(
        world_id=bundle.bundle_id, seed=bundle.garden_seed, width=80, height=24,
        path=tmp_path / "sealed-v2.json", observed_wall_time=1_000,
    )
    _apply_open_program(session, bundle, program, today=date.today(), read_ids=set())

    assert messages == [("For today", "Private letter")]
    assert any(item.collectible_id == "gift.key" for item in session.world.collectibles)
    assert any(entry.label == "Sealed memory" for entry in session.world.journal)
    assert session.world.program_state["applied_occurrences"]
    before = session.world.canonical_bytes()
    _apply_open_program(session, bundle, program, today=date.today(), read_ids=set())
    assert session.world.canonical_bytes() == before


def test_changed_semantic_command_re_evaluates_program_in_session(tmp_path):
    session = _session(tmp_path)
    program = parse_program({
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {}, "entities": [], "animals": [],
        "events": [{
            "id": "after-tending",
            "conditions": {"fact": "plant.growth_stage", "op": ">=", "value": 1},
            "schedule": None, "occurrence": "once", "priority": 0,
            "exclusive_group": None, "cooldown": None,
            "actions": [{
                "type": "narrative.show", "target": None,
                "params": {"kind": "memory", "label": "Care remembered", "text": "It grew."},
            }],
        }],
    })
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        bundle_id="bundle-under-test",
    )
    _apply_open_program(session, bundle, program, today=date.today(), read_ids=set())
    assert not any(entry.label == "Care remembered" for entry in session.world.journal)

    result = session.dispatch(
        "tend", target_id=session.world.plants[0].plant_id,
        args={"care_action": "water"},
    )
    assert result.accepted and result.changed
    _reapply_after_semantic_change(
        session, bundle, program, result, today=date.today(), read_ids=set(),
    )
    assert any(entry.label == "Care remembered" for entry in session.world.journal)
