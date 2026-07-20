"""The sole compatibility owner for authenticated v1 ``garden_gifts``.

Renderers must not evaluate legacy triggers directly.  After bundle HMAC
authentication and gift-sentiment decryption, this module translates each gift
to one canonical, idempotent program event.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from .program import GardenProgram, ProgramValidationError, parse_program


class LegacyAuthenticationRequired(PermissionError):
    pass


class LegacyMigrationError(ValueError):
    pass


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _trigger_field(gift: Any, name: str) -> Any:
    trigger = _field(gift, "trigger")
    if trigger is None:
        return None
    return _field(trigger, name)


def _completion_condition(message_ids: Sequence[str]) -> Mapping[str, Any] | None:
    if not message_ids:
        return None
    return {
        "all": [
            {"fact": "letter.read", "op": "contains", "ref": message_id}
            for message_id in sorted(set(message_ids))
        ]
    }


def _legacy_condition(gift: Any) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    trigger_type = _trigger_field(gift, "type")
    value = _trigger_field(gift, "value")
    if trigger_type == "date":
        try:
            date.fromisoformat(str(value))
        except ValueError as exc:
            raise LegacyMigrationError(f"legacy gift has invalid date trigger {value!r}") from exc
        return ({"fact": "time.local", "op": ">=", "value": f"{value}T00:00:00"}, None)
    if trigger_type == "cumulative_visits":
        try:
            visits = int(value)
        except (TypeError, ValueError) as exc:
            raise LegacyMigrationError(f"legacy gift has invalid visit trigger {value!r}") from exc
        if visits < 0:
            raise LegacyMigrationError("legacy visit trigger cannot be negative")
        return {"fact": "visit.total", "op": ">=", "value": visits}, None
    if trigger_type == "post_letter":
        return {"fact": "letter.read", "op": "contains", "ref": str(value)}, None
    raise LegacyMigrationError(f"unsupported legacy trigger {trigger_type!r}")


def migrate_legacy_gifts(
    gifts: Sequence[Any], *, authenticated: bool,
    decrypted_sentiments: Mapping[str, str] | None = None,
    message_ids: Sequence[str] = (), author_timezone: str = "UTC",
    atlas_version: str = "garden-atlas-1",
    astronomy_catalog_version: str = "bright-stars-1",
) -> GardenProgram:
    """Translate v1 gifts to an in-memory program only after authentication."""
    if not authenticated:
        raise LegacyAuthenticationRequired(
            "legacy gifts cannot influence world state before bundle authentication"
        )
    sentiments = decrypted_sentiments or {}
    entities: list[dict[str, Any]] = []
    animals: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    completion = _completion_condition(message_ids)

    for index, gift in enumerate(gifts):
        gift_id = _field(gift, "id")
        gift_type = _field(gift, "type")
        catalog_id = _field(gift, "catalog_id")
        if not isinstance(gift_id, str) or not gift_id:
            raise LegacyMigrationError(f"legacy gift {index} has no stable id")
        if gift_type not in {"item", "plant", "animal", "landmark", "nudge"}:
            raise LegacyMigrationError(f"legacy gift {gift_id} has unsupported type {gift_type!r}")
        if not isinstance(catalog_id, str) or not catalog_id:
            raise LegacyMigrationError(f"legacy gift {gift_id} has no catalog id")

        original, schedule = _legacy_condition(gift)
        condition: Mapping[str, Any]
        if completion is not None:
            condition = {"any": [original, completion]}
        else:
            condition = original
        event_id = f"legacy.{gift_id}"
        target_id = f"legacy-entity.{gift_id}"
        placement = str(_field(gift, "placement_hint", "random"))

        actions: list[dict[str, Any]] = []
        if gift_type == "animal":
            animals.append({
                "id": target_id,
                "species": catalog_id,
                "catalog_id": catalog_id,
                "name": _field(gift, "animal_name") or catalog_id,
                "initial_state": {"present": False},
            })
            actions.append({
                "type": "animal.arrive", "target": target_id,
                "params": {"position": placement},
            })
        elif gift_type == "plant":
            entities.append({
                "id": target_id, "kind": "plant", "catalog_id": catalog_id,
                "initial_state": {"planted": False}, "placement": placement,
            })
            actions.append({
                "type": "plant.plant", "target": target_id,
                "params": {"species_id": catalog_id, "position": placement},
            })
        else:
            entities.append({
                "id": target_id, "kind": gift_type, "catalog_id": catalog_id,
                "initial_state": {"revealed": False}, "placement": placement,
            })
            actions.append({
                "type": "entity.reveal", "target": target_id,
                "params": {"position": placement},
            })

        sentiment = sentiments.get(gift_id, "")
        if sentiment:
            actions.append({
                "type": "narrative.show", "target": None,
                "params": {"kind": "memory", "text": sentiment,
                           "label": _field(gift, "animal_name") or catalog_id},
            })
        actions.append({
            "type": "event.complete", "target": None,
            "params": {"event_id": event_id},
        })
        events.append({
            "id": event_id, "conditions": condition, "schedule": schedule,
            "occurrence": "once", "priority": 0, "exclusive_group": None,
            "cooldown": None, "actions": actions,
        })

    raw = {
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": atlas_version,
        "astronomy_catalog_version": astronomy_catalog_version,
        "author_timezone": author_timezone,
        "variables": {}, "entities": entities, "animals": animals,
        "events": events,
    }
    try:
        return parse_program(raw)
    except ProgramValidationError as exc:
        raise LegacyMigrationError(str(exc)) from exc
