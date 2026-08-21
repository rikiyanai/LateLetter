from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from lateletter.garden.schedule import (
    MAX_CATCH_UP_DAYS, ScheduleValidationError, expand_schedule, parse_schedule,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_dst_gap_and_fold_conformance_vectors():
    payload = json.loads((FIXTURES / "schedule_conformance.v1.json").read_text())
    for vector in payload["vectors"]:
        rule = parse_schedule(vector["schedule"])
        result = expand_schedule(
            rule, event_id="event.dst",
            last_seen_utc=datetime.fromisoformat(vector["last_seen_utc"]),
            now_utc=datetime.fromisoformat(vector["now_utc"]),
        )
        assert len(result.occurrences) == 1, vector["name"]
        assert result.occurrences[0].scheduled_utc == datetime.fromisoformat(
            vector["expected_occurrence_utc"]
        )


def test_count_until_and_exceptions_bound_recurrence():
    count_rule = parse_schedule({
        "start": "2026-01-01T09:00:00", "timezone": "UTC",
        "recurrence": {"frequency": "daily", "count": 5},
        "exceptions": ["2026-01-03"], "missed": "summarize_then_current",
    })
    result = expand_schedule(
        count_rule, event_id="event.count",
        last_seen_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        now_utc=datetime(2026, 1, 6, tzinfo=timezone.utc),
    )
    assert result.summarized_missed == 3
    assert result.occurrences[0].scheduled_utc == datetime(
        2026, 1, 5, 9, tzinfo=timezone.utc,
    )

    until_rule = parse_schedule({
        "start": "2026-01-01T09:00:00", "timezone": "UTC",
        "recurrence": {"frequency": "daily", "until": "2026-01-03T09:00:00"},
        "exceptions": [], "missed": "summarize_then_current",
    })
    until = expand_schedule(
        until_rule, event_id="event.until",
        last_seen_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        now_utc=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    assert until.summarized_missed == 2
    assert until.occurrences[0].scheduled_utc.day == 3


def test_accidental_unbounded_recurrence_is_rejected():
    with pytest.raises(ScheduleValidationError) as exc:
        parse_schedule({
            "start": "2026-01-01T09:00:00", "timezone": "UTC",
            "recurrence": {"frequency": "daily"},
            "exceptions": [], "missed": "skip",
        })
    assert any("intentional_unbounded" in error for error in exc.value.errors)


def test_missed_policies_and_year_catchup_are_bounded():
    base = {
        "start": "2020-01-01T09:00:00", "timezone": "UTC",
        "recurrence": {"frequency": "daily", "intentional_unbounded": True},
        "exceptions": [],
    }
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    last = datetime(2020, 1, 1, tzinfo=timezone.utc)
    delivery = expand_schedule(
        parse_schedule({**base, "missed": "deliver_on_next_visit"}),
        event_id="event.delivery", last_seen_utc=last, now_utc=now,
    )
    assert len(delivery.occurrences) == 1
    assert delivery.catch_up_truncated is True
    assert now - delivery.occurrences[0].scheduled_utc <= timedelta(days=1)
    assert now - max(last, now - timedelta(days=MAX_CATCH_UP_DAYS)) <= timedelta(days=MAX_CATCH_UP_DAYS)

    skipped = expand_schedule(
        parse_schedule({**base, "missed": "skip"}),
        event_id="event.skip", last_seen_utc=last, now_utc=now,
    )
    assert skipped.occurrences == ()
    assert skipped.skipped_missed > 0


def test_clock_rollback_emits_no_duplicate_occurrence():
    rule = parse_schedule({
        "start": "2026-01-01T09:00:00", "timezone": "UTC",
        "recurrence": None, "exceptions": [], "missed": "deliver_on_next_visit",
    })
    result = expand_schedule(
        rule, event_id="event.once",
        last_seen_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.rollback_detected is True
    assert result.occurrences == ()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
@pytest.mark.parametrize("schedule,last_seen,now", [
    ({
        "start": "2026-01-05T09:00:00", "timezone": "UTC",
        "recurrence": {"frequency": "weekly", "interval": 2, "count": 8,
                       "by_weekday": ["MO", "WE"]},
        "exceptions": [], "missed": "summarize_then_current",
    }, "2026-01-04T00:00:00+00:00", "2026-02-20T00:00:00+00:00"),
    ({
        "start": "2026-01-31T09:00:00", "timezone": "UTC",
        "recurrence": {"frequency": "monthly", "interval": 1, "count": 4},
        "exceptions": [], "missed": "summarize_then_current",
    }, "2026-01-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"),
])
def test_python_and_browser_weekly_month_end_schedules_conform(
    schedule, last_seen, now,
):
    result = expand_schedule(
        parse_schedule(schedule), event_id="event.conformance",
        last_seen_utc=datetime.fromisoformat(last_seen),
        now_utc=datetime.fromisoformat(now),
    )
    script = """
import { expandGardenSchedule } from './web/garden-program.mjs';
const [schedule, lastSeen, now] = JSON.parse(process.argv[1]);
const result = expandGardenSchedule(schedule, {
  event_id: 'event.conformance', last_seen_utc: lastSeen, now_utc: now,
});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script,
         json.dumps([schedule, last_seen, now])],
        cwd=Path(__file__).parents[2], check=True, capture_output=True, text=True,
    )
    browser = json.loads(completed.stdout)
    assert [item["id"] for item in browser["occurrences"]] == [
        item.id for item in result.occurrences
    ]
    assert browser["summarized_missed"] == result.summarized_missed
    assert browser["skipped_missed"] == result.skipped_missed
