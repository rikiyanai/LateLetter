"""
Session resumption flow for the offline Q&A loop.

Handles "Resume where you left off? [y/N]" for partially-completed Q&A sessions
(docs/SPEC.md §5.3).

Flow
----
  1. Reconcile split state: if session.json has qa_answers for this message
     that are absent from questions_asked.json (caused by a crash between the
     two atomic writes in _save_progress), back-fill them in one batch write
     before the session starts.

  2. Load prior qa_answers from session.json for this message_id.

  3. If no prior answers exist, return a fresh QALoop immediately (no prompt).

  4. If prior answers exist, prompt: "Resume where you left off? [y/N]"
       y → restore SelectorSession from selector_state.json (or reconstruct
           from questions_asked.json), call load_prior_answers(), return loop.
       n → return a fresh QALoop; prior answers remain in session.json as notes.

Usage
-----
  resumer = SessionResumer(
      selector=selector,
      store=store,
      message_id="msg-001",
      occasion="birthday",
      relationship="child",
  )
  loop = resumer.prepare()   # handles the resume prompt
  result = loop.run()
"""

from __future__ import annotations

import hashlib
import warnings
from datetime import datetime, timezone
from typing import Callable

from .qa_loop import DEFAULT_EXCHANGE_TARGET, QALoop
from .question_selector import QuestionSelector, SelectorSession
from .session_store import SessionStore


class SessionResumer:
    """Wraps QALoop construction with optional session resumption.

    Inject *input_fn* and *output_fn* in tests to avoid real I/O.
    """

    def __init__(
        self,
        selector: QuestionSelector,
        store: SessionStore,
        message_id: str,
        occasion: str,
        relationship: str,
        memory_tags: list[str] | None = None,
        exchange_target: int = DEFAULT_EXCHANGE_TARGET,
        input_fn: Callable[[], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.selector = selector
        self.store = store
        self.message_id = message_id
        self.occasion = occasion
        self.relationship = relationship
        self.memory_tags = memory_tags or []
        self.exchange_target = exchange_target
        self._input = input_fn or _default_input
        self._output = output_fn or _default_output

    # ---- public ----

    def prepare(self) -> QALoop:
        """Return a QALoop ready for run(), with resumption handled.

        Mutates questions_asked.json if split-state healing is needed.
        """
        self._reconcile_split_state()
        prior_answers = self._load_prior_answers()

        session = self._restore_or_build_session()
        loop = QALoop(
            selector=self.selector,
            session=session,
            store=self.store,
            message_id=self.message_id,
            exchange_target=self.exchange_target,
            input_fn=self._input,
            output_fn=self._output,
        )

        if not prior_answers:
            return loop

        # Prompt the author
        self._output("")
        self._output(
            f"  You have {len(prior_answers)} answered question(s) from a prior session."
        )
        self._output("  Resume where you left off? [y/N] ")
        try:
            response = self._input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = "n"

        if response == "y":
            loop.load_prior_answers(prior_answers)

        return loop

    # ---- internals ----

    def _reconcile_split_state(self) -> None:
        """Heal split state between session.json and questions_asked.json.

        A crash between the two atomic writes in _save_progress can leave
        qa_answers in session.json that are absent from questions_asked.json.
        The selector would then re-offer those questions, and a re-answer
        would silently overwrite the original irreplaceable answer.

        Fix: back-fill missing IDs in a single batch write at session start.
        """
        msg = self.store.get_message(self.message_id)
        if msg is None:
            return
        # Check both finalized answers and in-progress draft answers — a crash
        # between the two atomic writes can leave entries in either list absent
        # from questions_asked.json.
        qa_answers = msg.get("qa_answers", []) + msg.get("qa_answers_draft", [])
        if not qa_answers:
            return

        existing_ids = self.store.asked_question_ids()
        missing = [
            entry for entry in qa_answers
            if entry.get("question_id") and entry["question_id"] not in existing_ids
        ]
        if not missing:
            return

        entries = self.store.load_questions_asked()
        now = _now_iso()
        for entry in missing:
            qtext = entry.get("question_text", "")
            entries.append({
                "question_id": entry["question_id"],
                "question_hash": hashlib.sha256(qtext.encode()).hexdigest(),
                "question_text": qtext,
                "asked_at": now,
                "message_id": self.message_id,
            })
        self.store.save_questions_asked(entries)
        warnings.warn(
            f"Healed split state: back-filled {len(missing)} question ID(s) "
            "from session.json into questions_asked.json.",
            RuntimeWarning,
            stacklevel=2,
        )

    def _load_prior_answers(self) -> list[dict]:
        """Return qa_answers list from session.json for this message, or []."""
        msg = self.store.get_message(self.message_id)
        if msg is None:
            return []
        return msg.get("qa_answers", [])

    def _restore_or_build_session(self) -> SelectorSession:
        """Restore SelectorSession from selector_state.json or build fresh.

        In either case, asked_all_sessions is sourced from questions_asked.json
        (the authoritative cross-session dedup log), not from the disposable
        selector_state.json cache.
        """
        asked_ids = self.store.asked_question_ids()
        state = self.store.load_selector_state(self.message_id)
        if state is not None:
            return SelectorSession.from_dict(state, asked_ids)
        return SelectorSession(
            occasion=self.occasion,
            relationship=self.relationship,
            memory_tags=list(self.memory_tags),
            asked_all_sessions=asked_ids,
        )


# ---------------------------------------------------------------------------
# Default I/O — replaced in tests
# ---------------------------------------------------------------------------

def _default_input() -> str:
    return input("  ")


def _default_output(text: str) -> None:
    print(text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
