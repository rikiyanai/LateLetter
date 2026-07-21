"""Humane, rollback-safe, aggregate offline progress for Garden worlds."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .animals import AnimalContext, step_animals
from .model import AnimalState, PlantState, TraceEntry, WorldState, stable_id
from .plants import advance_topology


@dataclass(frozen=True)
class OfflineReport:
    elapsed_seconds: int
    rollback_clamped: bool
    summaries: tuple[str, ...]
    receipt_ids: tuple[str, ...]


def _grow_plant(plant: PlantState, start: int, end: int) -> tuple[PlantState, int]:
    if plant.dormant:
        return plant, 0
    period = max(1, plant.growth_period_seconds)
    milestones = max(0, end // period - start // period)
    if milestones == 0:
        return plant, 0
    grown = advance_topology(plant, end, milestones)
    return replace(grown, growth_points=plant.growth_points + milestones), milestones


def _safe_animal_baseline(animal: AnimalState) -> AnimalState:
    """Reset session-only pressure without touching bond or memories."""
    return replace(
        animal,
        session_interactions=(),
        energy=max(50, animal.energy),
        social_appetite=50,
        play_appetite=50,
        rest_appetite=40,
    )


def reconcile_offline(
    state: WorldState,
    observed_wall_time: int,
    *,
    max_summaries: int = 3,
) -> tuple[WorldState, OfflineReport]:
    """Advance effective time without replaying ticks.

    Work is O(plants + animals + collectibles), independent of the duration of
    the absence. Clock rollback preserves the previous watermark and produces
    zero elapsed time, so progress cannot reverse or later be counted twice.
    """
    observed = max(0, int(observed_wall_time))
    previous_wall = state.last_observed_wall_time
    if previous_wall is None:
        return (
            replace(state, last_observed_wall_time=observed),
            OfflineReport(0, False, (), ()),
        )

    if observed <= previous_wall:
        return (
            state,
            OfflineReport(0, observed < previous_wall, (), ()),
        )

    elapsed = observed - previous_wall
    start = state.effective_time
    end = start + elapsed

    grown: list[PlantState] = []
    plant_changes: list[tuple[str, int]] = []
    receipts: list[str] = []
    for plant in state.plants:
        updated, milestones = _grow_plant(plant, start, end)
        grown.append(updated)
        if milestones:
            plant_changes.append((plant.plant_id, milestones))
            receipts.append(stable_id("milestone", state.world_id, "plant-growth", plant.plant_id, start, end))

    animals = tuple(_safe_animal_baseline(animal) for animal in state.animals)
    if animals:
        receipts.append(stable_id("milestone", state.world_id, "animal-return", start, end))

    available = tuple(item for item in state.collectibles if not item.collected)
    if available:
        receipts.append(stable_id("milestone", state.world_id, "finds-waiting", start, end))

    summary_candidates: list[tuple[int, str, str]] = []
    for plant_id, count in plant_changes:
        summary_candidates.append((10, plant_id, f"A plant changed while you were away ({count} growth milestone{'s' if count != 1 else ''})."))
    for animal in animals:
        summary_candidates.append((20, animal.animal_id, f"Your {animal.species_id} is glad to see you."))
    if available:
        summary_candidates.append((30, available[0].collectible_id, f"{len(available)} garden find{'s are' if len(available) != 1 else ' is'} waiting to be noticed."))
    summaries = tuple(
        text for _, _, text in sorted(summary_candidates)[:max(0, max_summaries)]
    )

    new_receipts = tuple(sorted(set(state.milestone_receipts).union(receipts)))
    trace = TraceEntry(
        trace_id=stable_id("trace", state.world_id, "offline", start, end),
        sequence=state.command_sequence,
        kind="offline_reconcile",
        target_id=None,
        effective_time=end,
        summary=f"Reconciled {elapsed} seconds in aggregate.",
    )
    updated_state = replace(
        state,
        effective_time=end,
        last_observed_wall_time=observed,
        plants=tuple(grown),
        animals=animals,
        milestone_receipts=new_receipts,
        event_trace=state.event_trace + (trace,),
        program_state={
            **dict(state.program_state),
            "absence_summary": list(summaries),
            "absence_elapsed_seconds": elapsed,
        },
    )
    if updated_state.animals:
        scene = updated_state.program_state.get("scene", {})
        weather = str(scene.get("weather", "calm")) if isinstance(scene, dict) else "calm"
        hour = (end // 3_600) % 24
        updated_state, _ = step_animals(updated_state, AnimalContext(
            effective_time=end,
            time_of_day="night" if hour < 6 or hour >= 20 else "day",
            weather=weather,
            recipient_focus_id=updated_state.ui.focus_id,
            returning=True,
        ))
    return updated_state, OfflineReport(elapsed, False, summaries, tuple(receipts))
