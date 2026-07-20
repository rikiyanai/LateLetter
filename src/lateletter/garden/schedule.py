"""Constrained, deterministic schedule expansion for garden event programs.

This is deliberately smaller than RFC 5545.  It defines the recurrence subset
LateLetter can reproduce in every runtime and resolves DST gaps/folds explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import calendar
from typing import Any, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MAX_CATCH_UP_DAYS = 366
MAX_OCCURRENCES_PER_EVALUATION = 400
MAX_GENERATION_STEPS = 200_000
_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "yearly"})
_MISSED_POLICIES = frozenset({"skip", "deliver_on_next_visit", "summarize_then_current"})
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


class ScheduleValidationError(ValueError):
    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Invalid garden schedule: " + "; ".join(errors))


@dataclass(frozen=True)
class RecurrenceRule:
    frequency: str
    interval: int = 1
    count: int | None = None
    until: datetime | None = None
    by_weekday: tuple[int, ...] = ()
    intentional_unbounded: bool = False
    dst_gap: str = "shift_forward"
    dst_fold: str = "first"


@dataclass(frozen=True)
class ScheduleRule:
    start: datetime
    timezone_name: str
    recurrence: RecurrenceRule | None
    exceptions: frozenset[str]
    missed: str


@dataclass(frozen=True)
class Occurrence:
    id: str
    scheduled_utc: datetime
    scheduled_local: datetime


@dataclass(frozen=True)
class ScheduleResult:
    occurrences: tuple[Occurrence, ...]
    summarized_missed: int = 0
    skipped_missed: int = 0
    catch_up_truncated: bool = False
    rollback_detected: bool = False


def _local_datetime(value: Any, path: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{path}: expected ISO local date/time string")
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors.append(f"{path}: invalid ISO date/time")
        return None
    if parsed.tzinfo is not None:
        errors.append(f"{path}: timezone belongs in the separate timezone field")
        return parsed.replace(tzinfo=None)
    return parsed


def parse_schedule(raw: Mapping[str, Any]) -> ScheduleRule:
    errors: list[str] = []
    if not isinstance(raw, Mapping):
        raise ScheduleValidationError(("$: schedule must be an object",))
    allowed = {"start", "timezone", "recurrence", "exceptions", "missed"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        errors.append("$: unknown fields " + ", ".join(unknown))
    start = _local_datetime(raw.get("start"), "$.start", errors)
    timezone_name = raw.get("timezone")
    if not isinstance(timezone_name, str):
        errors.append("$.timezone: required IANA timezone")
        timezone_name = "UTC"
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        errors.append(f"$.timezone: unknown IANA timezone {timezone_name!r}")
    missed = raw.get("missed")
    if missed not in _MISSED_POLICIES:
        errors.append("$.missed: unsupported missed-event policy")
        missed = "skip"
    exceptions_raw = raw.get("exceptions", [])
    if not isinstance(exceptions_raw, list) or any(not isinstance(item, str) for item in exceptions_raw):
        errors.append("$.exceptions: expected a list of ISO local dates or date/times")
        exceptions_raw = []
    exceptions: set[str] = set()
    for index, item in enumerate(exceptions_raw):
        try:
            parsed = datetime.fromisoformat(item)
            exceptions.add(parsed.isoformat(timespec="seconds"))
            exceptions.add(parsed.date().isoformat())
        except ValueError:
            errors.append(f"$.exceptions[{index}]: invalid ISO date or date/time")

    recurrence_raw = raw.get("recurrence")
    recurrence: RecurrenceRule | None = None
    if recurrence_raw is not None:
        if not isinstance(recurrence_raw, Mapping):
            errors.append("$.recurrence: expected an object or null")
        else:
            recurrence_allowed = {
                "frequency", "interval", "count", "until", "by_weekday",
                "intentional_unbounded", "dst_gap", "dst_fold",
            }
            recurrence_unknown = sorted(set(recurrence_raw) - recurrence_allowed)
            if recurrence_unknown:
                errors.append("$.recurrence: unknown fields " + ", ".join(recurrence_unknown))
            frequency = recurrence_raw.get("frequency")
            if frequency not in _FREQUENCIES:
                errors.append("$.recurrence.frequency: unsupported frequency")
                frequency = "daily"
            interval = recurrence_raw.get("interval", 1)
            if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 10_000:
                errors.append("$.recurrence.interval: expected integer from 1 to 10000")
                interval = 1
            count = recurrence_raw.get("count")
            if count is not None and (isinstance(count, bool) or not isinstance(count, int)
                                      or not 1 <= count <= 1_000_000):
                errors.append("$.recurrence.count: expected positive bounded integer")
                count = None
            until = None
            if recurrence_raw.get("until") is not None:
                until = _local_datetime(recurrence_raw["until"], "$.recurrence.until", errors)
            intentional = recurrence_raw.get("intentional_unbounded", False)
            if not isinstance(intentional, bool):
                errors.append("$.recurrence.intentional_unbounded: expected boolean")
                intentional = False
            if count is None and until is None and not intentional:
                errors.append("$.recurrence: count, until, or intentional_unbounded is required")
            weekdays_raw = recurrence_raw.get("by_weekday", [])
            if not isinstance(weekdays_raw, list) or any(day not in _WEEKDAYS for day in weekdays_raw):
                errors.append("$.recurrence.by_weekday: use MO through SU")
                weekdays_raw = []
            if weekdays_raw and frequency != "weekly":
                errors.append("$.recurrence.by_weekday: only valid for weekly recurrence")
            dst_gap = recurrence_raw.get("dst_gap", "shift_forward")
            dst_fold = recurrence_raw.get("dst_fold", "first")
            if dst_gap not in {"shift_forward", "skip"}:
                errors.append("$.recurrence.dst_gap: expected shift_forward or skip")
                dst_gap = "shift_forward"
            if dst_fold not in {"first", "second"}:
                errors.append("$.recurrence.dst_fold: expected first or second")
                dst_fold = "first"
            recurrence = RecurrenceRule(
                frequency=frequency, interval=interval, count=count, until=until,
                by_weekday=tuple(sorted({_WEEKDAYS[day] for day in weekdays_raw})),
                intentional_unbounded=intentional, dst_gap=dst_gap, dst_fold=dst_fold,
            )

    if errors:
        raise ScheduleValidationError(errors)
    assert start is not None
    return ScheduleRule(start=start, timezone_name=timezone_name,
                        recurrence=recurrence, exceptions=frozenset(exceptions),
                        missed=missed)


def _add_months(value: datetime, months: int) -> datetime | None:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    if value.day > calendar.monthrange(year, month)[1]:
        return None
    return value.replace(year=year, month=month)


def _candidate_locals(rule: ScheduleRule) -> Iterator[datetime]:
    recurrence = rule.recurrence
    if recurrence is None:
        yield rule.start
        return
    emitted = 0
    steps = 0
    if recurrence.frequency in {"daily", "weekly"}:
        candidate = rule.start
        while steps < MAX_GENERATION_STEPS:
            steps += 1
            days = (candidate.date() - rule.start.date()).days
            if recurrence.frequency == "daily":
                matches = days % recurrence.interval == 0
            elif recurrence.by_weekday:
                matches = ((days // 7) % recurrence.interval == 0
                           and candidate.weekday() in recurrence.by_weekday)
            else:
                matches = days % (7 * recurrence.interval) == 0
            if matches:
                if recurrence.until is not None and candidate > recurrence.until:
                    return
                emitted += 1
                yield candidate
                if recurrence.count is not None and emitted >= recurrence.count:
                    return
            candidate += timedelta(days=1)
    else:
        index = 0
        while steps < MAX_GENERATION_STEPS:
            steps += 1
            if recurrence.frequency == "monthly":
                candidate = _add_months(rule.start, index * recurrence.interval)
            else:
                try:
                    candidate = rule.start.replace(year=rule.start.year + index * recurrence.interval)
                except ValueError:
                    candidate = None
            index += 1
            if candidate is None:
                continue
            if recurrence.until is not None and candidate > recurrence.until:
                return
            emitted += 1
            yield candidate
            if recurrence.count is not None and emitted >= recurrence.count:
                return
    raise RuntimeError("schedule generation exceeded its deterministic safety bound")


def _valid_local(naive: datetime, zone: ZoneInfo, fold: int) -> datetime | None:
    candidate = naive.replace(tzinfo=zone, fold=fold)
    round_trip = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    return candidate if round_trip == naive else None


def _resolve_local(naive: datetime, zone: ZoneInfo, *, gap: str,
                   fold: str) -> datetime | None:
    first = _valid_local(naive, zone, 0)
    second = _valid_local(naive, zone, 1)
    if first is not None and second is not None and first.utcoffset() != second.utcoffset():
        return first if fold == "first" else second
    if first is not None:
        return first
    if second is not None:
        return second
    if gap == "skip":
        return None
    shifted = naive
    for _ in range(180):
        shifted += timedelta(minutes=1)
        resolved = _valid_local(shifted, zone, 0)
        if resolved is not None:
            return resolved
    raise RuntimeError("DST gap exceeded three-hour safety bound")


def _is_exception(local: datetime, exceptions: frozenset[str]) -> bool:
    naive = local.replace(tzinfo=None)
    return (naive.date().isoformat() in exceptions
            or naive.isoformat(timespec="seconds") in exceptions)


def _occurrence_id(event_id: str, scheduled_utc: datetime) -> str:
    stamp = scheduled_utc.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return f"{event_id}@{stamp}"


def expand_schedule(rule: ScheduleRule, *, event_id: str,
                    last_seen_utc: datetime, now_utc: datetime,
                    current_window_seconds: int = 60) -> ScheduleResult:
    """Return bounded, rollback-safe occurrences due at the current visit."""
    if last_seen_utc.tzinfo is None or now_utc.tzinfo is None:
        raise ValueError("schedule boundaries must be timezone-aware")
    last_seen = last_seen_utc.astimezone(timezone.utc)
    now = now_utc.astimezone(timezone.utc)
    if now < last_seen:
        return ScheduleResult((), rollback_detected=True)
    catch_up_start = max(last_seen, now - timedelta(days=MAX_CATCH_UP_DAYS))
    truncated = last_seen < catch_up_start
    recurrence = rule.recurrence
    gap = recurrence.dst_gap if recurrence else "shift_forward"
    fold = recurrence.dst_fold if recurrence else "first"
    zone = ZoneInfo(rule.timezone_name)
    due: list[Occurrence] = []
    for local_naive in _candidate_locals(rule):
        aware = _resolve_local(local_naive, zone, gap=gap, fold=fold)
        if aware is None or _is_exception(aware, rule.exceptions):
            continue
        scheduled = aware.astimezone(timezone.utc)
        if scheduled > now:
            break
        if scheduled <= catch_up_start:
            continue
        due.append(Occurrence(_occurrence_id(event_id, scheduled), scheduled, aware))
        if len(due) > MAX_OCCURRENCES_PER_EVALUATION:
            due = due[-MAX_OCCURRENCES_PER_EVALUATION:]
            truncated = True

    if not due:
        return ScheduleResult((), catch_up_truncated=truncated)
    if rule.missed == "skip":
        current = tuple(item for item in due
                        if (now - item.scheduled_utc).total_seconds() <= current_window_seconds)
        return ScheduleResult(current, skipped_missed=len(due) - len(current),
                              catch_up_truncated=truncated)
    latest = due[-1]
    if rule.missed == "deliver_on_next_visit":
        return ScheduleResult((latest,), skipped_missed=max(0, len(due) - 1),
                              catch_up_truncated=truncated)
    return ScheduleResult((latest,), summarized_missed=max(0, len(due) - 1),
                          catch_up_truncated=truncated)
