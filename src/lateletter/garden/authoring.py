"""Fatigue-aware beat-card authoring and exact-runtime preview.

Authors work with ``When`` and ``ActionCard`` objects rather than raw JSON.
Compilation produces the same :class:`GardenProgram` consumed by recipient
runtimes, and preview delegates directly to the canonical evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .evaluator import EvaluationResult, evaluate_program
from .program import (
    GardenProgram,
    ProgramValidationError,
    narrative_ethics_violation,
    parse_program,
)
from .schedule import ScheduleValidationError, parse_schedule


TRACKS = frozenset({"letters", "animals", "plants", "fixtures", "gifts", "sky", "revisit"})


class FatigueLimitReached(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthoringIssue:
    code: str
    path: str
    message: str
    blocking: bool = True


class AuthoringValidationError(ValueError):
    def __init__(self, issues: Sequence[AuthoringIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("Garden timeline is not exportable: " + "; ".join(
            f"{issue.path}: {issue.message}" for issue in issues if issue.blocking
        ))


@dataclass(frozen=True)
class When:
    """Plain-language condition card compiled to the canonical condition tree."""

    kind: str
    fact_name: str | None = None
    operator: str | None = None
    value: Any = None
    reference: str | None = None
    children: tuple["When", ...] = ()

    @classmethod
    def fact(cls, name: str, operator: str, value: Any = None, *,
             reference: str | None = None) -> "When":
        return cls("leaf", fact_name=name, operator=operator, value=value,
                   reference=reference)

    @classmethod
    def every(cls, *conditions: "When") -> "When":
        if not conditions:
            raise ValueError("every() needs at least one condition")
        return cls("all", children=tuple(conditions))

    @classmethod
    def either(cls, *conditions: "When") -> "When":
        if not conditions:
            raise ValueError("either() needs at least one condition")
        return cls("any", children=tuple(conditions))

    @classmethod
    def never(cls, condition: "When") -> "When":
        return cls("not", children=(condition,))

    def compile(self) -> dict[str, Any]:
        if self.kind == "leaf":
            result = {"fact": self.fact_name, "op": self.operator}
            if self.reference is not None:
                result["ref"] = self.reference
            elif self.operator != "exists" or self.value is not None:
                result["value"] = self.value
            return result
        if self.kind == "not":
            return {"not": self.children[0].compile()}
        return {self.kind: [child.compile() for child in self.children]}


@dataclass(frozen=True)
class ActionCard:
    type: str
    target: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def reveal(cls, target: str, *, position: Any = "authored") -> "ActionCard":
        return cls("entity.reveal", target, {"position": position})

    @classmethod
    def show_memory(cls, text: str, *, label: str = "memory") -> "ActionCard":
        return cls("narrative.show", None, {"kind": "memory", "text": text, "label": label})

    @classmethod
    def set_variable(cls, name: str, value: Any) -> "ActionCard":
        return cls("variable.set", None, {"name": name, "value": value})

    @classmethod
    def increment(cls, name: str, amount: int | float = 1) -> "ActionCard":
        return cls("variable.increment", None, {"name": name, "amount": amount})

    @classmethod
    def complete(cls, event_id: str) -> "ActionCard":
        return cls("event.complete", None, {"event_id": event_id})

    def compile(self) -> dict[str, Any]:
        return {"type": self.type, "target": self.target, "params": dict(self.params)}


@dataclass(frozen=True)
class BeatCard:
    id: str
    title: str
    track: str
    when: When
    actions: tuple[ActionCard, ...]
    schedule: Mapping[str, Any] | None = None
    priority: int = 0
    exclusive_group: str | None = None
    cooldown: Mapping[str, Any] | None = None
    occurrence: str = "auto"


@dataclass
class Timeline:
    author_timezone: str
    variables: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    animals: list[dict[str, Any]] = field(default_factory=list)
    beats: list[BeatCard] = field(default_factory=list)
    atlas_version: str = "garden-atlas-1"
    astronomy_catalog_version: str = "bright-stars-1"
    session_beat_limit: int = 3
    _beats_this_session: int = 0

    def __post_init__(self) -> None:
        if self.session_beat_limit < 1:
            raise ValueError("session beat limit must be positive")

    @property
    def pause_recommended(self) -> bool:
        return self._beats_this_session >= self.session_beat_limit

    def begin_session(self) -> None:
        self._beats_this_session = 0

    def add_beat(self, beat: BeatCard) -> None:
        if self.pause_recommended:
            raise FatigueLimitReached(
                "This session's beat-card limit is reached; save and resume later."
            )
        if beat.track not in TRACKS:
            raise ValueError(f"unsupported timeline track {beat.track!r}")
        self.beats.append(beat)
        self._beats_this_session += 1

    def reorder(self, beat_id: str, new_index: int) -> None:
        index = next((i for i, beat in enumerate(self.beats) if beat.id == beat_id), None)
        if index is None:
            raise KeyError(beat_id)
        beat = self.beats.pop(index)
        self.beats.insert(max(0, min(new_index, len(self.beats))), beat)


def _condition_leaves(when: When) -> Iterable[When]:
    if when.kind == "leaf":
        yield when
    else:
        for child in when.children:
            yield from _condition_leaves(child)


def _condition_dependencies(when: When) -> set[str]:
    return {
        leaf.reference for leaf in _condition_leaves(when)
        if leaf.fact_name == "event.completed" and leaf.reference is not None
    }


def _contradiction(when: When) -> bool:
    if when.kind != "all":
        return any(_contradiction(child) for child in when.children)
    equals: dict[tuple[str, str | None], Any] = {}
    lower: dict[tuple[str, str | None], float] = {}
    upper: dict[tuple[str, str | None], float] = {}
    for leaf in _condition_leaves(when):
        key = (leaf.fact_name or "", leaf.reference)
        if leaf.operator == "==":
            if key in equals and equals[key] != leaf.value:
                return True
            equals[key] = leaf.value
        if isinstance(leaf.value, (int, float)) and not isinstance(leaf.value, bool):
            if leaf.operator in {">", ">="}:
                lower[key] = max(lower.get(key, float("-inf")), float(leaf.value))
            if leaf.operator in {"<", "<="}:
                upper[key] = min(upper.get(key, float("inf")), float(leaf.value))
    return any(lower.get(key, float("-inf")) > upper.get(key, float("inf"))
               for key in set(lower) | set(upper))


def _cycle_nodes(graph: Mapping[str, set[str]]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        if node in visiting:
            cycles.update(trail[trail.index(node):])
            return
        if node in visited:
            return
        visiting.add(node)
        trail.append(node)
        for dependency in sorted(graph.get(node, set())):
            if dependency in graph:
                visit(dependency, trail)
        trail.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    return cycles


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def _narrative_surfaces(timeline: Timeline) -> Iterable[tuple[str, str]]:
    """Yield every author-facing string that can become recipient narrative."""
    for index, beat in enumerate(timeline.beats):
        yield f"beats[{index}].title", beat.title
        for action_index, action in enumerate(beat.actions):
            if action.type in {
                "narrative.show", "scene.set", "entity.transform",
                "animal.behave", "animal.routine",
            }:
                for value in _strings(action.params):
                    yield f"beats[{index}].actions[{action_index}]", value
    for index, entity in enumerate(timeline.entities):
        for value in _strings(entity.get("properties", {})):
            yield f"entities[{index}].properties", value
    for index, animal in enumerate(timeline.animals):
        for field in ("name", "personality", "routine", "gifts", "milestones"):
            for value in _strings(animal.get(field)):
                yield f"animals[{index}].{field}", value


def build_letter_rabbit_autumn_arc(
    *,
    recipient_name: str,
    letter_id: str,
    author_timezone: str = "UTC",
    rabbit_name: str = "Clover",
) -> Timeline:
    """Build the complete §7.8.13 author-control acceptance arc.

    This guided template is ordinary beat-card data, not a privileged runtime
    path.  Authors can edit every condition/action in the no-JSON timeline UI,
    and preview/export uses the same evaluator as recipients.
    """
    safe_recipient = recipient_name.strip() or "you"
    timeline = Timeline(author_timezone=author_timezone, session_beat_limit=10)
    timeline.entities.extend((
        {
            "id": "arc.autumn-rose", "kind": "plant", "catalog_id": "rose",
            "position": [24, 12], "initial_state": {"planted": False},
            "properties": {"label": f"{safe_recipient}'s rose"},
        },
        {
            "id": "arc.autumn-gift", "kind": "collectible",
            "catalog_id": "collectible.seed_packet", "position": [28, 12],
            "initial_state": {"revealed": False},
            "properties": {
                "label": "an autumn keepsake",
                "description": "A small gift carried here with care.",
            },
        },
    ))
    timeline.animals.append({
        "id": "arc.rabbit", "species": "rabbit", "catalog_id": "rabbit",
        "name": rabbit_name, "personality": "gentle, curious, and patient",
        "routine": "visit the rose, rest nearby, and greet without demanding attention",
        "favorite_places": ["arc.autumn-rose"],
        "prohibited_behaviors": ["guilt", "urgency", "resource guarding"],
        "gifts": ["arc.autumn-gift"],
        "milestones": ["arrived", "bonded", "autumn gift delivered"],
        "initial_state": {"present": False},
    })
    timeline.beats.extend((
        BeatCard(
            id="arc.rabbit-arrives", title=f"{rabbit_name} arrives after the letter",
            track="animals",
            when=When.fact("letter.read", "contains", reference=letter_id),
            actions=(
                ActionCard("animal.arrive", "arc.rabbit", {
                    "position": [20, 12], "routine": "gentle greeting",
                }),
                ActionCard.show_memory(
                    f"{rabbit_name} has come to keep {safe_recipient} company.",
                    label=f"{rabbit_name} arrives",
                ),
                ActionCard.complete("arc.rabbit-arrives"),
            ),
            priority=300,
        ),
        BeatCard(
            id="arc.third-visit-rose", title="The rose grows on the third visit",
            track="plants",
            when=When.every(
                When.fact("event.completed", "contains", reference="arc.rabbit-arrives"),
                When.fact("visit.total", ">=", 3),
            ),
            actions=(
                ActionCard("plant.plant", "arc.autumn-rose", {
                    "species_id": "rose", "position": [24, 12],
                }),
                ActionCard("plant.grow", "arc.autumn-rose", {"amount": 3}),
                ActionCard.complete("arc.third-visit-rose"),
            ),
            priority=200,
        ),
        BeatCard(
            id="arc.bonded-autumn-gift", title="A bonded autumn gift",
            track="gifts",
            when=When.every(
                When.fact("event.completed", "contains", reference="arc.third-visit-rose"),
                When.fact("animal.bond_tier", ">=", 3),
                When.fact("season.current", "==", "autumn"),
            ),
            actions=(
                ActionCard("animal.present_gift", "arc.rabbit", {
                    "gift_id": "arc.autumn-gift",
                }),
                ActionCard.reveal("arc.autumn-gift", position=[28, 12]),
                ActionCard.show_memory(
                    f"{rabbit_name} brought this for {safe_recipient}, with no hurry and no obligation.",
                    label="Autumn gift",
                ),
                ActionCard.complete("arc.bonded-autumn-gift"),
            ),
            priority=100,
        ),
    ))
    return timeline


def validate_timeline(
    timeline: Timeline, *, known_letter_ids: set[str] | None = None,
    known_asset_ids: set[str] | None = None,
    plaintext_envelope: Mapping[str, Any] | None = None,
) -> tuple[AuthoringIssue, ...]:
    issues: list[AuthoringIssue] = []
    beat_ids = {beat.id for beat in timeline.beats}
    if len(beat_ids) != len(timeline.beats):
        issues.append(AuthoringIssue("duplicate_event", "beats", "Beat IDs must be unique."))
    targets = {str(entity.get("id")) for entity in timeline.entities + timeline.animals}
    dependency_graph: dict[str, set[str]] = {}
    exclusive: set[tuple[str, int]] = set()

    for path, text in _narrative_surfaces(timeline):
        violation = narrative_ethics_violation(text)
        if violation is not None:
            issues.append(AuthoringIssue(
                "prohibited_narrative", path,
                f"This {violation}/dark-pattern wording is not allowed.",
            ))

    for index, beat in enumerate(timeline.beats):
        path = f"beats[{index}]"
        if not beat.actions:
            issues.append(AuthoringIssue("no_actions", path, "This beat does not do anything."))
        if beat.occurrence not in {"auto", "once", "recurring"}:
            issues.append(AuthoringIssue(
                "invalid_occurrence", f"{path}.occurrence",
                "Choose once or recurring.",
            ))
        if _contradiction(beat.when):
            issues.append(AuthoringIssue("unreachable", f"{path}.when",
                                         "The conditions contradict one another."))
        dependencies = _condition_dependencies(beat.when)
        dependency_graph[beat.id] = dependencies
        for dependency in sorted(dependencies - beat_ids):
            issues.append(AuthoringIssue("missing_event_ref", f"{path}.when",
                                         f"Unknown prior beat {dependency}."))
        for leaf in _condition_leaves(beat.when):
            if leaf.fact_name in {"letter.read", "letter.due"} and leaf.reference:
                if known_letter_ids is not None and leaf.reference not in known_letter_ids:
                    issues.append(AuthoringIssue("missing_letter_ref", f"{path}.when",
                                                 f"Unknown letter {leaf.reference}."))
            if (
                leaf.fact_name in {
                    "gift.revealed", "gift.examined", "animal.arrived",
                    "plant.bloom", "fixture.present",
                }
                and leaf.reference is not None
                and leaf.reference not in targets
            ):
                issues.append(AuthoringIssue(
                    "missing_object_ref", f"{path}.when",
                    f"Unknown world object {leaf.reference}.",
                ))
        for action_index, action in enumerate(beat.actions):
            action_path = f"{path}.actions[{action_index}]"
            if action.type.startswith(("entity.", "animal.", "plant.")):
                if action.target not in targets:
                    issues.append(AuthoringIssue("missing_target", action_path,
                                                 f"Unknown world object {action.target}."))
            if action.type == "letter.present" and known_letter_ids is not None:
                letter_id = action.params.get("letter_id")
                if letter_id not in known_letter_ids:
                    issues.append(AuthoringIssue(
                        "missing_letter_ref", action_path,
                        f"Unknown letter {letter_id}.",
                    ))
        if beat.exclusive_group is not None:
            key = (beat.exclusive_group, beat.priority)
            if key in exclusive:
                issues.append(AuthoringIssue(
                    "ambiguous_exclusivity", path,
                    "Two exclusive beats have equal priority.",
                ))
            exclusive.add(key)
        if beat.schedule is not None:
            try:
                parse_schedule(beat.schedule)
            except ScheduleValidationError as exc:
                issues.extend(AuthoringIssue("invalid_schedule", f"{path}.schedule", message)
                              for message in exc.errors)

    for node in sorted(_cycle_nodes(dependency_graph)):
        issues.append(AuthoringIssue("dependency_cycle", f"beat:{node}",
                                     "Beat dependency is part of a cycle."))

    if known_asset_ids is not None:
        for index, entity in enumerate(timeline.entities):
            asset = entity.get("asset_id") or entity.get("catalog_id")
            if (
                entity.get("kind") not in {"plant"}
                and asset is not None and asset not in known_asset_ids
            ):
                issues.append(AuthoringIssue("missing_asset", f"entities[{index}]",
                                             f"Unknown atlas asset {asset}."))

    if plaintext_envelope:
        exposed = list(_strings(plaintext_envelope))
        private = [beat.title for beat in timeline.beats]
        for beat in timeline.beats:
            for action in beat.actions:
                if action.type == "narrative.show":
                    private.extend(str(value) for value in action.params.values() if value)
        private.extend(str(animal.get("name")) for animal in timeline.animals if animal.get("name"))
        for secret in private:
            if len(secret) >= 4 and any(secret in value for value in exposed):
                issues.append(AuthoringIssue(
                    "private_string_exposed", "plaintext_envelope",
                    "Narrative-bearing garden text appears outside encryption.",
                ))
                break
    return tuple(issues)


def compile_timeline(timeline: Timeline, **validation_context: Any) -> GardenProgram:
    issues = validate_timeline(timeline, **validation_context)
    blocking = tuple(issue for issue in issues if issue.blocking)
    if blocking:
        raise AuthoringValidationError(blocking)
    raw = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": timeline.atlas_version,
        "astronomy_catalog_version": timeline.astronomy_catalog_version,
        "author_timezone": timeline.author_timezone,
        "variables": dict(timeline.variables),
        "entities": [dict(entity) for entity in timeline.entities],
        "animals": [dict(animal) for animal in timeline.animals],
        "events": [
            {
                "id": beat.id, "conditions": beat.when.compile(),
                "schedule": dict(beat.schedule) if beat.schedule is not None else None,
                "occurrence": (
                    beat.occurrence if beat.occurrence in {"once", "recurring"}
                    else "recurring" if (
                        (beat.schedule and beat.schedule.get("recurrence")) or beat.cooldown
                    ) else "once"
                ),
                "priority": beat.priority, "exclusive_group": beat.exclusive_group,
                "cooldown": dict(beat.cooldown) if beat.cooldown is not None else None,
                "actions": [action.compile() for action in beat.actions],
            }
            for beat in timeline.beats
        ],
    }
    try:
        return parse_program(raw)
    except ProgramValidationError as exc:
        raise AuthoringValidationError(tuple(
            AuthoringIssue("program_schema", "program", error) for error in exc.errors
        )) from exc


def preview_timeline(timeline: Timeline, state: Mapping[str, Any],
                     context: Mapping[str, Any], **validation_context: Any) -> EvaluationResult:
    """Preview with the exact evaluator used by recipient runtimes."""
    return evaluate_program(compile_timeline(timeline, **validation_context), state, context)


def explain_trace(result: EvaluationResult) -> tuple[str, ...]:
    explanations: list[str] = []
    for row in result.trace:
        event = row["event_id"]
        if row["status"] == "applied":
            explanations.append(f"{event}: eligible; applied {row['effect_count']} action(s).")
        elif row["reason"] == "conditions_false":
            explanations.append(f"{event}: blocked because its when/if conditions were false.")
        elif row["reason"] == "schedule_not_eligible":
            explanations.append(f"{event}: blocked because no scheduled occurrence is due.")
        elif row["reason"] == "already_applied":
            explanations.append(f"{event}: already applied for this occurrence.")
        else:
            explanations.append(f"{event}: blocked by {row['reason'].replace('_', ' ')}.")
    return tuple(explanations)
