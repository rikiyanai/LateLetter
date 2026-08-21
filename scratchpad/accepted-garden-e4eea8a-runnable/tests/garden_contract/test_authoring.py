from __future__ import annotations

import pytest

from lateletter.garden.authoring import (
    ActionCard, AuthoringValidationError, BeatCard, FatigueLimitReached,
    Timeline, When, compile_timeline, explain_trace, preview_timeline,
    validate_timeline, build_letter_rabbit_autumn_arc,
)


def _timeline() -> Timeline:
    timeline = Timeline("America/New_York", variables={"returns": 0}, session_beat_limit=2)
    timeline.entities.append({
        "id": "bench", "kind": "fixture", "asset_id": "fixture.bench",
        "initial_state": {"revealed": False},
    })
    timeline.add_beat(BeatCard(
        id="beat.return", title="The bench waits for you", track="fixtures",
        when=When.every(
            When.fact("visit.total", ">=", 3),
            When.never(When.fact("letter.read", "contains", reference="letter.future")),
        ),
        actions=(ActionCard.reveal("bench"), ActionCard.increment("returns")),
        priority=10,
    ))
    return timeline


def test_fatigue_limit_pauses_beat_authoring_without_losing_timeline():
    timeline = _timeline()
    timeline.add_beat(BeatCard(
        id="beat.second", title="A second gentle beat", track="revisit",
        when=When.fact("visit.total", ">=", 5),
        actions=(ActionCard.set_variable("returns", 2),),
    ))
    assert timeline.pause_recommended
    with pytest.raises(FatigueLimitReached):
        timeline.add_beat(BeatCard(
            id="beat.too-much", title="Too much for one sitting", track="revisit",
            when=When.fact("visit.total", ">=", 7),
            actions=(ActionCard.set_variable("returns", 3),),
        ))
    timeline.begin_session()
    assert not timeline.pause_recommended
    assert len(timeline.beats) == 2


def test_preview_uses_exact_evaluator_and_explains_trace():
    timeline = _timeline()
    result = preview_timeline(
        timeline, {"variables": {"returns": 0}, "applied_occurrences": []},
        {"seed": 10, "facts": {"visit.total": 3, "letter.read": []}},
        known_letter_ids={"letter.future"}, known_asset_ids={"fixture.bench"},
    )
    assert result.state["variables"]["returns"] == 1
    assert result.state["entities"]["bench"]["revealed"] is True
    assert explain_trace(result) == ("beat.return: eligible; applied 2 action(s).",)


def test_validation_blocks_missing_refs_cycles_exclusivity_and_recurrence():
    timeline = _timeline()
    timeline.begin_session()
    timeline.add_beat(BeatCard(
        id="beat.cycle-a", title="Cycle A", track="revisit",
        when=When.fact("event.completed", "contains", reference="beat.cycle-b"),
        actions=(ActionCard.complete("beat.cycle-a"),),
        exclusive_group="same", priority=4,
        schedule={
            "start": "2026-01-01T09:00:00", "timezone": "UTC",
            "recurrence": {"frequency": "daily"}, "exceptions": [],
            "missed": "deliver_on_next_visit",
        },
    ))
    timeline.begin_session()
    timeline.add_beat(BeatCard(
        id="beat.cycle-b", title="Cycle B", track="revisit",
        when=When.fact("event.completed", "contains", reference="beat.cycle-a"),
        actions=(ActionCard.reveal("missing-object"),),
        exclusive_group="same", priority=4,
    ))
    issues = validate_timeline(timeline, known_letter_ids={"letter.future"})
    codes = {issue.code for issue in issues}
    assert {"dependency_cycle", "missing_target", "ambiguous_exclusivity", "invalid_schedule"} <= codes
    with pytest.raises(AuthoringValidationError):
        compile_timeline(timeline, known_letter_ids={"letter.future"})


def test_validation_blocks_contradictions_and_private_plaintext_leaks():
    timeline = Timeline("UTC")
    timeline.add_beat(BeatCard(
        id="beat.secret", title="For the quiet anniversary", track="gifts",
        when=When.every(
            When.fact("visit.total", "==", 1),
            When.fact("visit.total", "==", 2),
        ),
        actions=(ActionCard.show_memory("The blue cup was always yours."),),
    ))
    issues = validate_timeline(
        timeline,
        plaintext_envelope={"debug_label": "The blue cup was always yours."},
    )
    assert {issue.code for issue in issues} == {"unreachable", "private_string_exposed"}


def test_compile_blocks_unknown_species_and_missing_action_parameters_before_seal():
    timeline = Timeline("UTC")
    timeline.animals.append({
        "id": "animal.chloe", "species": "dragon", "name": "Impossible",
        "personality": "mysterious", "initial_state": {"present": False},
    })
    timeline.add_beat(BeatCard(
        id="beat.invalid", title="Invalid runtime beat", track="animals",
        when=When.fact("visit.total", ">=", 1),
        actions=(
            ActionCard("animal.arrive", "animal.chloe", {}),
            ActionCard("animal.behave", "animal.chloe", {}),
        ),
    ))
    with pytest.raises(AuthoringValidationError) as exc:
        compile_timeline(timeline)
    messages = " ".join(issue.message for issue in exc.value.issues)
    assert "unknown runtime animal species" in messages
    assert "requires behavior" in messages


def test_narrative_ethics_blocks_coercion_but_allows_compassionate_prose():
    unsafe = Timeline("UTC")
    unsafe.beats.append(BeatCard(
        id="guilt", title="If you really love me", track="revisit",
        when=When.fact("visit.total", ">=", 1),
        actions=(ActionCard.show_memory("Act now; this expires today."),),
    ))
    issues = validate_timeline(unsafe)
    assert [issue.code for issue in issues].count("prohibited_narrative") == 2
    with pytest.raises(AuthoringValidationError, match="dark-pattern"):
        compile_timeline(unsafe)

    gentle = Timeline("UTC")
    gentle.beats.append(BeatCard(
        id="gentle", title="A place that waits", track="revisit",
        when=When.fact("visit.total", ">=", 1),
        actions=(ActionCard.show_memory(
            "I miss you. Take all the time you need; there is no need to hurry.",
        ),),
    ))
    assert not [issue for issue in validate_timeline(gentle)
                if issue.code == "prohibited_narrative"]
    assert compile_timeline(gentle).events[0].id == "gentle"


def test_guided_arc_compiles_and_preview_reaches_exact_acceptance_story():
    timeline = build_letter_rabbit_autumn_arc(
        recipient_name="Chloe", letter_id="letter.chloe", rabbit_name="Clover",
    )
    program = compile_timeline(
        timeline,
        known_letter_ids={"letter.chloe"},
        known_asset_ids={"collectible.seed_packet"},
    )
    result = preview_timeline(
        timeline, {}, {"facts": {
            "letter.read": ["letter.chloe"], "visit.total": 3,
            "animal.bond_tier": 3, "season.current": "autumn",
        }},
        known_letter_ids={"letter.chloe"},
        known_asset_ids={"collectible.seed_packet"},
    )
    assert [event.id for event in program.events] == [
        "arc.rabbit-arrives", "arc.third-visit-rose", "arc.bonded-autumn-gift",
    ]
    assert [row["event_id"] for row in result.trace if row["status"] == "applied"] == [
        "arc.rabbit-arrives", "arc.third-visit-rose", "arc.bonded-autumn-gift",
    ]
    assert result.state["entities"]["arc.rabbit"]["present"] is True
    assert result.state["entities"]["arc.autumn-rose"]["planted"] is True
    assert result.state["entities"]["arc.autumn-gift"]["revealed"] is True
