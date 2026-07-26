"""
Tests for the offline question selector.

Covers:
  - Universal ramp: first questions must be universal base-set
  - Intensity gating: intensity-3 never surfaced until unlocked
  - Prerequisite gating: questions blocked until prerequisites met
  - Heavy domain gating: heavy pool never selected first
  - Dedup: asked questions never re-surfaced
  - Skip: skipped question deprioritized, next returned
  - Easier: lower-intensity alternative returned
  - More specific: occasion/relationship-specific preferred
  - Auto-unlock: intensity-3 surfaced after INTENSITY_3_AUTOGATE_AFTER questions
  - Explicit unlock: intensity_3_unlocked enables gated questions immediately
  - Coverage balance: selector prefers domains not yet touched
  - Occasion match: occasion-specific questions scored above universals
  - Relationship match: relationship-specific questions scored above universals

Run with:
  python -m pytest tests/test_question_selector.py -v
"""

import pytest
from pathlib import Path

from src.lateletter.question_selector import (
    Question,
    QuestionSelector,
    SelectorSession,
    UNIVERSAL_RAMP_LENGTH,
    INTENSITY_3_AUTOGATE_AFTER,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data"
BASE_BANK = DATA_DIR / "question_bank_seed.v0.json"
DOMAIN_POOLS = DATA_DIR / "question_bank_domain_pools.v0.json"


@pytest.fixture(scope="module")
def selector():
    return QuestionSelector.load(BASE_BANK, DOMAIN_POOLS)


def fresh_session(**kwargs) -> SelectorSession:
    defaults = dict(occasion="birthday", relationship="child", memory_tags=[])
    defaults.update(kwargs)
    return SelectorSession(**defaults)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoading:
    def test_loads_questions(self, selector):
        assert len(selector._all) > 100

    def test_universal_questions_present(self, selector):
        universals = [q for q in selector._all if q.is_universal()]
        assert len(universals) >= 20

    def test_session_openers_populated(self, selector):
        assert len(selector._session_openers) > 0

    def test_all_questions_have_ids(self, selector):
        for q in selector._all:
            assert q.question_id, f"Empty question_id: {q}"

    def test_no_duplicate_ids(self, selector):
        ids = [q.question_id for q in selector._all]
        assert len(ids) == len(set(ids)), "Duplicate question IDs found"

    def test_intensity_values_valid(self, selector):
        for q in selector._all:
            assert q.intensity in (1, 2, 3), f"Invalid intensity {q.intensity} on {q.question_id}"

    def test_heavy_pool_sources_correct(self, selector):
        heavy = [q for q in selector._all if q.is_heavy_gated()]
        assert len(heavy) > 0
        for q in heavy:
            assert q.source.startswith("heavy:")


# ---------------------------------------------------------------------------
# Universal ramp
# ---------------------------------------------------------------------------

class TestUniversalRamp:
    def test_first_question_is_universal(self, selector):
        session = fresh_session()
        q = selector.next(session)
        assert q is not None
        assert q.is_universal(), f"Expected universal, got source={q.source}"

    def test_first_n_questions_are_universal(self, selector):
        session = fresh_session()
        for i in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            assert q is not None, f"No question available at position {i}"
            assert q.is_universal(), f"Position {i}: expected universal, got {q.source}"
            selector.mark_asked(session, q)

    def test_after_ramp_domain_questions_available(self, selector):
        session = fresh_session(occasion="birthday", relationship="child")
        # exhaust universal ramp
        for _ in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            assert q is not None
            selector.mark_asked(session, q)
        # now domain-specific questions should be eligible
        q = selector.next(session)
        assert q is not None
        # it may still be universal (scoring), but should not be _forced_ universal
        # the key check: domain questions are not excluded
        ranked = selector._rank(session)
        sources = [q.source for _, q in ranked[:10]]
        assert any(s != "universal" for s in sources), \
            "No domain questions eligible after universal ramp"

    def test_opener_questions_preferred_in_ramp(self, selector):
        session = fresh_session()
        q = selector.next(session)
        assert q is not None
        # The first question should be a designated session opener
        assert q.question_id in selector._session_openers, \
            f"Expected session opener, got {q.question_id}"


# ---------------------------------------------------------------------------
# Intensity gating
# ---------------------------------------------------------------------------

class TestIntensityGating:
    def test_intensity_3_not_surfaced_by_default(self, selector):
        session = fresh_session()
        ranked = selector._rank(session)
        for score, q in ranked:
            if score > -500:
                assert q.intensity <= 2, \
                    f"Intensity-3 question surfaced before unlock: {q.question_id}"

    def test_intensity_3_surfaced_after_explicit_unlock(self, selector):
        session = fresh_session()
        # Ask enough questions to have some session history
        for _ in range(3):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)
        session.unlock_intensity_3()

        ranked = selector._rank(session)
        eligible_ids = {q.question_id for _, q in ranked if _ > -500}
        intensity3_ids = {q.question_id for q in selector._all if q.intensity == 3}
        # At least some intensity-3 questions should now be eligible
        # (prerequisites may block some, but not all)
        assert len(eligible_ids & intensity3_ids) > 0, \
            "No intensity-3 questions eligible after explicit unlock"

    def test_intensity_3_auto_unlocked_after_n_questions(self, selector):
        session = fresh_session()
        assert session.intensity_ceiling == 2
        for i in range(INTENSITY_3_AUTOGATE_AFTER):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)
        assert session.intensity_ceiling == 3

    def test_intensity_ceiling_before_autogate(self, selector):
        session = fresh_session()
        for i in range(INTENSITY_3_AUTOGATE_AFTER - 1):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)
        assert session.intensity_ceiling == 2


# ---------------------------------------------------------------------------
# Prerequisite gating
# ---------------------------------------------------------------------------

class TestPrerequisiteGating:
    def test_question_with_unmet_prereq_not_surfaced(self, selector):
        # Find a question with a prerequisite
        gated = [q for q in selector._all if q.prerequisites]
        if not gated:
            pytest.skip("No questions with prerequisites in bank")

        sample = gated[0]
        prereq_id = sample.prerequisites[0]

        session = fresh_session()
        # Do not ask the prerequisite
        ranked = selector._rank(session)
        eligible_ids = {q.question_id for _, q in ranked if _ > -500}
        assert sample.question_id not in eligible_ids, \
            f"{sample.question_id} surfaced before prerequisite {prereq_id} was asked"

    def test_question_with_met_prereq_becomes_eligible(self, selector):
        gated = [q for q in selector._all if q.prerequisites and q.intensity <= 2]
        if not gated:
            pytest.skip("No non-intensity-3 questions with prerequisites")

        sample = gated[0]
        prereq_id = sample.prerequisites[0]

        session = fresh_session()
        session.unlock_intensity_3()
        # Manually mark prerequisite as asked
        session.asked_all_sessions.add(prereq_id)

        ranked = selector._rank(session)
        eligible_ids = {q.question_id for _, q in ranked if _ > -500}
        assert sample.question_id in eligible_ids, \
            f"{sample.question_id} not surfaced after prerequisite {prereq_id} met"


# ---------------------------------------------------------------------------
# Heavy domain never first
# ---------------------------------------------------------------------------

class TestHeavyDomainGating:
    def test_heavy_domain_not_surfaced_first(self, selector):
        session = fresh_session()
        assert session.position == 0
        ranked = selector._rank(session)
        top = ranked[0][1] if ranked else None
        assert top is not None
        assert not top.is_heavy_gated(), \
            f"Heavy domain question surfaced as first question: {top.question_id}"

    def test_heavy_domain_eligible_later(self, selector):
        session = fresh_session()
        session.unlock_intensity_3()
        # Must advance past the full universal ramp before domain questions are eligible
        for _ in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)

        ranked = selector._rank(session)
        heavy_eligible = [q for _, q in ranked if q.is_heavy_gated() and _ > -500]
        assert len(heavy_eligible) > 0, \
            "No heavy-gated questions eligible after full ramp completion and unlock"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDedup:
    def test_asked_question_not_re_surfaced(self, selector):
        session = fresh_session()
        q = selector.next(session)
        assert q is not None
        selector.mark_asked(session, q)
        # question should no longer appear in ranked list
        ranked = selector._rank(session)
        eligible_ids = {qq.question_id for _, qq in ranked if _ > -500}
        assert q.question_id not in eligible_ids

    def test_cross_session_dedup(self, selector):
        # Pre-populate asked_all_sessions with a specific question
        q_id = "u-001"
        session = fresh_session(asked_all_sessions={q_id})
        ranked = selector._rank(session)
        eligible_ids = {q.question_id for _, q in ranked if _ > -500}
        assert q_id not in eligible_ids

    def test_exhausting_universals_falls_through_to_domain(self, selector):
        session = fresh_session(occasion="birthday", relationship="child")
        universal_ids = {q.question_id for q in selector._all if q.is_universal()}
        session.asked_all_sessions = universal_ids.copy()
        # force ramp to pass
        session.asked_this_session = list(universal_ids)[:UNIVERSAL_RAMP_LENGTH]
        session.domains_covered = {"voice", "relationship"}  # some covered
        q = selector.next(session)
        assert q is not None, "No question available after universals exhausted"
        assert not q.is_universal()


# ---------------------------------------------------------------------------
# Skip
# ---------------------------------------------------------------------------

class TestSkip:
    def test_skip_returns_different_question(self, selector):
        session = fresh_session()
        q1 = selector.next(session)
        assert q1 is not None
        q2 = selector.skip(session, q1.question_id)
        assert q2 is not None
        assert q2.question_id != q1.question_id

    def test_skipped_question_deprioritized(self, selector):
        session = fresh_session()
        q1 = selector.next(session)
        assert q1 is not None
        selector.skip(session, q1.question_id)
        # Re-rank: skipped question should not be at the top
        ranked = selector._rank(session)
        top = ranked[0][1] if ranked else None
        # skipped is penalized but not excluded — if it's somehow the only option
        # it may still appear. But in a full bank it should not be first.
        if top and len(ranked) > 1:
            assert top.question_id != q1.question_id, \
                "Skipped question reappeared at top of ranking"

    def test_skip_marks_session_state(self, selector):
        session = fresh_session()
        q1 = selector.next(session)
        assert q1 is not None
        selector.skip(session, q1.question_id)
        assert q1.question_id in session.skipped_this_session


# ---------------------------------------------------------------------------
# Easier
# ---------------------------------------------------------------------------

class TestEasier:
    def test_easier_returns_lower_intensity_when_available(self, selector):
        # Find an intensity-2 question that has intensity-1 questions not yet asked
        session = fresh_session()
        # Advance past the ramp so intensity-2 questions are eligible
        for _ in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)

        # Find an intensity-2 question to call easier on
        ranked = selector._rank(session)
        intensity2 = next(
            (q for _, q in ranked if q.intensity == 2 and _ > -500), None
        )
        if intensity2 is None:
            pytest.skip("No intensity-2 questions available after ramp")

        easier_q = selector.easier(session, intensity2.question_id)
        assert easier_q is not None
        assert easier_q.intensity < intensity2.intensity, \
            f"easier() returned same or higher intensity: {easier_q.intensity}"

    def test_easier_does_not_return_same_question(self, selector):
        session = fresh_session()
        q = selector.next(session)
        if q:
            easier_q = selector.easier(session, q.question_id)
            if easier_q:
                assert easier_q.question_id != q.question_id


# ---------------------------------------------------------------------------
# More specific
# ---------------------------------------------------------------------------

class TestMoreSpecific:
    def test_more_specific_prefers_non_universal(self, selector):
        session = fresh_session(occasion="birthday", relationship="child")
        # Advance past ramp
        for _ in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)

        q_current = selector.next(session)
        if q_current is None:
            pytest.skip("No current question")

        specific_q = selector.more_specific(session, q_current.question_id)
        if specific_q:
            # Should prefer occasion or relationship source
            assert specific_q.source != "universal" or q_current.source != "universal", \
                "more_specific returned a universal when domain-specific were available"

    def test_more_specific_does_not_return_same_question(self, selector):
        session = fresh_session()
        q = selector.next(session)
        if q:
            specific_q = selector.more_specific(session, q.question_id)
            if specific_q:
                assert specific_q.question_id != q.question_id


# ---------------------------------------------------------------------------
# Occasion and relationship scoring
# ---------------------------------------------------------------------------

class TestScoring:
    def test_birthday_questions_rank_above_universals_for_birthday_session(self, selector):
        session = fresh_session(occasion="birthday", relationship="general")
        # Advance past ramp
        for _ in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)

        ranked = selector._rank(session)
        top10 = [q for _, q in ranked[:10]]
        birthday_in_top10 = any(
            "birthday" in q.occasion_tags for q in top10
        )
        assert birthday_in_top10, \
            "No birthday-tagged question in top 10 for a birthday session"

    def test_relationship_questions_rank_for_matching_relationship(self, selector):
        session = fresh_session(occasion="general", relationship="child")
        for _ in range(UNIVERSAL_RAMP_LENGTH):
            q = selector.next(session)
            if q:
                selector.mark_asked(session, q)

        ranked = selector._rank(session)
        top20 = [q for _, q in ranked[:20]]
        child_q = any(
            "child" in q.relationship_tags for q in top20
        )
        assert child_q, "No child-relationship question in top 20 for child session"

    def test_coverage_balance_introduces_new_domains(self, selector):
        session = fresh_session()
        # Cover one domain heavily
        session.domains_covered.add("voice")
        # Rank: questions in "voice" domain should be penalized vs. others
        ranked = selector._rank(session)
        if len(ranked) >= 2:
            top_domains = [q.domain for _, q in ranked[:5]]
            # Should have variety, not all "voice"
            assert len(set(top_domains)) > 1, \
                "Coverage balance not working — all top questions in same domain"


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

class TestSessionState:
    def test_mark_asked_updates_position(self, selector):
        session = fresh_session()
        assert session.position == 0
        q = selector.next(session)
        assert q is not None
        selector.mark_asked(session, q)
        assert session.position == 1

    def test_mark_asked_updates_domains_covered(self, selector):
        session = fresh_session()
        q = selector.next(session)
        assert q is not None
        assert q.domain not in session.domains_covered or True  # may already be empty
        selector.mark_asked(session, q)
        assert q.domain in session.domains_covered

    def test_to_dict_roundtrip(self, selector):
        session = fresh_session(
            occasion="wedding",
            relationship="partner",
            memory_tags=["italy", "cooking"],
        )
        q = selector.next(session)
        if q:
            selector.mark_asked(session, q)

        d = session.to_dict()
        restored = SelectorSession.from_dict(d, asked_all_sessions=session.asked_all_sessions)
        assert restored.occasion == session.occasion
        assert restored.relationship == session.relationship
        assert restored.asked_this_session == session.asked_this_session
        assert restored.domains_covered == session.domains_covered

    def test_available_count_decreases_as_asked(self, selector):
        session = fresh_session()
        # Find a leaf question — one that is NOT a prerequisite for any other question.
        # Asking a prerequisite-source question may unblock dependents, keeping count stable.
        all_prereq_sources: set[str] = set()
        for q in selector._all:
            if q.prerequisites:
                all_prereq_sources.update(q.prerequisites)

        leaf_questions = [
            q for q in selector._all
            if q.question_id not in all_prereq_sources
            and q.intensity <= 2
            and not q.prerequisites
        ]
        assert leaf_questions, "No leaf questions found in bank"

        target = leaf_questions[0]
        initial = selector.available_count(session)
        selector.mark_asked(session, target)
        assert selector.available_count(session) < initial, \
            "available_count did not decrease after asking a leaf question"
