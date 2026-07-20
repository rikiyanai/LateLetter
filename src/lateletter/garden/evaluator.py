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
from typing import Any, Mapping

from .program import Condition, GardenProgram, ProgramAction, ProgramEvent


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
        if not isinstance(observed, (int, float)) or not isinstance(expected, (int, float)):
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
        else:
            # Authored animal choreography is emitted for the world owner to
            # consume; the evaluator never invents renderer-local movement.
            entity["directive"] = {"type": action.type, **params}

    effects.append(effect)


def _occurrence_for(event: ProgramEvent, context: Mapping[str, Any]) -> str | None:
    eligibility = context.get("eligible_occurrences", {})
    if event.schedule is None:
        return f"{event.id}:once"
    if not isinstance(eligibility, Mapping):
        raise ValueError("context.eligible_occurrences must be an object")
    value = eligibility.get(event.id)
    if value is True:
        return f"{event.id}:scheduled"
    if isinstance(value, str) and value:
        return value
    return None


def evaluate_program(program: GardenProgram, state: Mapping[str, Any],
                     context: Mapping[str, Any]) -> EvaluationResult:
    """Run eligible events to completion in one deterministic transaction."""
    next_state = _canonical_clone(state)
    context_copy = _canonical_clone(context)
    facts = context_copy.get("facts", {})
    if not isinstance(facts, Mapping):
        raise ValueError("context.facts must be an object")
    seed = context_copy.get("seed", 0)

    ledger = next_state.setdefault("applied_occurrences", [])
    if not isinstance(ledger, list) or any(not isinstance(item, str) for item in ledger):
        raise ValueError("state.applied_occurrences must be a list of strings")
    applied = set(ledger)
    exclusive_claims = next_state.setdefault("exclusive_claims", {})
    if not isinstance(exclusive_claims, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in exclusive_claims.items()
    ):
        raise ValueError("state.exclusive_claims must be an object of string claims")
    claimed_groups: set[str] = set(exclusive_claims)
    effects: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    for event in sorted(program.events, key=lambda item: (-item.priority, item.id)):
        occurrence_id = _occurrence_for(event, context_copy)
        row: dict[str, Any] = {
            "event_id": event.id, "priority": event.priority,
            "exclusive_group": event.exclusive_group,
            "occurrence_id": occurrence_id,
        }
        if occurrence_id is None:
            row.update(status="blocked", reason="schedule_not_eligible")
            trace.append(row)
            continue
        ledger_id = f"{event.id}@{occurrence_id}"
        if ledger_id in applied:
            row.update(status="skipped", reason="already_applied")
            trace.append(row)
            continue
        if event.exclusive_group and event.exclusive_group in claimed_groups:
            row.update(status="blocked", reason="exclusive_group_claimed")
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
            continue

        for action in event.actions:
            _apply_action(action, next_state, event.id, effects)
        applied.add(ledger_id)
        ledger.append(ledger_id)
        ledger.sort()
        if event.exclusive_group:
            claimed_groups.add(event.exclusive_group)
            exclusive_claims[event.exclusive_group] = ledger_id
        row.update(status="applied", effect_count=len(event.actions))
        trace.append(row)

    return EvaluationResult(state=next_state, effects=tuple(effects), trace=tuple(trace))
