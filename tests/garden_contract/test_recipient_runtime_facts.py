from dataclasses import replace
from datetime import date, datetime, timezone

from lateletter.garden.program import parse_program
from lateletter.garden.terminal import TerminalWorldSession
from lateletter.recipient import _apply_program_to_session


def _program(condition):
    return parse_program({
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {"fired": False},
        "entities": [], "animals": [],
        "events": [{
            "id": "runtime.fact", "conditions": condition, "schedule": None,
            "occurrence": "once", "priority": 0, "exclusive_group": None,
            "cooldown": None, "actions": [{
                "type": "variable.set", "target": None,
                "params": {"name": "fired", "value": True},
            }],
        }],
    })


def test_terminal_program_uses_real_monotonic_session_duration():
    session = TerminalWorldSession.preview(
        width=80, height=24, observed_wall_time=100,
    )
    _apply_program_to_session(
        session,
        _program({"fact": "session.duration_seconds", "op": ">=", "value": 30}),
        today=date(1999, 1, 1), read_ids=set(), session_duration_seconds=30,
    )
    assert session.world.program_state["variables"]["fired"] is True


def test_terminal_program_date_comes_from_observed_clock_not_stale_ui_date():
    session = TerminalWorldSession.preview(
        width=80, height=24, observed_wall_time=100,
    )
    observed = int(datetime(2030, 1, 2, 0, 1, tzinfo=timezone.utc).timestamp())
    session.world = replace(session.world, last_observed_wall_time=observed)
    _apply_program_to_session(
        session,
        _program({"fact": "date.range", "op": "==", "value": "2030-01-02"}),
        today=date(2030, 1, 1), read_ids=set(), session_duration_seconds=1,
    )
    assert session.world.program_state["variables"]["fired"] is True
