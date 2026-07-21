"""
Tests for SessionResumer — session resumption flow.

All tests use injected input_fn/output_fn to avoid real I/O.
"""

from pathlib import Path
import warnings

import pytest

from src.lateletter.qa_loop import DEFAULT_EXCHANGE_TARGET, QALoop
from src.lateletter.question_selector import QuestionSelector, SelectorSession
from src.lateletter.session_resumer import SessionResumer
from src.lateletter.session_store import SessionStore

DATA_DIR = Path(__file__).parent.parent / "src" / "lateletter" / "data"
BASE_BANK = DATA_DIR / "question_bank_seed.v0.json"
DOMAIN_POOLS = DATA_DIR / "question_bank_domain_pools.v0.json"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def selector():
    return QuestionSelector.load(BASE_BANK, DOMAIN_POOLS)


@pytest.fixture
def store(tmp_path):
    return SessionStore(base_dir=tmp_path)


def make_resumer(
    selector,
    store,
    inputs: list[str],
    *,
    message_id: str = "test-msg-001",
    occasion: str = "birthday",
    relationship: str = "child",
) -> tuple[SessionResumer, list[str]]:
    output_lines: list[str] = []
    input_iter = iter(inputs)

    resumer = SessionResumer(
        selector=selector,
        store=store,
        message_id=message_id,
        occasion=occasion,
        relationship=relationship,
        exchange_target=5,
        input_fn=lambda: next(input_iter),
        output_fn=output_lines.append,
    )
    return resumer, output_lines


def _write_prior_session(store, message_id, answers):
    """Seed session.json with prior qa_answers for resumption tests."""
    store.upsert_message(message_id, {
        "qa_answers": answers,
        "qa_exchange_target": 5,
        "qa_exchange_count": len(answers),
        "qa_complete": False,
    })


_PRIOR_ANSWER = {
    "question_id": "u-001",
    "question_text": "How would you describe yourself to someone who has never met you?",
    "answer": "I am a person who loves deeply.",
    "asked_at": "2026-01-01T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Fresh session (no prior answers)
# ---------------------------------------------------------------------------

class TestFreshSession:
    def test_no_prompt_when_no_prior_answers(self, selector, store):
        resumer, output = make_resumer(selector, store, ["done"])
        resumer.prepare()
        combined = " ".join(output)
        assert "Resume" not in combined

    def test_returns_qaloop_instance(self, selector, store):
        resumer, _ = make_resumer(selector, store, ["done"])
        loop = resumer.prepare()
        assert isinstance(loop, QALoop)

    def test_fresh_loop_has_no_prior_answers(self, selector, store):
        resumer, _ = make_resumer(selector, store, ["done"])
        loop = resumer.prepare()
        result = loop.run()
        assert len(result.answers) == 0

    def test_fresh_session_uses_correct_occasion(self, selector, store):
        resumer, _ = make_resumer(
            selector, store, ["done"], occasion="wedding", relationship="partner"
        )
        loop = resumer.prepare()
        assert loop.session.occasion == "wedding"
        assert loop.session.relationship == "partner"


# ---------------------------------------------------------------------------
# Resume prompt — user chooses 'y'
# ---------------------------------------------------------------------------

class TestResumeYes:
    def test_prompt_shown_when_prior_answers_exist(self, selector, store):
        _write_prior_session(store, "msg-r1", [_PRIOR_ANSWER])
        resumer, output = make_resumer(selector, store, ["y", "done"], message_id="msg-r1")
        resumer.prepare()
        combined = " ".join(output)
        assert "Resume" in combined

    def test_prompt_shows_count_of_prior_answers(self, selector, store):
        _write_prior_session(store, "msg-r2", [_PRIOR_ANSWER])
        resumer, output = make_resumer(selector, store, ["y", "done"], message_id="msg-r2")
        resumer.prepare()
        combined = " ".join(output)
        assert "1" in combined

    def test_resume_yes_loads_prior_answers_into_loop(self, selector, store):
        _write_prior_session(store, "msg-r3", [_PRIOR_ANSWER])
        resumer, _ = make_resumer(
            selector, store,
            ["y", "New answer", "", "done"],
            message_id="msg-r3",
        )
        loop = resumer.prepare()
        result = loop.run()
        assert result.answers[0].answer == "I am a person who loves deeply."
        assert result.answers[1].answer == "New answer"

    def test_resume_yes_prior_question_not_re_asked(self, selector, store):
        _write_prior_session(store, "msg-r4", [_PRIOR_ANSWER])
        resumer, _ = make_resumer(
            selector, store,
            ["y", "New answer", "", "done"],
            message_id="msg-r4",
        )
        loop = resumer.prepare()
        result = loop.run()
        new_ids = [a.question_id for a in result.answers if a.asked_at != "2026-01-01T00:00:00+00:00"]
        assert "u-001" not in new_ids

    def test_resume_yes_complete_flag_correct_on_target(self, selector, store):
        prior = [_PRIOR_ANSWER]
        _write_prior_session(store, "msg-r5", prior)
        # 4 more answers → total 5 → complete
        qa_inputs = []
        for _ in range(4):
            qa_inputs += ["Answer", ""]
        resumer, _ = make_resumer(
            selector, store,
            ["y"] + qa_inputs,
            message_id="msg-r5",
        )
        loop = resumer.prepare()
        result = loop.run()
        assert result.complete is True


# ---------------------------------------------------------------------------
# Resume prompt — user chooses 'n'
# ---------------------------------------------------------------------------

class TestResumeNo:
    def test_resume_no_starts_fresh_loop(self, selector, store):
        _write_prior_session(store, "msg-n1", [_PRIOR_ANSWER])
        resumer, _ = make_resumer(
            selector, store,
            ["n", "Brand new answer", "", "done"],
            message_id="msg-n1",
        )
        loop = resumer.prepare()
        result = loop.run()
        # Only the new answer should be in the result (prior not loaded)
        assert result.answers[0].answer == "Brand new answer"
        assert len([a for a in result.answers if a.answer == "I am a person who loves deeply."]) == 0

    def test_resume_no_prior_answers_remain_in_store(self, selector, store):
        _write_prior_session(store, "msg-n2", [_PRIOR_ANSWER])
        resumer, _ = make_resumer(selector, store, ["n", "done"], message_id="msg-n2")
        resumer.prepare()
        msg = store.get_message("msg-n2")
        # The prior session data is still in session.json as notes
        assert msg is not None
        assert len(msg["qa_answers"]) == 1

    def test_eof_on_resume_prompt_defaults_to_no(self, selector, store):
        _write_prior_session(store, "msg-n3", [_PRIOR_ANSWER])
        output_lines: list[str] = []
        inputs = iter([])  # empty — raises StopIteration on first call inside EOFError handler

        def _eof_input():
            raise EOFError

        resumer = SessionResumer(
            selector=selector,
            store=store,
            message_id="msg-n3",
            occasion="birthday",
            relationship="child",
            exchange_target=5,
            input_fn=_eof_input,
            output_fn=output_lines.append,
        )
        loop = resumer.prepare()
        # EOFError → treated as 'n' → prior answers NOT loaded
        assert len(loop._answers) == 0


# ---------------------------------------------------------------------------
# SelectorSession restoration
# ---------------------------------------------------------------------------

class TestSessionRestoration:
    def test_restore_from_selector_state_json(self, selector, store):
        """If selector_state.json exists for the message, it should be used."""
        state = {
            "occasion": "birthday",
            "relationship": "child",
            "memory_tags": [],
            "asked_this_session": ["u-003"],
            "skipped_this_session": ["u-005"],
            "domains_covered": ["voice"],
            "intensity_3_unlocked": False,
        }
        store.save_selector_state("msg-restore", state)
        # Also record u-003 as asked so asked_all_sessions is consistent
        store.record_question_asked("u-003", "Q", "msg-restore")

        resumer, _ = make_resumer(selector, store, ["done"], message_id="msg-restore")
        loop = resumer.prepare()
        # Skipped and domain state should be restored
        assert "u-005" in loop.session.skipped_this_session
        assert "voice" in loop.session.domains_covered

    def test_reconstruct_when_no_selector_state_json(self, selector, store):
        """No selector_state.json → fresh SelectorSession with asked_all_sessions from store."""
        store.record_question_asked("u-002", "Q", "msg-recon")
        resumer, _ = make_resumer(selector, store, ["done"], message_id="msg-recon")
        loop = resumer.prepare()
        assert "u-002" in loop.session.asked_all_sessions

    def test_selector_state_for_different_message_not_used(self, selector, store):
        """selector_state.json for a different message_id should be ignored."""
        state = {
            "occasion": "wedding",
            "relationship": "partner",
            "memory_tags": [],
            "asked_this_session": [],
            "skipped_this_session": ["u-010"],
            "domains_covered": [],
            "intensity_3_unlocked": False,
        }
        store.save_selector_state("other-msg", state)
        resumer, _ = make_resumer(selector, store, ["done"], message_id="msg-different")
        loop = resumer.prepare()
        # Should be a fresh session, not the wedding one
        assert loop.session.occasion == "birthday"
        assert "u-010" not in loop.session.skipped_this_session


# ---------------------------------------------------------------------------
# Split-state reconciliation (ADV-003 fix)
# ---------------------------------------------------------------------------

class TestSplitStateReconciliation:
    def test_heals_missing_id_in_questions_asked(self, selector, store):
        """qa_answers in session.json but absent from questions_asked.json → back-filled."""
        # Write session.json directly with qa_answers but skip questions_asked.json
        store.upsert_message("msg-split", {
            "qa_answers": [_PRIOR_ANSWER],
            "qa_exchange_count": 1,
            "qa_exchange_target": 5,
            "qa_complete": False,
        })
        # questions_asked.json has nothing for u-001
        assert "u-001" not in store.asked_question_ids()

        with warnings.catch_warnings(record=True):
            resumer, _ = make_resumer(selector, store, ["n", "done"], message_id="msg-split")
            resumer.prepare()

        # After prepare(), u-001 should be healed into questions_asked.json
        assert "u-001" in store.asked_question_ids()

    def test_no_duplicate_after_reconciliation(self, selector, store):
        """Reconciliation must not add duplicates if the ID is already present."""
        store.record_question_asked("u-001", _PRIOR_ANSWER["question_text"], "msg-nodup")
        store.upsert_message("msg-nodup", {
            "qa_answers": [_PRIOR_ANSWER],
            "qa_exchange_count": 1,
            "qa_exchange_target": 5,
            "qa_complete": False,
        })
        with warnings.catch_warnings(record=True):
            resumer, _ = make_resumer(selector, store, ["n", "done"], message_id="msg-nodup")
            resumer.prepare()

        ids = [e["question_id"] for e in store.load_questions_asked()]
        assert ids.count("u-001") == 1

    def test_healed_question_excluded_from_selection(self, selector, store):
        """After reconciliation, the healed question must not be re-offered."""
        store.upsert_message("msg-excl", {
            "qa_answers": [_PRIOR_ANSWER],
            "qa_exchange_count": 1,
            "qa_exchange_target": 5,
            "qa_complete": False,
        })
        with warnings.catch_warnings(record=True):
            resumer, _ = make_resumer(
                selector, store, ["n", "New answer", "", "done"], message_id="msg-excl"
            )
            loop = resumer.prepare()
            result = loop.run()

        new_ids = [
            a.question_id for a in result.answers
            if a.asked_at != "2026-01-01T00:00:00+00:00"
        ]
        assert "u-001" not in new_ids

    def test_warning_issued_when_state_healed(self, selector, store):
        store.upsert_message("msg-warn", {
            "qa_answers": [_PRIOR_ANSWER],
            "qa_exchange_count": 1,
            "qa_exchange_target": 5,
            "qa_complete": False,
        })
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resumer, _ = make_resumer(selector, store, ["n", "done"], message_id="msg-warn")
            resumer.prepare()

        messages = [str(w.message) for w in caught]
        assert any("split" in m.lower() or "heal" in m.lower() for m in messages)

    def test_no_warning_when_state_consistent(self, selector, store):
        """No warning if questions_asked.json already has all the IDs."""
        store.record_question_asked("u-001", _PRIOR_ANSWER["question_text"], "msg-ok")
        store.upsert_message("msg-ok", {
            "qa_answers": [_PRIOR_ANSWER],
            "qa_exchange_count": 1,
            "qa_exchange_target": 5,
            "qa_complete": False,
        })
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resumer, _ = make_resumer(selector, store, ["n", "done"], message_id="msg-ok")
            resumer.prepare()

        messages = [str(w.message) for w in caught]
        assert not any("split" in m.lower() or "heal" in m.lower() for m in messages)
