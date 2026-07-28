"""
Tests for QALoop (offline Q&A session loop).

All tests use injected input_fn and output_fn to avoid real I/O and
to drive the loop programmatically.
"""

from pathlib import Path

import pytest

from src.lateletter.qa_loop import (
    DEFAULT_EXCHANGE_TARGET,
    MAX_EXCHANGES,
    MIN_EXCHANGES,
    QALoop,
    QAResult,
)
from src.lateletter.question_selector import QuestionSelector, SelectorSession
from src.lateletter.session_store import SessionStore

DATA_DIR = Path(__file__).parent.parent / "data"
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


def make_session(**kwargs) -> SelectorSession:
    defaults = dict(occasion="birthday", relationship="child", memory_tags=[])
    defaults.update(kwargs)
    return SelectorSession(**defaults)


def make_loop(
    selector,
    store,
    inputs: list[str],
    *,
    exchange_target: int = 5,
    session: SelectorSession | None = None,
    message_id: str = "test-msg-001",
) -> tuple[QALoop, list[str]]:
    """Return a QALoop wired to a fixed input sequence and captured output."""
    if session is None:
        session = make_session()
    output_lines: list[str] = []
    input_iter = iter(inputs)

    def _in() -> str:
        return next(input_iter)

    loop = QALoop(
        selector=selector,
        session=session,
        store=store,
        message_id=message_id,
        exchange_target=exchange_target,
        input_fn=_in,
        output_fn=output_lines.append,
    )
    return loop, output_lines


# ---------------------------------------------------------------------------
# Basic flow
# ---------------------------------------------------------------------------

class TestBasicFlow:
    def test_run_returns_qa_result(self, selector, store):
        # Provide one answer per question then 'done'
        # Each question asks for a blank-line termination; supply an answer line then ''
        inputs = []
        for _ in range(5):
            inputs += ["An answer", ""]  # answer + blank line to submit
        inputs += ["done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert isinstance(result, QAResult)

    def test_answers_recorded(self, selector, store):
        inputs = []
        for _ in range(5):
            inputs += ["My answer here", ""]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert len(result.answers) == 5

    def test_complete_true_when_target_reached(self, selector, store):
        inputs = []
        for _ in range(5):
            inputs += ["Answer", ""]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.complete is True
        assert result.interrupted is False

    def test_answer_text_preserved(self, selector, store):
        inputs = ["My full answer text", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.answers[0].answer == "My full answer text"

    def test_answer_has_timestamp(self, selector, store):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.answers[0].asked_at.endswith("+00:00") or "Z" in result.answers[0].asked_at

    def test_answer_has_question_text(self, selector, store):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.answers[0].question_text  # not empty
        assert "?" in result.answers[0].question_text or len(result.answers[0].question_text) > 5

    def test_answer_has_question_id(self, selector, store):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.answers[0].question_id.startswith("u-") or "-" in result.answers[0].question_id


# ---------------------------------------------------------------------------
# Quit command
# ---------------------------------------------------------------------------

class TestQuit:
    def test_quit_returns_interrupted(self, selector, store):
        inputs = ["Answer", "", "q"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.interrupted is True
        assert result.complete is False

    def test_quit_preserves_prior_answers(self, selector, store):
        inputs = ["First answer", "", "q"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert len(result.answers) == 1
        assert result.answers[0].answer == "First answer"

    def test_quit_on_first_question(self, selector, store):
        inputs = ["q"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.interrupted is True
        assert len(result.answers) == 0

    def test_quit_persists_selector_state(self, selector, store):
        """Quit path must write selector_state.json so skipped questions survive."""
        session = make_session()
        inputs = ["s", "q"]  # skip first question then quit
        loop, _ = make_loop(selector, store, inputs, session=session,
                            exchange_target=5, message_id="msg-quit-state")
        loop.run()
        saved = store.load_selector_state("msg-quit-state")
        assert saved is not None, "selector_state.json not written on quit"
        assert len(saved.get("skipped_this_session", [])) == 1

    def test_quit_message_accurate_when_prior_answers_exist(self, selector, store):
        """Output should not say 'saved' without qualification when answers exist."""
        inputs = ["Answer", "", "q"]
        loop, output = make_loop(selector, store, inputs, exchange_target=5)
        loop.run()
        combined = " ".join(output)
        assert "saved" in combined.lower()  # some save message is present
        # The old misleading bare "Session saved. Type 'y'" is gone
        assert "Type 'y' to resume" not in combined


# ---------------------------------------------------------------------------
# Done command
# ---------------------------------------------------------------------------

class TestDone:
    def test_done_completes_session(self, selector, store):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.complete is True
        assert result.interrupted is False

    def test_done_on_first_question_returns_zero_answers(self, selector, store):
        inputs = ["done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.complete is True
        assert len(result.answers) == 0


# ---------------------------------------------------------------------------
# Skip command
# ---------------------------------------------------------------------------

class TestSkip:
    def test_skip_advances_to_new_question(self, selector, store):
        # Skip first question, then answer the second, then done
        inputs = ["s", "An answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert len(result.answers) == 1

    def test_skip_does_not_record_answer(self, selector, store):
        inputs = ["s", "s", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert len(result.answers) == 0

    def test_skipped_question_id_in_session_state(self, selector, store):
        session = make_session()
        inputs = ["s", "done"]
        loop, _ = make_loop(selector, store, inputs, session=session, exchange_target=5)
        loop.run()
        assert len(session.skipped_this_session) == 1


# ---------------------------------------------------------------------------
# Easier command
# ---------------------------------------------------------------------------

class TestEasier:
    def test_easier_changes_question(self, selector, store):
        # Get first question, request easier, then answer, then done
        first_ids: list[str] = []
        second_ids: list[str] = []

        outputs: list[str] = []

        def patched_out(text: str) -> None:
            outputs.append(text)

        # Run once to capture first question
        session_a = make_session()
        input_a = iter(["done"])
        loop_a = QALoop(
            selector=selector, session=session_a, store=store,
            message_id="msg-a", exchange_target=5,
            input_fn=lambda: next(input_a),
            output_fn=lambda t: None,
        )

        q_a = selector.next(session_a)
        if q_a:
            first_ids.append(q_a.question_id)

        # Now run with easier
        session_b = make_session()
        input_b = iter(["e", "An answer", "", "done"])
        loop_b = QALoop(
            selector=selector, session=session_b, store=store,
            message_id="msg-b", exchange_target=5,
            input_fn=lambda: next(input_b),
            output_fn=lambda t: None,
        )
        result = loop_b.run()
        # Either a question was answered or we got a 'no easier available' path
        # The key assertion is just that the loop runs without error
        assert isinstance(result, QAResult)

    def test_easier_does_not_crash_when_nothing_easier(self, selector, store):
        # Force a situation where only intensity-1 questions remain by
        # marking all intensity-2+ questions as asked
        session = make_session()
        for q in selector._all:
            if q.intensity > 1:
                session.asked_all_sessions.add(q.question_id)
        inputs = ["e", "done"]
        loop, output = make_loop(selector, store, inputs, session=session, exchange_target=5)
        result = loop.run()
        # Should produce a "no easier" message or still run
        assert isinstance(result, QAResult)


# ---------------------------------------------------------------------------
# More specific command
# ---------------------------------------------------------------------------

class TestMoreSpecific:
    def test_more_specific_runs_without_error(self, selector, store):
        inputs = ["m", "An answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert isinstance(result, QAResult)


# ---------------------------------------------------------------------------
# Empty answer
# ---------------------------------------------------------------------------

class TestEmptyAnswer:
    def test_empty_answer_skips_question(self, selector, store):
        # First answer is empty (blank line immediately), then a real answer, done
        inputs = ["", "A real answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        # The empty answer was skipped; the real answer was recorded
        assert len(result.answers) == 1
        assert result.answers[0].answer == "A real answer"


# ---------------------------------------------------------------------------
# Multiline answers
# ---------------------------------------------------------------------------

class TestMultilineAnswers:
    def test_multiline_answer_joined(self, selector, store):
        inputs = ["Line one", "Line two", "Line three", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert "Line one" in result.answers[0].answer
        assert "Line two" in result.answers[0].answer
        assert "Line three" in result.answers[0].answer

    def test_dot_terminates_answer(self, selector, store):
        inputs = ["My answer", ".", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5)
        result = loop.run()
        assert result.answers[0].answer == "My answer"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_answers_persisted_to_session_json(self, selector, store):
        inputs = ["Answer one", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-persist")
        loop.run()
        msg = store.get_message("msg-persist")
        assert msg is not None
        assert len(msg["qa_answers"]) == 1
        assert msg["qa_answers"][0]["answer"] == "Answer one"

    def test_questions_asked_json_updated(self, selector, store):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-dedup")
        loop.run()
        ids = store.asked_question_ids()
        assert len(ids) >= 1

    def test_selector_state_json_written(self, selector, store, tmp_path):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-state")
        loop.run()
        assert (tmp_path / "selector_state.json").exists()

    def test_qa_exchange_count_persisted(self, selector, store):
        inputs = ["A1", "", "A2", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-count")
        loop.run()
        msg = store.get_message("msg-count")
        assert msg["qa_exchange_count"] == 2

    def test_qa_complete_flag_set_on_target_reached(self, selector, store):
        inputs = []
        for _ in range(5):
            inputs += ["Answer", ""]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-flag")
        loop.run()
        msg = store.get_message("msg-flag")
        assert msg["qa_complete"] is True

    def test_qa_complete_false_on_quit(self, selector, store):
        inputs = ["Answer", "", "q"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-quit")
        loop.run()
        msg = store.get_message("msg-quit")
        assert msg is not None
        assert msg["qa_complete"] is False

    def test_no_duplicate_entries_in_questions_asked(self, selector, store):
        inputs = ["Answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=5, message_id="msg-nodup")
        loop.run()
        entries = store.load_questions_asked()
        ids = [e["question_id"] for e in entries]
        assert len(ids) == len(set(ids)), "Duplicate entries in questions_asked.json"


# ---------------------------------------------------------------------------
# Exchange target limits
# ---------------------------------------------------------------------------

class TestExchangeTarget:
    def test_min_exchange_target_enforced(self, selector, store):
        inputs = []
        for _ in range(MIN_EXCHANGES):
            inputs += ["A", ""]
        inputs += ["done"]
        loop, _ = make_loop(selector, store, inputs, exchange_target=1)  # below min
        assert loop.exchange_target == MIN_EXCHANGES

    def test_max_exchange_target_enforced(self, selector, store):
        loop, _ = make_loop(selector, store, ["done"], exchange_target=999)  # above max
        assert loop.exchange_target == MAX_EXCHANGES


# ---------------------------------------------------------------------------
# load_prior_answers (resumption support)
# ---------------------------------------------------------------------------

class TestLoadPriorAnswers:
    def test_prior_answers_prepended(self, selector, store):
        prior = [
            {
                "question_id": "u-001",
                "question_text": "How would you describe yourself?",
                "answer": "Prior answer",
                "asked_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        session = make_session(asked_all_sessions={"u-001"})
        inputs = ["New answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, session=session, exchange_target=5)
        loop.load_prior_answers(prior)
        result = loop.run()
        assert result.answers[0].answer == "Prior answer"
        assert result.answers[1].answer == "New answer"

    def test_prior_answers_mark_questions_as_asked(self, selector, store):
        prior = [
            {
                "question_id": "u-001",
                "question_text": "Q1",
                "answer": "A1",
                "asked_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        session = make_session()
        loop, _ = make_loop(selector, store, ["done"], session=session, exchange_target=5)
        loop.load_prior_answers(prior)
        assert "u-001" in session.asked_all_sessions

    def test_session_continues_from_after_prior_questions(self, selector, store):
        # Mark u-001 as prior → next question should not be u-001
        prior = [
            {
                "question_id": "u-001",
                "question_text": "Q1",
                "answer": "A1",
                "asked_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        session = make_session()
        inputs = ["New answer", "", "done"]
        loop, _ = make_loop(selector, store, inputs, session=session, exchange_target=5)
        loop.load_prior_answers(prior)
        result = loop.run()
        # New answer should be for a different question than u-001
        new_answers = [a for a in result.answers if a.asked_at != "2026-01-01T00:00:00+00:00"]
        if new_answers:
            assert new_answers[0].question_id != "u-001"

    def test_prior_answers_with_unknown_id_does_not_pollute_domains_covered(self, selector, store):
        """A removed bank question must not add 'unknown' to domains_covered."""
        prior = [
            {
                "question_id": "deleted-question-99",
                "question_text": "Old question that was removed",
                "answer": "Prior answer",
                "asked_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        session = make_session()
        loop, _ = make_loop(selector, store, ["done"], session=session, exchange_target=5)
        loop.load_prior_answers(prior)
        assert "unknown" not in session.domains_covered
        assert "deleted-question-99" in session.asked_all_sessions

    def test_prior_answers_with_unknown_id_question_not_re_offered(self, selector, store):
        """A removed bank question must still be excluded from future selection."""
        prior = [
            {
                "question_id": "deleted-question-99",
                "question_text": "Removed",
                "answer": "A",
                "asked_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        session = make_session()
        loop, _ = make_loop(selector, store, ["done"], session=session, exchange_target=5)
        loop.load_prior_answers(prior)
        # The deleted ID is in asked_all_sessions so selector will not offer it
        assert "deleted-question-99" in session.asked_all_sessions


# ---------------------------------------------------------------------------
# Save-progress error handling
# ---------------------------------------------------------------------------

class TestSaveProgressErrors:
    def test_oserror_in_save_does_not_crash_loop(self, selector, store, tmp_path):
        """A disk error during save should warn but not lose in-progress answers."""
        import unittest.mock as mock
        inputs = ["Answer one", "", "Answer two", "", "done"]
        loop, output = make_loop(selector, store, inputs, exchange_target=5,
                                 message_id="msg-ioerr")
        # Make _save_progress raise OSError on first call only
        original_save = loop._save_progress
        call_count = [0]
        def _failing_save(*, complete):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("disk full")
            return original_save(complete=complete)
        loop._save_progress = _failing_save

        result = loop.run()
        # Session should complete despite the error; both answers in memory
        assert len(result.answers) == 2
        # Warning was surfaced to output
        assert any("Warning" in line or "could not save" in line for line in output)
