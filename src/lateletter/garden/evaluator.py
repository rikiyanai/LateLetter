"""Pure deterministic evaluator for validated garden programs.

Clock and recurrence expansion are intentionally outside this module.  A clock
owner supplies ``eligible_occurrences`` in the context; this evaluator orders
those occurrences, applies conditions and actions, and records idempotency.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from .program import Condition, GardenProgram, ProgramAction, ProgramEvent


OCCURRENCE_LEDGER_LIMIT = 512
EXCLUSIVE_LEDGER_LIMIT = 512


def _compact_recent(values: list[str], limit: int) -> list[str]:
    recent: dict[str, None] = {}
    for value in values:
        recent.pop(value, None)
        recent[value] = None
    return list(recent)[-limit:]


@dataclass(frozen=True)
class EvaluationResult:
    state: dict[str, Any]
    effects: tuple[dict[str, Any], ...]
    trace: tuple[dict[str, Any], ...]


def _canonical_clone(value: Mapping[str, Any]) -> dict[str, Any]:
    """Clone JSON state while rejecting non-canonical runtime objects."""
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"state/context must contain canonical JSON values: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("state must be a mapping")
    return decoded


def _lookup(mapping: Mapping[str, Any], dotted: str) -> tuple[bool, Any]:
    if dotted in mapping:
        return True, mapping[dotted]
    current: Any = mapping
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _compare(observed: Any, op: str, expected: Any, exists: bool) -> bool:
    if op == "exists":
        return exists if expected is None else exists is bool(expected)
    if not exists:
        return False
    if op == "==":
        return observed == expected
    if op == "!=":
        return observed != expected
    if op in {">", ">=", "<", "<="}:
        if isinstance(observed, bool) or isinstance(expected, bool):
            return False
        comparable_numbers = (isinstance(observed, (int, float))
                              and isinstance(expected, (int, float)))
        comparable_strings = isinstance(observed, str) and isinstance(expected, str)
        if not comparable_numbers and not comparable_strings:
            return False
        return {
            ">": observed > expected,
            ">=": observed >= expected,
            "<": observed < expected,
            "<=": observed <= expected,
        }[op]
    if op in {"contains", "not_contains"}:
        try:
            result = expected in observed
        except (TypeError, ValueError):
            result = False
        return not result if op == "not_contains" else result
    if op in {"in", "not_in"}:
        try:
            result = observed in expected
        except (TypeError, ValueError):
            result = False
        return not result if op == "not_in" else result
    return False


def _seeded_probability(seed: Any, event_id: str, occurrence_id: str) -> float:
    material = f"garden-probability-v1\0{seed}\0{event_id}\0{occurrence_id}".encode()
    number = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return number / 2**64


def evaluate_condition(condition: Condition, facts: Mapping[str, Any], *,
                       seed: Any = 0, event_id: str = "",
                       occurrence_id: str = "") -> tuple[bool, dict[str, Any]]:
    """Evaluate a condition and return its result plus an explainable trace."""
    if condition.kind in {"all", "any", "not"}:
        children = [
            evaluate_condition(child, facts, seed=seed, event_id=event_id,
                               occurrence_id=occurrence_id)
            for child in condition.children
        ]
        values = [value for value, _ in children]
        if condition.kind == "all":
            result = all(values)
        elif condition.kind == "any":
            result = any(values)
        else:
            result = not values[0] if values else True
        return result, {
            "kind": condition.kind, "result": result,
            "children": [trace for _, trace in children],
        }

    if condition.fact == "probability.seeded":
        exists, observed = True, _seeded_probability(seed, event_id, occurrence_id)
    else:
        exists, observed = _lookup(facts, condition.fact or "")
    expected = condition.ref if condition.ref is not None else condition.value
    result = _compare(observed, condition.op or "", expected, exists)
    return result, {
        "kind": "leaf", "fact": condition.fact, "op": condition.op,
        "expected": deepcopy(expected), "observed": deepcopy(observed),
        "exists": exists, "result": result,
    }


def _entity_slot(state: dict[str, Any], target: str) -> dict[str, Any]:
    entities = state.setdefault("entities", {})
    if not isinstance(entities, dict):
        raise ValueError("state.entities must be an object")
    entity = entities.setdefault(target, {"id": target})
    if not isinstance(entity, dict):
        raise ValueError(f"state.entities.{target} must be an object")
    return entity


def _apply_action(action: ProgramAction, state: dict[str, Any], event_id: str,
                  effects: list[dict[str, Any]]) -> None:
    params = deepcopy(dict(action.params))
    effect = {"type": action.type, "event_id": event_id}
    if action.target is not None:
        effect["target"] = action.target
    if params:
        effect["params"] = params

    if action.type == "variable.set":
        state.setdefault("variables", {})[params["name"]] = deepcopy(params.get("value"))
    elif action.type == "variable.increment":
        variables = state.setdefault("variables", {})
        name = params["name"]
        current = variables.get(name, 0)
        amount = params.get("amount", 1)
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ValueError(f"variable {name} is not numeric")
        variables[name] = current + amount
    elif action.type == "event.complete":
        completed = state.setdefault("completed_events", [])
        completed_id = params.get("event_id", event_id)
        if completed_id not in completed:
            completed.append(completed_id)
            completed.sort()
    elif action.type.startswith(("entity.", "animal.", "plant.")):
        assert action.target is not None
        entity = _entity_slot(state, action.target)
        if action.type.endswith(".reveal"):
            entity["revealed"] = True
        elif action.type.endswith(".retire"):
            entity["retired"] = True
        elif action.type.endswith(".place") or action.type.endswith(".move"):
            entity["position"] = deepcopy(params["position"])
        elif action.type.endswith(".transform"):
            if "state" in params:
                entity["state"] = deepcopy(params["state"])
            if "asset_id" in params:
                entity["asset_id"] = params["asset_id"]
        elif action.type == "animal.arrive":
            entity["present"] = True
            entity.update(deepcopy(params))
        elif action.type == "animal.depart":
            entity["present"] = False
        elif action.type == "plant.plant":
            entity.update(deepcopy(params))
            entity["planted"] = True
        elif action.type == "plant.grow":
            entity.update(deepcopy(params))
        elif action.type == "plant.bloom":
            entity["blooming"] = True
            entity.update(deepcopy(params))
        elif action.type == "plant.dormancy":
            entity["dormant"] = bool(params.get("dormant", True))
        elif action.type == "plant.prune":
            entity["pruned_node_ids"] = deepcopy(params.get("node_ids", []))
        elif action.type == "plant.revive":
            entity["dormant"] = False
            entity["revived"] = True
        elif action.type in {"animal.deliver", "animal.present_gift"}:
            # Delivery is an immediate semantic transaction.  Renderers may
            # animate it, but the authoritative state records both completion
            # and the revealed object so a later event can depend on it in the
            # same run-to-completion evaluation.
            reference_key = "entity_id" if action.type == "animal.deliver" else "gift_id"
            delivered_id = str(params[reference_key])
            delivered = _entity_slot(state, delivered_id)
            delivered.update({
                "revealed": True,
                "delivered": True,
                "delivered_by": action.target,
            })
            entity["directive"] = {
                "type": action.type,
                **params,
                "status": "completed",
            }
        else:
            # Authored animal choreography is emitted for the world owner to
            # consume.  The semantic directive completes immediately; a
            # renderer-local animation cannot hold authored progression open.
            entity["directive"] = {
                "type": action.type,
                **params,
                "status": "completed",
            }

    effects.append(effect)


def _occurrence_for(event: ProgramEvent, context: Mapping[str, Any]) -> str | None:
    eligibility = context.get("eligible_occurrences", {})
    if event.schedule is None:
        if event.occurrence == "recurring":
            facts = context.get("facts", {})
            if isinstance(facts, Mapping):
                visit = facts.get("visit.total")
                if isinstance(visit, int) and not isinstance(visit, bool):
                    return f"{event.id}:visit:{visit}"
                stamp = facts.get("time.utc")
                if isinstance(stamp, str) and stamp:
                    return f"{event.id}:time:{stamp}"
        return f"{event.id}:once"
    if not isinstance(eligibility, Mapping):
        raise ValueError("context.eligible_occurrences must be an object")
    value = eligibility.get(event.id)
    if value is True:
        return f"{event.id}:scheduled"
    if isinstance(value, str) and value:
        return value
    return None


def _exclusive_scope(
    event: ProgramEvent,
    occurrence_id: str,
    context: Mapping[str, Any],
) -> str:
    """Return the shared visit/schedule scope for an exclusive occurrence."""
    transaction_id = context.get("transaction_id")
    if isinstance(transaction_id, str) and transaction_id:
        return transaction_id
    prefix = f"{event.id}:"
    scheduled_prefix = f"{event.id}@"
    if occurrence_id.startswith(prefix):
        return occurrence_id[len(prefix):]
    if occurrence_id.startswith(scheduled_prefix):
        return occurrence_id[len(scheduled_prefix):]
    return occurrence_id


def _cooldown_values(facts: Mapping[str, Any]) -> tuple[int | None, int | None]:
    raw_time = facts.get("time.utc")
    now_seconds: int | None = None
    if isinstance(raw_time, str):
        try:
            parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                now_seconds = int(parsed.astimezone(timezone.utc).timestamp())
        except ValueError:
            pass
    raw_visits = facts.get("visit.total")
    visits = raw_visits if isinstance(raw_visits, int) and not isinstance(raw_visits, bool) else None
    return now_seconds, visits


def _cooldown_blocked(
    event: ProgramEvent,
    cooldowns: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> bool:
    if not event.cooldown:
        return False
    prior = cooldowns.get(event.id)
    if not isinstance(prior, Mapping):
        return False
    now_seconds, visits = _cooldown_values(facts)
    duration = event.cooldown.get("duration_seconds")
    if isinstance(duration, int) and now_seconds is not None:
        last_time = prior.get("time_utc_seconds")
        if isinstance(last_time, int) and now_seconds - last_time < duration:
            return True
    visit_gap = event.cooldown.get("visits")
    if isinstance(visit_gap, int) and visits is not None:
        last_visit = prior.get("visit_total")
        if isinstance(last_visit, int) and visits - last_visit < visit_gap:
            return True
    return False


def _derived_facts(state: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    """Refresh facts that authored actions can change during this transaction.

    The clock/session owner remains responsible for external facts.  This
    function only projects evaluator-owned semantic state, which is what makes
    dependent beats deterministic without renderer callbacks.
    """
    facts = deepcopy(dict(base))
    completed = state.get("completed_events", [])
    if isinstance(completed, list):
        prior_completed = facts.get("event.completed", [])
        prior_completed = prior_completed if isinstance(prior_completed, list) else []
        facts["event.completed"] = sorted({
            *(str(item) for item in prior_completed),
            *(str(item) for item in completed),
        })
    entities = state.get("entities", {})
    if isinstance(entities, Mapping):
        for fact_name, state_key in (
            ("gift.revealed", "revealed"),
            ("animal.arrived", "present"),
            ("plant.bloom", "blooming"),
        ):
            prior = facts.get(fact_name, [])
            facts[fact_name] = sorted({
                *(str(item) for item in prior if isinstance(prior, list)),
                *(str(target) for target, value in entities.items()
                  if isinstance(value, Mapping) and value.get(state_key) is True),
            })
        growth = [
            value.get("stage", value.get("amount", 0))
            for value in entities.values()
            if isinstance(value, Mapping) and value.get("planted") is True
        ]
        numeric_growth = [
            value for value in growth
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if numeric_growth:
            prior_growth = facts.get("plant.growth_stage", 0)
            facts["plant.growth_stage"] = max(
                max(numeric_growth),
                prior_growth if isinstance(prior_growth, (int, float))
                and not isinstance(prior_growth, bool) else 0,
            )
    return facts


def evaluate_program(program: GardenProgram, state: Mapping[str, Any],
                     context: Mapping[str, Any]) -> EvaluationResult:
    """Run eligible events to completion in one deterministic transaction."""
    next_state = _canonical_clone(state)
    context_copy = _canonical_clone(context)
    base_facts = context_copy.get("facts", {})
    if not isinstance(base_facts, Mapping):
        raise ValueError("context.facts must be an object")
    seed = context_copy.get("seed", 0)

    ledger = next_state.setdefault("applied_occurrences", [])
    if not isinstance(ledger, list) or any(not isinstance(item, str) for item in ledger):
        raise ValueError("state.applied_occurrences must be a list of strings")
    original_ledger_length = len(ledger)
    ledger[:] = _compact_recent(ledger, OCCURRENCE_LEDGER_LIMIT)
    next_state["applied_occurrence_total"] = max(
        original_ledger_length,
        int(next_state.get("applied_occurrence_total", 0)),
    )
    applied = set(ledger)
    # v1 persisted a single claim per group, which permanently suppressed later
    # visits.  Claims now include the shared visit/schedule occurrence scope.
    next_state.pop("exclusive_claims", None)
    exclusive_occurrences = next_state.setdefault("exclusive_occurrences", [])
    if not isinstance(exclusive_occurrences, list) or any(
        not isinstance(item, str) for item in exclusive_occurrences
    ):
        raise ValueError("state.exclusive_occurrences must be a list of strings")
    original_exclusive_length = len(exclusive_occurrences)
    exclusive_occurrences[:] = _compact_recent(
        exclusive_occurrences, EXCLUSIVE_LEDGER_LIMIT,
    )
    next_state["exclusive_occurrence_total"] = max(
        original_exclusive_length,
        int(next_state.get("exclusive_occurrence_total", 0)),
    )
    persisted_exclusive = set(exclusive_occurrences)
    claimed_groups: set[str] = set()
    cooldowns = next_state.setdefault("event_cooldowns", {})
    if not isinstance(cooldowns, dict):
        raise ValueError("state.event_cooldowns must be an object")
    effects: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    ordered = sorted(program.events, key=lambda item: (-item.priority, item.id))
    pending = list(ordered)
    evaluation_pass = 0
    # At least one occurrence is consumed on every productive pass, so this
    # bound is both deterministic and sufficient for every acyclic program.
    while pending and evaluation_pass <= len(ordered):
        evaluation_pass += 1
        progressed = False
        retry: list[ProgramEvent] = []
        facts = _derived_facts(next_state, base_facts)
        for event in pending:
            occurrence_id = _occurrence_for(event, context_copy)
            row: dict[str, Any] = {
                "event_id": event.id, "priority": event.priority,
                "exclusive_group": event.exclusive_group,
                "occurrence_id": occurrence_id,
                "evaluation_pass": evaluation_pass,
            }
            if occurrence_id is None:
                row.update(status="blocked", reason="schedule_not_eligible")
                trace.append(row)
                continue
            ledger_id = f"{event.id}@{occurrence_id}"
            exclusive_key = None
            if event.exclusive_group:
                exclusive_key = (
                    f"{event.exclusive_group}@"
                    f"{_exclusive_scope(event, occurrence_id, context_copy)}"
                )
            if ledger_id in applied:
                row.update(status="skipped", reason="already_applied")
                trace.append(row)
                continue
            if event.exclusive_group and (
                event.exclusive_group in claimed_groups
                or exclusive_key in persisted_exclusive
            ):
                row.update(status="blocked", reason="exclusive_group_claimed")
                trace.append(row)
                continue
            if _cooldown_blocked(event, cooldowns, facts):
                row.update(status="blocked", reason="cooldown_active")
                trace.append(row)
                continue

            eligible, condition_trace = evaluate_condition(
                event.conditions, facts, seed=seed, event_id=event.id,
                occurrence_id=occurrence_id,
            )
            row["conditions"] = condition_trace
            if not eligible:
                row.update(status="blocked", reason="conditions_false")
                trace.append(row)
                retry.append(event)
                continue

            for action in event.actions:
                _apply_action(action, next_state, event.id, effects)
            applied.add(ledger_id)
            ledger.append(ledger_id)
            ledger[:] = _compact_recent(ledger, OCCURRENCE_LEDGER_LIMIT)
            next_state["applied_occurrence_total"] += 1
            if event.exclusive_group:
                claimed_groups.add(event.exclusive_group)
                assert exclusive_key is not None
                persisted_exclusive.add(exclusive_key)
                exclusive_occurrences.append(exclusive_key)
                exclusive_occurrences[:] = _compact_recent(
                    exclusive_occurrences, EXCLUSIVE_LEDGER_LIMIT,
                )
                next_state["exclusive_occurrence_total"] += 1
            if event.cooldown:
                now_seconds, visits = _cooldown_values(facts)
                cooldowns[event.id] = {
                    **({"time_utc_seconds": now_seconds} if now_seconds is not None else {}),
                    **({"visit_total": visits} if visits is not None else {}),
                }
            row.update(status="applied", effect_count=len(event.actions))
            trace.append(row)
            progressed = True
            # Lower-priority events in this same pass must see completed event,
            # reveal, arrival, and plant facts produced above.
            facts = _derived_facts(next_state, base_facts)
        if not progressed:
            break
        pending = retry

    return EvaluationResult(state=next_state, effects=tuple(effects), trace=tuple(trace))
