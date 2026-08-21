"""
Offline Q&A session loop.

Presents questions drawn from the QuestionSelector, accepts free-form answers,
and persists state to disk after every exchange so the session survives
unexpected interruption (fatigue, terminal close, medical emergency).

Offline mode behaviour (docs/SPEC.md §5.3):
  - Questions are drawn from the static bank via QuestionSelector.
  - Answers are stored in session.json as notes for the draft editor.
  - No automated synthesis — the author composes the final message manually.
  - Session resumption: prior answers are reloaded and the selector continues
    from the next unasked question (handled by the caller, not this module).

Controls (typed as the entire answer and submitted):
  s     skip this question (deprioritised, may reappear later)
  e     ask something easier
  m     ask something more specific
  done  finish this session (mark complete, go to draft)
  q     quit and save (resume next session)

Multi-line answers: an empty line submits. A bare "." also submits.
Single-command inputs (s/e/m/done/q) must be the only content on the line.

Exchange target: default 10, configurable 5–30 per docs/SPEC.md §5.3.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .question_selector import Question, QuestionSelector, SelectorSession
from .session_store import SessionStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXCHANGE_TARGET = 10
MIN_EXCHANGES = 5
MAX_EXCHANGES = 30
COLUMN_WIDTH = 72

# Single-character / short commands recognised as the sole line input
_CMD_SKIP = "s"
_CMD_EASIER = "e"
_CMD_SPECIFIC = "m"
_CMD_DONE = "done"
_CMD_QUIT = "q"
_CMD_END_INPUT = "."    # alternate end-of-answer marker


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class QAAnswer:
    question_id: str
    question_text: str
    answer: str
    asked_at: str  # ISO 8601 UTC


@dataclass
class QAResult:
    answers: list[QAAnswer]
    complete: bool       # True if target reached or author typed 'done'
    interrupted: bool    # True if author quit mid-session with 'q'


# ---------------------------------------------------------------------------
# QALoop
# ---------------------------------------------------------------------------

class QALoop:
    """Interactive offline Q&A session loop.

    Inject *input_fn* and *output_fn* in tests to avoid real I/O.
    """

    def __init__(
        self,
        selector: QuestionSelector,
        session: SelectorSession,
        store: SessionStore,
        message_id: str,
        exchange_target: int = DEFAULT_EXCHANGE_TARGET,
        input_fn: Callable[[], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.selector = selector
        self.session = session
        self.store = store
        self.message_id = message_id
        self.exchange_target = max(MIN_EXCHANGES, min(MAX_EXCHANGES, exchange_target))
        self._answers: list[QAAnswer] = []
        self._prior_answer_count: int = 0
        self._input = input_fn or _default_input
        self._output = output_fn or _default_output

    # ---- public ----

    def run(self) -> QAResult:
        """Run the Q&A loop. Saves progress after every answered question."""
        self._print_header()
        current_q = self.selector.next(self.session)

        while current_q is not None and len(self._answers) < self.exchange_target:
            self._print_question(current_q)
            raw = self._read_multiline_answer()

            command = raw.strip().lower()

            if command == _CMD_QUIT:
                try:
                    self._save_progress(complete=False)
                except (OSError, IOError) as exc:
                    self._out(f"  (Warning: could not save progress — {exc})")
                    self._out("  Your answers are held in memory.")
                self._out("")
                self._out("  Session saved up to your last completed answer.")
                return QAResult(self._answers, complete=False, interrupted=True)

            if command == _CMD_DONE:
                self._out("")
                self._out("  Session complete.")
                try:
                    self._save_progress(complete=True)
                except (OSError, IOError) as exc:
                    self._out(f"  (Warning: could not save progress — {exc})")
                    self._out("  Your answers are held in memory.")
                return QAResult(self._answers, complete=True, interrupted=False)

            if command == _CMD_SKIP:
                current_q = self.selector.skip(self.session, current_q.question_id)
                continue

            if command == _CMD_EASIER:
                alt = self.selector.easier(self.session, current_q.question_id)
                if alt is not None:
                    current_q = alt
                else:
                    self._out("  (No easier question available — keeping this one.)")
                continue

            if command == _CMD_SPECIFIC:
                alt = self.selector.more_specific(self.session, current_q.question_id)
                if alt is not None:
                    current_q = alt
                else:
                    self._out("  (No more specific question available — keeping this one.)")
                continue

            if not raw.strip():
                self._out("  (Empty answer — skipped.)")
                current_q = self.selector.skip(self.session, current_q.question_id)
                continue

            # Record answer and persist
            answer = QAAnswer(
                question_id=current_q.question_id,
                question_text=current_q.prompt,
                answer=raw.strip(),
                asked_at=_now_iso(),
            )
            self._answers.append(answer)
            self.selector.mark_asked(self.session, current_q)
            try:
                self._save_progress(complete=False)
            except (OSError, IOError) as exc:
                self._out(f"  (Warning: could not save progress — {exc})")
                self._out("  Your answers are held in memory. Try to complete the session.")

            current_q = self.selector.next(self.session)

        target_reached = len(self._answers) >= self.exchange_target
        self._out("")
        if target_reached:
            self._out("  Session complete.")
        else:
            self._out("  (No more questions available for this session.)")
        try:
            self._save_progress(complete=target_reached)
        except (OSError, IOError) as exc:
            self._out(f"  (Warning: could not save progress — {exc})")
            self._out("  Your answers are held in memory.")
        return QAResult(self._answers, complete=target_reached, interrupted=False)

    def load_prior_answers(self, answers: list[dict]) -> None:
        """Restore previously answered Q&A from session.json.

        Called by the resumption flow before run() when the author resumes
        a partially completed session. Marks all prior questions as asked in
        the selector session so they are not re-selected.
        """
        for entry in answers:
            qa = QAAnswer(
                question_id=entry["question_id"],
                question_text=entry["question_text"],
                answer=entry["answer"],
                asked_at=entry["asked_at"],
            )
            self._answers.append(qa)
            # Mark in selector so already-asked questions are excluded.
            # If the question was removed from the bank (bank migration), add
            # it to asked_all_sessions directly so it is not re-offered, but
            # do NOT call mark_asked — that would add "unknown" to
            # domains_covered and skew coverage-balance scoring.
            q_obj = self.selector.get(qa.question_id)
            if q_obj is not None:
                self.session.mark_asked(qa.question_id, q_obj.domain)
            else:
                self.session.asked_all_sessions.add(qa.question_id)
        self._prior_answer_count = len(self._answers)

    # ---- rendering ----

    def _print_header(self) -> None:
        remaining = self.exchange_target - len(self._answers)
        self._out("")
        self._out("  " + "─" * COLUMN_WIDTH)
        self._out(f"  Q&A session  ({remaining} question{'s' if remaining != 1 else ''} remaining)")
        self._out("  " + "─" * COLUMN_WIDTH)

    def _print_question(self, q: Question) -> None:
        pos = len(self._answers) + 1
        self._out("")
        self._out(f"  [{pos}/{self.exchange_target}]")
        self._out("")
        for line in textwrap.wrap(q.prompt, COLUMN_WIDTH - 2):
            self._out("  " + line)
        self._out("")
        self._out(
            "  [s]kip  [e]asier  [m]ore specific  [done] finish  [q]uit"
        )
        self._out("")

    # ---- input ----

    def _read_multiline_answer(self) -> str:
        """Read lines until a blank line or '.' alone. Return joined text."""
        self._out("  Your answer (blank line to submit):")
        self._out("")
        lines: list[str] = []
        while True:
            try:
                line = self._input()
            except (EOFError, KeyboardInterrupt):
                return _CMD_QUIT
            stripped = line.strip()
            # Single-command shortcut: only on first line and only if no text yet
            if not lines and stripped.lower() in (
                _CMD_SKIP, _CMD_EASIER, _CMD_SPECIFIC, _CMD_DONE, _CMD_QUIT
            ):
                return stripped.lower()
            if stripped == _CMD_END_INPUT:
                break
            if stripped == "" and lines:
                break
            if stripped != "":
                lines.append(line)
        return "\n".join(lines)

    # ---- persistence ----

    def _save_progress(self, *, complete: bool) -> None:
        """Persist answers, selector state, and update session.json.

        Draft/finalized split (Option C):
          incomplete → write new answers to qa_answers_draft only; prior
                       answers in qa_answers are untouched (preserved on disk).
          complete   → merge prior + new into qa_answers, clear qa_answers_draft.
        """
        new_answers = self._answers[self._prior_answer_count:]
        serialised_new = [
            {
                "question_id": a.question_id,
                "question_text": a.question_text,
                "answer": a.answer,
                "asked_at": a.asked_at,
            }
            for a in new_answers
        ]

        if complete:
            if self._prior_answer_count > 0:
                serialised_prior = [
                    {
                        "question_id": a.question_id,
                        "question_text": a.question_text,
                        "answer": a.answer,
                        "asked_at": a.asked_at,
                    }
                    for a in self._answers[:self._prior_answer_count]
                ]
            else:
                # Fresh session or user chose not to resume — preserve any
                # pre-existing qa_answers from previous completed sessions.
                existing_msg = self.store.get_message(self.message_id) or {}
                serialised_prior = existing_msg.get("qa_answers", [])
            serialised_all = serialised_prior + serialised_new
            self.store.upsert_message(self.message_id, {
                "qa_answers": serialised_all,
                "qa_answers_draft": [],
                "qa_exchange_target": self.exchange_target,
                "qa_exchange_count": len(serialised_all),
                "qa_complete": True,
            })
        else:
            self.store.upsert_message(self.message_id, {
                "qa_answers_draft": serialised_new,
                "qa_draft_count": len(new_answers),
                "qa_exchange_target": self.exchange_target,
                "qa_complete": False,
            })

        # Append any newly asked questions to questions_asked.json.
        # Re-reading the existing log each time is safe because we always
        # append; no question is written twice (record_question_asked does
        # not dedup, so we track which IDs we've already persisted).
        existing_ids = self.store.asked_question_ids()
        for a in self._answers:
            if a.question_id not in existing_ids:
                self.store.record_question_asked(
                    a.question_id, a.question_text, self.message_id
                )
                existing_ids.add(a.question_id)

        self.store.save_selector_state(self.message_id, self.session.to_dict())

    # ---- output ----

    def _out(self, text: str) -> None:
        self._output(text)


# ---------------------------------------------------------------------------
# Default I/O — replaced in tests
# ---------------------------------------------------------------------------

def _default_input() -> str:
    return input("  ")


def _default_output(text: str) -> None:
    print(text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
