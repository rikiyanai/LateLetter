from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world.clock import reconcile_offline


DAY = 86_400


def test_first_clock_observation_sets_watermark_without_progress(world):
    state, report = reconcile_offline(world, 1_000)
    assert state.last_observed_wall_time == 1_000
    assert state.effective_time == 0
    assert report.elapsed_seconds == 0


def test_clock_rollback_never_reverses_or_moves_watermark(world):
    started = replace(world, last_observed_wall_time=2_000, effective_time=500)
    state, report = reconcile_offline(started, 1_000)
    assert report.rollback_clamped
    assert report.elapsed_seconds == 0
    assert state == started


def test_seven_day_absence_is_aggregate_humane_and_bounded(world):
    animal = replace(
        world.animals[0],
        bond_points=21,
        bond_tier=2,
        session_interactions=("feed", "play"),
        energy=20,
    )
    started = replace(
        world,
        animals=(animal,),
        last_observed_wall_time=1_000,
        effective_time=0,
    )
    state, report = reconcile_offline(started, 1_000 + 7 * DAY)
    assert report.elapsed_seconds == 7 * DAY
    assert state.plants[0].growth_points == 7
    assert state.animals[0].bond_points == 21
    assert state.animals[0].bond_tier == 2
    assert state.animals[0].session_interactions == ()
    assert state.animals[0].energy == 50
    assert len(report.summaries) <= 3
    assert len(state.event_trace) == 1


def test_one_year_absence_does_not_replay_ticks_or_lose_progress(world):
    started = replace(world, last_observed_wall_time=10, effective_time=0)
    state, report = reconcile_offline(started, 10 + 365 * DAY)
    assert state.effective_time == 365 * DAY
    assert state.plants[0].growth_points == 365
    assert len(report.receipt_ids) <= len(world.plants) + 2
    assert len(report.summaries) <= 3


def test_same_wall_time_cannot_duplicate_offline_rewards(world):
    started = replace(world, last_observed_wall_time=100)
    once, first = reconcile_offline(started, 100 + DAY)
    twice, second = reconcile_offline(once, 100 + DAY)
    assert first.elapsed_seconds == DAY
    assert second.elapsed_seconds == 0
    assert twice == once
