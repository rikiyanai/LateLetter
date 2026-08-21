"""Recipient regressions for canonical Garden ownership."""

from __future__ import annotations

import curses
from dataclasses import replace
from datetime import date, timedelta

import pytest

from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    Bundle,
    GardenGift,
    Message,
    Trigger,
    create_dev_fixture,
    write_bundle,
)
from lateletter.garden.renderer import GardenRenderer, run_curses
from lateletter.garden.world.clock import reconcile_offline
from lateletter.garden.world.model import MILESTONE_RECEIPT_LIMIT, Vec2, WorldState
from lateletter.garden.program import parse_program
from lateletter.garden.world.generation import (
    REVIEW_PENDING_ANIMAL_SPECIES,
    REVIEW_PENDING_COLLECTIBLES,
    REVIEW_PENDING_PLANT_SPECIES,
    generate_initial_world,
)
from lateletter.garden.world.persistence import WorldStore
from lateletter.garden.terminal import (
    FULL_GARDEN_PARITY,
    TERMINAL_HELP_LINES,
    TERMINAL_WORLD_WIRED,
    TerminalWorldSession,
    handle_terminal_key,
)
from lateletter.recipient import (
    _compute_due,
    RecipientStore,
    _apply_legacy_gifts,
    _apply_open_program,
    _build_archive_rows,
    _unlock_content,
    _open_authenticated_program,
    _reapply_after_semantic_change,
    _sync_story_completion,
    _verify_passphrase,
    gift_catalog_entry,
    run_recipient,
    run_recipient_file,
)
from lateletter.sealed import (
    bundle_persistence_binding,
    seal_bundle,
    seal_garden_program,
    seal_gift_sentiment,
    seal_message,
)


@pytest.fixture()
def receipt_store(tmp_path, monkeypatch):
    monkeypatch.setattr("lateletter.recipient._RECIPIENT_DIR", tmp_path)
    monkeypatch.setattr("lateletter.recipient._RECEIPTS_FILE", tmp_path / "receipts.json")
    return RecipientStore("bundle-under-test")


def _session(tmp_path, *, visits: int = 0) -> TerminalWorldSession:
    """Open a session over a world that actually contains plants and animals.

    The tests below tend plants, feed animals and pick up collectibles, so an
    empty world would leave them nothing to act on -- and the default starter
    content is empty while its art waits for per-asset visual approval.

    The world is therefore built and persisted here FIRST, then opened. That is
    the ordinary restore path, not a test-only door: `TerminalWorldSession.open`
    loads whatever world already exists at `path`, so writing one there is how
    any caller supplies a specific world. `open` itself takes no content
    arguments, which keeps a test's staging needs out of the product surface.
    """
    world_path = tmp_path / "world.json"
    # Seed only on the FIRST call for this `tmp_path`. Several tests reopen the
    # same world to assert that a session persisted what it should have, and
    # rewriting a fresh world here would silently erase exactly the state those
    # assertions are checking for -- the seeding stands in for a world created
    # on an earlier run, not for one created on every open.
    if not world_path.exists():
        WorldStore(world_path).save(generate_initial_world(
            "bundle-under-test", 41,
            plant_species=REVIEW_PENDING_PLANT_SPECIES,
            animal_species=REVIEW_PENDING_ANIMAL_SPECIES,
            collectibles=REVIEW_PENDING_COLLECTIBLES,
        ))
    session = TerminalWorldSession.open(
        world_id="bundle-under-test",
        seed=41,
        width=80,
        height=24,
        path=world_path,
        observed_wall_time=1_000,
        record_visit=False,
    )
    for _ in range(visits):
        session.record_visit()
    return session


class _ScriptedScreen:
    """Minimal curses surface for recipient authentication regressions."""

    def __init__(self, keys: list[int]) -> None:
        self._keys = iter(keys)

    def timeout(self, _milliseconds: int) -> None:
        pass

    def getmaxyx(self) -> tuple[int, int]:
        return 24, 80

    def erase(self) -> None:
        pass

    def addstr(self, *_args) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        return next(self._keys)


class _CountingScreen(_ScriptedScreen):
    def __init__(self, keys: list[int]) -> None:
        super().__init__(keys)
        self.current_adds = 0
        self.frame_adds: list[int] = []

    def erase(self) -> None:
        self.current_adds = 0

    def addstr(self, *_args) -> None:
        self.current_adds += 1

    def refresh(self) -> None:
        self.frame_adds.append(self.current_adds)


def _auth_keys(passphrase: str) -> list[int]:
    return [ord("e"), *(ord(char) for char in passphrase), 10]


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


def test_unsigned_fixture_requires_explicit_trusted_fixture_path(tmp_path, capsys):
    bundle = create_dev_fixture(include_gifts=False)
    path = tmp_path / "unsigned.lateletter"
    write_bundle(bundle, path)

    with pytest.raises(SystemExit) as exc:
        run_recipient_file(path)
    assert exc.value.code == 1
    assert "explicit trusted development-fixture harness" in capsys.readouterr().out

    assert _verify_passphrase("anything", bundle, True)
    messages, gifts = _unlock_content("anything", bundle, True)
    assert messages[0][1].startswith("Dear Maya,")
    assert gifts == {}


def test_terminal_preview_is_generic_and_never_persists(tmp_path):
    protected = tmp_path / "authenticated-world.json"
    protected.write_bytes(b"existing authenticated world bytes")

    preview = TerminalWorldSession.preview(
        width=80,
        height=24,
        observed_wall_time=1_000,
    )
    assert preview.world.world_id == "recipient-preview"
    assert preview.world.animals == ()
    assert preview.store is None
    assert handle_terminal_key(preview, ord("o")).accepted
    assert protected.read_bytes() == b"existing authenticated world bytes"


def test_recipient_tolerates_terminal_without_cursor_visibility_control(
    monkeypatch, receipt_store,
):
    bundle = Bundle(bundle_id="bundle-under-test", garden_seed=41)
    seal_bundle(bundle, "correct")
    monkeypatch.setattr(
        "lateletter.recipient.curses.curs_set",
        lambda _value: (_ for _ in ()).throw(curses.error("unsupported")),
    )
    run_recipient(_ScriptedScreen([ord("q")]), bundle, receipt_store)


def test_standalone_tolerates_terminal_without_cursor_visibility_control(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "lateletter.garden.renderer.curses.curs_set",
        lambda _value: (_ for _ in ()).throw(curses.error("unsupported")),
    )
    run_curses(
        _ScriptedScreen([ord("q")]),
        world_path=tmp_path / "standalone-world.json",
        observed_wall_time=1_000,
    )


def test_recipient_full_repaints_identical_garden_after_external_erase(receipt_store):
    bundle = Bundle(bundle_id="bundle-under-test", garden_seed=41)
    screen = _CountingScreen([ord("z"), ord("q")])
    run_recipient(screen, bundle, receipt_store, observed_wall_time=1_000)
    assert len(screen.frame_adds) == 2
    assert screen.frame_adds[0] == screen.frame_adds[1]
    assert screen.frame_adds[0] > 3  # More than the three status rows.


def test_terminal_resume_discards_paused_wall_interval_during_continuous_input(
    monkeypatch,
):
    session = TerminalWorldSession.preview(
        width=80, height=24, observed_wall_time=1_000,
    )
    assert session.dispatch("pause_motion", args={"paused": True}).accepted
    paused_effective = session.world.effective_time
    monkeypatch.setattr("lateletter.garden.terminal.time.time", lambda: 9_000)
    assert session.dispatch("pause_motion", args={"paused": False}).accepted
    assert session.world.effective_time == paused_effective
    assert session.world.last_observed_wall_time == 9_000
    reopened, report = reconcile_offline(session.world, 9_000)
    assert report.elapsed_seconds == 0
    assert reopened.effective_time == paused_effective


def test_recipient_resume_resets_monotonic_live_baseline_under_continuous_keys(
    monkeypatch, receipt_store,
):
    session = TerminalWorldSession.preview(
        width=80, height=24, observed_wall_time=1_000,
    )
    monotonic_values = iter((100.0, 1_000.0, 1_001.0))
    monkeypatch.setattr(
        "lateletter.recipient.TerminalWorldSession.preview",
        lambda **_kwargs: session,
    )
    monkeypatch.setattr(
        "lateletter.recipient.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr("lateletter.garden.terminal.time.time", lambda: 9_000)
    run_recipient(
        _ScriptedScreen([ord(" "), ord("z"), ord(" "), -1, ord("q")]),
        Bundle(bundle_id="bundle-under-test", garden_seed=41),
        receipt_store,
        observed_wall_time=1_000,
    )
    assert session.world.effective_time == 1
    assert session.world.last_observed_wall_time == 9_001


def test_terminal_visit_receipts_are_bounded_with_restart_stable_total():
    session = TerminalWorldSession.preview(
        width=80, height=24, observed_wall_time=1_000,
    )
    for _ in range(700):
        session.record_visit()
    assert session.total_visits == 700
    assert len(session.world.milestone_receipts) == MILESTONE_RECEIPT_LIMIT
    assert session.world.milestone_receipts[0] == "terminal-visit:189"
    assert session.world.milestone_receipts[-1] == "terminal-visit:700"
    restarted = WorldState.from_dict(session.world.to_dict())
    session.world = restarted
    assert session.total_visits == 700


def test_same_public_bundle_id_cannot_share_receipts_or_default_world_path(
    tmp_path, monkeypatch,
):
    first = Bundle(bundle_id="same-public-id", garden_seed=41)
    second = Bundle(bundle_id="same-public-id", garden_seed=41)
    seal_bundle(first, "first secret")
    seal_bundle(second, "second secret")
    first_binding = bundle_persistence_binding(first, "first secret")
    second_binding = bundle_persistence_binding(second, "second secret")
    assert first_binding != second_binding

    monkeypatch.setattr("lateletter.recipient._RECIPIENT_DIR", tmp_path / "receipts")
    monkeypatch.setattr(
        "lateletter.recipient._RECEIPTS_FILE", tmp_path / "receipts" / "receipts.json",
    )
    first_store = RecipientStore(f"bundle:{first.bundle_id}:{first_binding}")
    second_store = RecipientStore(f"bundle:{second.bundle_id}:{second_binding}")
    first_store.mark_read("message-1")
    assert first_store.is_read("message-1")
    assert not second_store.is_read("message-1")

    world_dir = tmp_path / "worlds"
    monkeypatch.setattr("lateletter.garden.terminal._DEFAULT_WORLD_DIR", world_dir)
    first_session = TerminalWorldSession.open(
        world_id=f"bundle:{first.bundle_id}:{first_binding}", seed=41,
        width=80, height=24, observed_wall_time=1_000, record_visit=False,
    )
    second_session = TerminalWorldSession.open(
        world_id=f"bundle:{second.bundle_id}:{second_binding}", seed=41,
        width=80, height=24, observed_wall_time=1_000, record_visit=False,
    )
    assert first_session.store is not None and second_session.store is not None
    assert first_session.store.path.parent == world_dir
    assert second_session.store.path.parent == world_dir
    assert first_session.store.path != second_session.store.path
    assert first_session.store.path.name.endswith(".json")
    assert "/" not in first_session.store.path.name


def test_wrong_passphrase_does_not_read_write_or_visit_persistent_world(
    tmp_path, monkeypatch, receipt_store,
):
    passphrase = "correct"
    bundle = Bundle(bundle_id="bundle-under-test", garden_seed=41)
    seal_bundle(bundle, passphrase)
    world_path = tmp_path / "authenticated-world.json"
    original = b"not even valid world JSON; pre-auth must not read it"
    world_path.write_bytes(original)
    screen = _ScriptedScreen([
        *_auth_keys("wrong"),
        27,
        ord("q"),
    ])
    monkeypatch.setattr("lateletter.recipient.curses.curs_set", lambda _value: None)

    run_recipient(
        screen,
        bundle,
        receipt_store,
        world_path=world_path,
        observed_wall_time=1_000,
    )

    assert world_path.read_bytes() == original


def test_corrupted_launch_does_not_read_or_write_persistent_world(
    tmp_path, monkeypatch, receipt_store,
):
    bundle = Bundle(bundle_id="bundle-under-test", garden_seed=41)
    seal_bundle(bundle, "correct")
    world_path = tmp_path / "authenticated-world.json"
    original = b"corrupted launch must not parse this authenticated state"
    world_path.write_bytes(original)
    monkeypatch.setattr("lateletter.recipient.curses.curs_set", lambda _value: None)

    run_recipient(
        _ScriptedScreen([ord("q")]),
        bundle,
        receipt_store,
        corrupted=True,
        world_path=world_path,
        observed_wall_time=1_000,
    )

    assert world_path.read_bytes() == original


def test_correct_passphrase_atomically_restores_persistent_world(
    tmp_path, monkeypatch, receipt_store,
):
    passphrase = "correct"
    bundle = Bundle(bundle_id="bundle-under-test", garden_seed=41)
    seal_bundle(bundle, passphrase)
    persistence_id = (
        f"bundle:{bundle.bundle_id}:"
        f"{bundle_persistence_binding(bundle, passphrase)}"
    )
    world_path = tmp_path / "authenticated-world.json"
    existing = TerminalWorldSession.open(
        world_id=persistence_id,
        seed=bundle.garden_seed,
        width=80,
        height=24,
        path=world_path,
        observed_wall_time=1_000,
        record_visit=False,
    )
    prior = existing.dispatch("pan", args={"dx": 1})
    assert prior.accepted and prior.changed
    prior_trace_ids = {entry.trace_id for entry in existing.world.event_trace}
    screen = _ScriptedScreen([*_auth_keys(passphrase), ord("q")])
    monkeypatch.setattr("lateletter.recipient.curses.curs_set", lambda _value: None)

    run_recipient(
        screen,
        bundle,
        receipt_store,
        world_path=world_path,
        observed_wall_time=1_000,
    )

    reopened = TerminalWorldSession.open(
        world_id=persistence_id,
        seed=bundle.garden_seed,
        width=80,
        height=24,
        path=world_path,
        observed_wall_time=1_000,
        record_visit=False,
    )
    assert prior_trace_ids <= {entry.trace_id for entry in reopened.world.event_trace}
    assert reopened.total_visits == 1


def test_correct_passphrase_with_runtime_invalid_program_leaves_world_byte_identical(
    tmp_path, monkeypatch, receipt_store,
):
    passphrase = "correct"
    raw_program = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {},
        "entities": [{
            "id": "fixture.unsafe", "kind": "fixture", "catalog_id": "bench",
            "position": [999, 999], "initial_state": {"revealed": True},
        }],
        "animals": [], "events": [],
    }
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        bundle_id="bundle-under-test", garden_seed=41,
        garden_program=seal_garden_program(passphrase, raw_program),
    )
    seal_bundle(bundle, passphrase)
    world_path = tmp_path / "authenticated-world.json"
    existing = TerminalWorldSession.open(
        world_id=bundle.bundle_id, seed=bundle.garden_seed, width=80, height=24,
        path=world_path, observed_wall_time=1_000, record_visit=False,
    )
    existing.dispatch("pan", args={"dx": 1})
    before = world_path.read_bytes()
    monkeypatch.setattr("lateletter.recipient.curses.curs_set", lambda _value: None)

    run_recipient(
        _ScriptedScreen([*_auth_keys(passphrase), 27, ord("q")]),
        bundle,
        receipt_store,
        world_path=world_path,
        observed_wall_time=1_001,
    )

    assert world_path.read_bytes() == before


def test_recipient_binds_authenticated_program_letter_references_to_bundle():
    passphrase = "correct"
    raw_program = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {}, "entities": [], "animals": [],
        "events": [{
            "id": "present.missing",
            "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
            "schedule": None,
            "occurrence": "once", "priority": 0, "exclusive_group": None,
            "cooldown": None,
            "actions": [{
                "type": "letter.present", "target": None,
                "params": {"letter_id": "letter.missing"},
            }],
        }],
    }
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        messages=[Message(id="letter.real", date=date.today().isoformat())],
        garden_program=seal_garden_program(passphrase, raw_program),
    )

    with pytest.raises(ValueError, match="unknown bundle letter"):
        _open_authenticated_program(passphrase, bundle, {})


def test_recipient_store_owns_only_read_receipts(receipt_store):
    receipt_store.mark_read("letter.one")
    assert receipt_store.is_read("letter.one")
    assert receipt_store.read_set() == {"letter.one"}
    for stale_owner in ("record_visit", "feed_animal", "discover", "total_visits"):
        assert not hasattr(receipt_store, stale_owner)


def test_presented_future_letter_is_due_from_canonical_program_state():
    bundle = Bundle(messages=[Message(id="future", date="2099-01-01")])

    assert _compute_due(bundle, date(2026, 7, 21), set()) == []
    assert _compute_due(
        bundle,
        date(2026, 7, 21),
        set(),
        {"presented_letters": ["future"]},
    ) == [0]
    assert _compute_due(
        bundle,
        date(2026, 7, 21),
        {"future"},
        {"presented_letters": ["future"]},
    ) == []


def test_terminal_all_letters_read_persists_lasting_canonical_memorial(tmp_path):
    session = _session(tmp_path)
    bundle = Bundle(messages=[
        Message("letter.one", date.today().isoformat()),
        Message("letter.two", date.today().isoformat()),
    ])
    assert not _sync_story_completion(session, bundle, {"letter.one"})
    assert "story_complete" not in session.world.program_state

    assert _sync_story_completion(
        session, bundle, {"letter.one", "letter.two"},
    )
    assert session.world.program_state["story_complete"] is True
    memorial = session.world.program_state["memorial"]
    assert memorial == {
        "active": True,
        "completed_at": session.world.effective_time,
        "examined_gifts": [],
        "lasting": True,
    }
    assert session.projection().scene["memorial"] == memorial
    assert not _sync_story_completion(
        session, bundle, {"letter.one", "letter.two"},
    )

    reopened = _session(tmp_path)
    assert reopened.world.program_state["story_complete"] is True
    assert reopened.world.program_state["memorial"] == memorial
    assert reopened.projection().scene["memorial"] == memorial


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


def test_terminal_camera_center_and_dwell_use_canonical_living_world(tmp_path):
    session = _session(tmp_path)
    session.world = replace(
        session.world,
        ui=replace(session.world.ui, camera=Vec2(7, 9)),
    )
    assert session.center_world_position() == (7, 9)
    before = session.world.effective_time
    result = handle_terminal_key(session, ord("d"))
    assert result is not None and result.accepted and result.changed
    assert result.summary == "Dwelled for 30 Garden seconds."
    assert session.world.effective_time == before + 30
    assert any(entry.kind == "live_tick" for entry in session.world.event_trace)

    session.dispatch("pause_motion", args={"paused": True})
    paused = session.world.effective_time
    result = handle_terminal_key(session, ord("d"))
    assert result is not None and result.accepted and not result.changed
    assert result.summary == "The paused Garden stayed still."
    assert session.world.effective_time == paused


def test_terminal_controls_are_discoverable_and_flags_are_honest():
    help_text = " ".join(TERMINAL_HELP_LINES)
    for action in (
        "objects", "actions", "primary", "inspect", "tend", "feed", "play",
        "collect", "place", "move", "undo", "journal", "pan", "pause", "back",
        "dwell",
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
        program=program,
    )
    _apply_open_program(session, bundle, program, today=date.today(), read_ids=set())

    assert messages == [("For today", "Private letter")]
    assert any(item.collectible_id == "gift.key" for item in session.world.collectibles)
    assert session.world.animals == ()
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
