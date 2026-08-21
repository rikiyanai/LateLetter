"""
Offline question selector — Phase 1 prototype.

Implements the three-layer selection model from docs/SPEC.md §5.3:

  Layer 1: Universal base set (question_bank_seed.v0.json)
            20-30 reviewed prompts covering voice, relationship, values, love,
            hope, and practical wisdom. Mandatory session ramp — every session
            begins with 2-3 universals before domain questions are introduced.

  Layer 2: Domain-specific pools (question_bank_domain_pools.v0.json)
            Occasion pools (birthday, wedding, graduation, after_my_death,
            whenever_you_need_this) and relationship pools (child, partner,
            friend, sibling), plus six heavy/gated domains (apology, regret,
            fear, spiritual, permission, grief).

  Layer 3: Personalization — future. Hook point is the memory_tags field on
            SelectorSession and the tag-match scoring branch in _score().

Gating rules (from docs/SPEC.md §5.3):
  - Intensity 3 questions are never surfaced until intensity_3_unlocked is True.
  - intensity_3_unlocked becomes True after explicit author opt-in
    OR automatically after INTENSITY_3_AUTOGATE_AFTER questions in the session.
  - Heavy gated pool questions (apology, regret, fear, spiritual, permission,
    grief) are never selected first, regardless of intensity.
  - Prerequisites: if a question lists prerequisite IDs, all must have been
    asked (any session) before this question is eligible.

Session state:
  SelectorSession is a runtime object derived from session.json +
  questions_asked.json. It is serializable to selector_state.json but that
  file is optional and disposable — losing it does not destroy authored work.

Steerable controls:
  selector.next(session)                   — best next question
  selector.skip(session, question_id)      — skip current, return next best
  selector.easier(session, question_id)    — lower-intensity alternative
  selector.more_specific(session, q_id)   — occasion/relationship-specific alt

Usage:
  session = SelectorSession(
      occasion="birthday",
      relationship="child",
      memory_tags=["dogs", "hiking"],
      asked_all_sessions={"u-001", "u-003"},  # from questions_asked.json
  )
  selector = QuestionSelector.load(
      base_bank_path="src/lateletter/data/question_bank_seed.v0.json",
      domain_pools_path="src/lateletter/data/question_bank_domain_pools.v0.json",
  )
  q = selector.next(session)
  selector.mark_asked(session, q)
  q2 = selector.skip(session, q.question_id)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Question model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Question:
    question_id: str
    prompt: str
    domain: str
    intensity: int             # 1=easy/positive, 2=reflective, 3=heavy (gated)
    relationship_tags: tuple[str, ...]
    occasion_tags: tuple[str, ...]
    exclusion_flags: tuple[str, ...]
    prerequisites: tuple[str, ...] | None
    follow_up_hints: tuple[str, ...]
    source: str                # "universal" | "occasion:<key>" | "relationship:<key>" | "heavy:<key>"

    @classmethod
    def from_dict(cls, d: dict, source: str) -> "Question":
        return cls(
            question_id=d["question_id"],
            prompt=d["prompt"],
            domain=d["domain"],
            intensity=d["intensity"],
            relationship_tags=tuple(d.get("relationship_tags", [])),
            occasion_tags=tuple(d.get("occasion_tags", [])),
            exclusion_flags=tuple(d.get("exclusion_flags", [])),
            prerequisites=tuple(d["prerequisites"]) if d.get("prerequisites") else None,
            follow_up_hints=tuple(d.get("follow_up_hints", [])),
            source=source,
        )

    def is_heavy_gated(self) -> bool:
        return self.source.startswith("heavy:")

    def is_universal(self) -> bool:
        return self.source == "universal"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

# Number of questions asked before intensity-3 is auto-unlocked.
# Authors can also unlock it explicitly via unlock_intensity_3().
INTENSITY_3_AUTOGATE_AFTER = 5

# Number of universals required at the start of every session.
UNIVERSAL_RAMP_LENGTH = 3


@dataclass
class SelectorSession:
    """Runtime selector state for one authoring session (one message slot).

    Derived from session.json + questions_asked.json.
    Can be serialized to selector_state.json (optional, disposable).
    """

    # Intake context (from session.json)
    occasion: str       # "birthday" | "wedding" | "graduation" |
                        # "after my death" | "whenever you need this" | "general"
    relationship: str   # "child" | "partner" | "friend" | "sibling" | "general"
    memory_tags: list[str] = field(default_factory=list)

    # Cross-session dedup (loaded from questions_asked.json at startup)
    asked_all_sessions: set[str] = field(default_factory=set)

    # Per-session tracking
    asked_this_session: list[str] = field(default_factory=list)   # ordered
    skipped_this_session: set[str] = field(default_factory=set)
    domains_covered: set[str] = field(default_factory=set)

    # Gating state
    _intensity_3_unlocked: bool = field(default=False, repr=False)

    # ---- derived ----

    @property
    def position(self) -> int:
        """Number of questions answered this session."""
        return len(self.asked_this_session)

    @property
    def intensity_ceiling(self) -> int:
        """Max intensity surfaceable given current session progress."""
        if self._intensity_3_unlocked:
            return 3
        if self.position >= INTENSITY_3_AUTOGATE_AFTER:
            return 3
        return 2

    # ---- mutations ----

    def mark_asked(self, question_id: str, domain: str) -> None:
        self.asked_this_session.append(question_id)
        self.asked_all_sessions.add(question_id)
        self.domains_covered.add(domain)

    def mark_skipped(self, question_id: str) -> None:
        self.skipped_this_session.add(question_id)

    def unlock_intensity_3(self) -> None:
        """Explicit author opt-in for heavy/gated questions."""
        self._intensity_3_unlocked = True

    # ---- persistence helpers ----

    def to_dict(self) -> dict:
        return {
            "occasion": self.occasion,
            "relationship": self.relationship,
            "memory_tags": self.memory_tags,
            "asked_this_session": self.asked_this_session,
            "skipped_this_session": list(self.skipped_this_session),
            "domains_covered": list(self.domains_covered),
            "intensity_3_unlocked": self._intensity_3_unlocked,
            # asked_all_sessions not persisted here — lives in questions_asked.json
        }

    @classmethod
    def from_dict(cls, d: dict, asked_all_sessions: set[str]) -> "SelectorSession":
        obj = cls(
            occasion=d["occasion"],
            relationship=d["relationship"],
            memory_tags=d.get("memory_tags", []),
            asked_all_sessions=asked_all_sessions,
            asked_this_session=d.get("asked_this_session", []),
            skipped_this_session=set(d.get("skipped_this_session", [])),
            domains_covered=set(d.get("domains_covered", [])),
        )
        if d.get("intensity_3_unlocked"):
            obj.unlock_intensity_3()
        return obj


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

# Hard exclusions — scores below _HARD_EXCLUDE are filtered out entirely.
_HARD_EXCLUDE = -500

_W_REPEAT_ANY        = -1000   # asked in any previous session
_W_GATED             = -1000   # intensity > current ceiling
_W_PREREQ_UNMET      = -1000   # prerequisite not yet asked
_W_HEAVY_FIRST       = -1000   # heavy gated domain, session position == 0
_W_WRONG_RAMP        = -800    # non-universal question during universal ramp

_W_SKIP_PENALTY      = -30     # skipped this session (soft, can recover)

_W_OCCASION_MATCH    =  4      # occasion_tags contains session.occasion
_W_OCCASION_UNIV     =  1      # "universal" in occasion_tags (small bonus)
_W_RELATIONSHIP      =  3      # relationship_tags contains session.relationship (non-general)
_W_MEMORY_TAG        =  1      # per matching memory tag found in prompt text
_W_DOMAIN_NEW        =  2      # domain not yet covered this session
_W_OPENER            =  3      # designated session-opener question, early in session

_W_UNIVERSAL_EARLY   =  2      # universal source bonus for early session positions
_W_SPECIFIC_BONUS    =  6      # bonus for non-universal in more_specific mode
_W_EASIER_EXACT      =  6      # exact target intensity in easier mode
_W_EASIER_LOWER      =  3      # below target intensity in easier mode

# Normalize occasion strings: "after my death" -> "after my death" (keep as-is,
# match against both the tag form and the normalized form).
def _normalize_occasion(occasion: str) -> str:
    return occasion.strip().lower()


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

class QuestionSelector:
    """Offline question selector implementing docs/SPEC.md §5.3 layered model.

    Stateless — all session state lives in SelectorSession.
    Load once, reuse across sessions.
    """

    def __init__(
        self,
        questions: list[Question],
        session_openers: set[str],
    ):
        self._all: list[Question] = questions
        self._by_id: dict[str, Question] = {q.question_id: q for q in questions}
        self._session_openers: set[str] = session_openers

    # ---- construction ----

    @classmethod
    def load(
        cls,
        base_bank_path: Path | str,
        domain_pools_path: Path | str,
    ) -> "QuestionSelector":
        """Load universal base set + domain pools. Returns configured selector."""
        base_bank_path = Path(base_bank_path)
        domain_pools_path = Path(domain_pools_path)

        try:
            base_text = base_bank_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Question bank not found: {base_bank_path}") from exc
        try:
            base_data = json.loads(base_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Malformed question bank JSON: {base_bank_path}") from exc

        try:
            pool_text = domain_pools_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Domain pools file not found: {domain_pools_path}") from exc
        try:
            pool_data = json.loads(pool_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Malformed domain pools JSON: {domain_pools_path}") from exc

        questions: list[Question] = []

        # Layer 1: universal base set
        session_openers: set[str] = set(
            base_data.get("editorial_metadata", {}).get("session_openers", [])
        )
        try:
            for q_dict in base_data["questions"]:
                questions.append(Question.from_dict(q_dict, source="universal"))
        except KeyError as exc:
            raise RuntimeError(
                f"Question bank missing required field {exc}: {base_bank_path}"
            ) from exc

        # Layer 2: domain-specific pools
        pools = pool_data.get("pools", {})

        try:
            for occasion_key, pool in pools.get("occasion", {}).items():
                for q_dict in pool["questions"]:
                    questions.append(Question.from_dict(q_dict, source=f"occasion:{occasion_key}"))

            for rel_key, pool in pools.get("relationship", {}).items():
                for q_dict in pool["questions"]:
                    questions.append(Question.from_dict(q_dict, source=f"relationship:{rel_key}"))

            for domain_key, pool in pools.get("heavy_gated", {}).items():
                for q_dict in pool["questions"]:
                    questions.append(Question.from_dict(q_dict, source=f"heavy:{domain_key}"))
        except KeyError as exc:
            raise RuntimeError(
                f"Domain pools file missing required field {exc}: {domain_pools_path}"
            ) from exc

        return cls(questions, session_openers)

    # ---- public API ----

    def next(self, session: SelectorSession) -> Optional[Question]:
        """Return the best next question for this session state."""
        ranked = self._rank(session)
        return ranked[0][1] if ranked else None

    def skip(
        self,
        session: SelectorSession,
        current_question_id: str,
    ) -> Optional[Question]:
        """Mark current_question_id as skipped. Return next best question."""
        session.mark_skipped(current_question_id)
        ranked = self._rank(session, exclude={current_question_id})
        return ranked[0][1] if ranked else None

    def easier(
        self,
        session: SelectorSession,
        current_question_id: str,
    ) -> Optional[Question]:
        """Return a lower-intensity alternative to the current question.

        Prefers questions with intensity strictly less than the current one.
        Falls back to any eligible question if no strictly easier one exists.
        """
        current = self._by_id.get(current_question_id)
        ranked = self._rank(session, exclude={current_question_id}, easier_mode=True)

        if current:
            softer = [(s, q) for s, q in ranked if q.intensity < current.intensity]
            if softer:
                return softer[0][1]

        return ranked[0][1] if ranked else None

    def more_specific(
        self,
        session: SelectorSession,
        current_question_id: str,
    ) -> Optional[Question]:
        """Return a more occasion/relationship-specific alternative.

        Prefers questions from occasion or relationship pools over universals.
        """
        ranked = self._rank(session, exclude={current_question_id}, specific_mode=True)

        # Prefer non-universal sources
        specific = [(s, q) for s, q in ranked if not q.is_universal()]
        if specific:
            return specific[0][1]

        return ranked[0][1] if ranked else None

    def mark_asked(self, session: SelectorSession, question: Question) -> None:
        """Record that question was answered. Updates session state."""
        session.mark_asked(question.question_id, question.domain)

    def get(self, question_id: str) -> Optional[Question]:
        return self._by_id.get(question_id)

    def available_count(self, session: SelectorSession) -> int:
        """Count questions not yet asked and not gated out."""
        return sum(1 for q in self._all if not self._hard_excluded(q, session))

    # ---- internal scoring ----

    def _hard_excluded(self, q: Question, session: SelectorSession) -> bool:
        """True if this question must never appear (ignore, don't score)."""
        if q.question_id in session.asked_all_sessions:
            return True
        if q.intensity > session.intensity_ceiling:
            return True
        if q.prerequisites:
            if any(p not in session.asked_all_sessions for p in q.prerequisites):
                return True
        return False

    def _score(
        self,
        q: Question,
        session: SelectorSession,
        *,
        easier_mode: bool = False,
        specific_mode: bool = False,
    ) -> int:
        # Hard exclusions
        if self._hard_excluded(q, session):
            return _W_GATED  # all hard-exclusions share the same floor

        score = 0

        # --- Universal ramp enforcement ---
        # First UNIVERSAL_RAMP_LENGTH questions must be from the universal base set.
        if session.position < UNIVERSAL_RAMP_LENGTH:
            if not q.is_universal():
                return _W_WRONG_RAMP
            # Within ramp, reward designated openers
            if q.question_id in self._session_openers:
                score += _W_OPENER

        # --- Heavy gated domain never first ---
        if session.position == 0 and q.is_heavy_gated():
            return _W_HEAVY_FIRST

        # --- Soft skip penalty ---
        if q.question_id in session.skipped_this_session:
            score += _W_SKIP_PENALTY

        # --- Occasion relevance ---
        occ = _normalize_occasion(session.occasion)
        if any(_normalize_occasion(t) == occ for t in q.occasion_tags):
            score += _W_OCCASION_MATCH
        elif "universal" in q.occasion_tags:
            score += _W_OCCASION_UNIV

        # --- Relationship relevance ---
        if session.relationship in q.relationship_tags:
            score += _W_RELATIONSHIP
        # "general" relationship_tag gives no bonus — it's the default, not a match

        # --- Memory tag matching (layer 3 hook) ---
        prompt_lower = q.prompt.lower()
        for tag in session.memory_tags:
            if tag.lower() in prompt_lower:
                score += _W_MEMORY_TAG

        # --- Coverage balance: reward domains not yet touched ---
        if q.domain not in session.domains_covered:
            score += _W_DOMAIN_NEW

        # --- Early-session universal preference (when not in specific mode) ---
        if session.position < UNIVERSAL_RAMP_LENGTH + 2 and not specific_mode:
            if q.is_universal():
                score += _W_UNIVERSAL_EARLY

        # --- Mode bonuses ---
        if easier_mode:
            target = max(1, session.intensity_ceiling - 1)
            if q.intensity == target:
                score += _W_EASIER_EXACT
            elif q.intensity < target:
                score += _W_EASIER_LOWER

        if specific_mode and not q.is_universal():
            score += _W_SPECIFIC_BONUS

        return score

    def _rank(
        self,
        session: SelectorSession,
        exclude: set[str] | None = None,
        *,
        easier_mode: bool = False,
        specific_mode: bool = False,
    ) -> list[tuple[int, Question]]:
        """Return all eligible questions sorted by score descending."""
        exclude = exclude or set()
        scored: list[tuple[int, Question]] = []

        for q in self._all:
            if q.question_id in exclude:
                continue
            s = self._score(q, session, easier_mode=easier_mode, specific_mode=specific_mode)
            if s > _HARD_EXCLUDE:
                scored.append((s, q))

        scored.sort(key=lambda x: (-x[0], x[1].question_id))
        return scored
