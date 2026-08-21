#!/usr/bin/env python3
"""Recover every operator instruction and decision from the Claude Code session transcripts.

WHY THIS EXISTS
---------------
On 2026-08-01 the operator said, verbatim:

    "THERE ARE FUCKING TRANSCRIPTS. FUCKING READ THEM. U ASKED QUESTIONS. I
     FUCKING ANSWERED. U ASKED ME DESIGN SPEC QUESTIONS I FUCKING ANSWERED.
     YET U ACT LIKE NONE OF THIS FUCKING HAPPENED. NONE OF THIS WAS LOGGED."

That is correct and it is the root of the repeated-failure pattern documented in
`docs/FAILURE_LOG.md`. Decisions were made in conversation, acted on once, and
never written anywhere a later session could read. The next session then found
`not_reviewed` in the registry or an unattributed claim in `docs/SPEC.md`, could
not tell an operator decision from an assistant assertion, and re-litigated or
reversed a settled question. Five refactor attempts have run on top of that gap.

The session transcripts are the only durable record of what the operator
actually said. This script reads them and produces a single chronological
decision record so the answers stop living exclusively in a 23MB JSONL file that
nobody reads.

WHAT IT EXTRACTS
----------------
1. Every operator message -- their real typed input, verbatim, never summarised.
2. Every `AskUserQuestion` the assistant asked, with its options.
3. The operator's answer to each of those questions, matched by tool-use id.

WHAT IT DELIBERATELY DROPS
--------------------------
Transcripts contain far more than operator speech. Tool results, system
reminders, hook output, IDE state, compaction summaries and command stdout all
appear in `type: "user"` records because that is how the harness feeds them
back. Including them would bury the operator's twenty real sentences under
megabytes of machine chatter, which is the same signal-to-noise failure that let
these decisions get lost in the first place. Every filter below is therefore
about removing MACHINE speech, never about removing or shortening anything the
operator typed.

USAGE
-----
    python3 scripts/extract_operator_decisions.py
    python3 scripts/extract_operator_decisions.py --out docs/operator-decision-record.md
    python3 scripts/extract_operator_decisions.py --since 2026-07-28

Output is deterministic: same transcripts in, same file out, so it can be
regenerated and diffed rather than hand-maintained.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# Where Claude Code stores this project's session transcripts. One JSONL file
# per session, each line one record.
TRANSCRIPT_DIR = Path.home() / ".claude" / "projects" / "-Users-r-Projects-LateLetter"

# Records whose text starts with one of these are harness plumbing rather than
# operator speech. Matched against the START of the text only, so an operator
# message that happens to mention "Caveat" somewhere in the middle survives.
MACHINE_PREFIXES = (
    "<",                       # any wrapped block: system-reminder, tool output
    "Caveat:",                 # local-command caveat banner
    "[Request interrupted",    # harness interruption marker, carries no content
    "[Image:",                 # image attachment metadata line
    "PROTOCOL: TMUX-LANES",    # tmux lane dispatch envelope
    "ROOT|v=",                 # tmux lane control message
    "This session is being continued from a previous conversation",  # compaction
)

# Substrings that mark a record as machine output even mid-text.
MACHINE_MARKERS = (
    "system-reminder",
    "local-command-stdout",
    "local-command-caveat",
    "<task-notification>",
    "[SYSTEM NOTIFICATION - NOT USER INPUT]",
)

# Operator speech carrying one of these is a DECISION rather than a request:
# an approval, a rejection, a constraint, or a correction. Flagged in the output
# so the decisions can be found without reading every line.
DECISION_PATTERNS = (
    (r"\bapprov(e|ed|al)\b", "APPROVAL"),
    (r"\breject(ed)?\b|\bnot? fucking approve", "REJECTION"),
    (r"\bdo not\b|\bdont\b|\bdon't\b|\bnever\b|\bstop\b", "CONSTRAINT"),
    (r"\bwrong\b|\bincorrect\b|\bactually\b", "CORRECTION"),
    (r"\bspec\b|\bcontract\b|\bdesign\b", "SPEC"),
    (r"\blegacy\b|\brikiworld\b|\barchive\b", "LEGACY-REFERENCE"),
)


def text_of(content) -> str:
    """Flatten a transcript record's `content` field into plain text.

    `content` is either a bare string or a list of typed blocks. Only `text`
    blocks carry what a human typed; `tool_use` and `tool_result` blocks are
    machine traffic and are handled separately by the caller.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def is_machine(text: str) -> bool:
    """True when this record is harness plumbing rather than operator speech."""
    stripped = text.lstrip()
    if stripped.startswith(MACHINE_PREFIXES):
        return True
    # Only inspect the head: an operator quoting a system message in a long
    # complaint should still count as operator speech.
    head = stripped[:400]
    return any(marker in head for marker in MACHINE_MARKERS)


def classify(text: str) -> list[str]:
    """Tag operator speech with the kinds of decision it appears to carry."""
    tags = []
    for pattern, tag in DECISION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            tags.append(tag)
    return tags


def collect(paths: list[Path]) -> list[dict]:
    """Read every transcript and return one merged, chronological event list.

    Three event kinds are produced:
      `operator`  -- something the operator typed
      `question`  -- an AskUserQuestion the assistant put to them
      `answer`    -- their reply to a specific question, matched by tool-use id
    """
    events: list[dict] = []
    # tool_use_id -> the question text, so an answer arriving many records later
    # can be attached to the question it belongs to.
    pending: dict[str, dict] = {}

    for path in paths:
        session = path.stem[:8]
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a truncated final line is normal on a live session
                stamp = (record.get("timestamp") or "")[:19]
                message = record.get("message") or {}
                content = message.get("content")

                # ── Assistant records: harvest the questions asked ──────────
                if record.get("type") == "assistant" and isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue
                        if block.get("name") != "AskUserQuestion":
                            continue
                        for question in block.get("input", {}).get("questions", []):
                            pending[block["id"]] = {
                                "question": question.get("question", ""),
                                "options": [
                                    option.get("label", "")
                                    for option in question.get("options", [])
                                ],
                            }
                            events.append({
                                "kind": "question", "at": stamp, "session": session,
                                "text": question.get("question", ""),
                                "options": pending[block["id"]]["options"],
                            })

                if record.get("type") != "user":
                    continue

                # ── User records carrying a tool_result: the answers ────────
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_result":
                            continue
                        asked = pending.get(block.get("tool_use_id", ""))
                        if not asked:
                            continue
                        raw = block.get("content")
                        answer = raw if isinstance(raw, str) else json.dumps(
                            raw, ensure_ascii=False)
                        events.append({
                            "kind": "answer", "at": stamp, "session": session,
                            "question": asked["question"], "text": answer,
                        })

                # ── User records carrying typed text: operator speech ───────
                spoken = text_of(content).strip()
                if not spoken or is_machine(spoken):
                    continue
                events.append({
                    "kind": "operator", "at": stamp, "session": session,
                    "text": spoken, "tags": classify(spoken),
                })

    # Chronological across sessions. Records with no timestamp sort first rather
    # than crashing the sort.
    events.sort(key=lambda event: event["at"] or "")
    return events


def render(events: list[dict]) -> str:
    """Format the merged event list as a reviewable markdown record."""
    operator = [e for e in events if e["kind"] == "operator"]
    questions = [e for e in events if e["kind"] == "question"]
    answers = [e for e in events if e["kind"] == "answer"]

    out = [
        "# Operator decision record",
        "",
        "Generated by `scripts/extract_operator_decisions.py` from the Claude Code",
        "session transcripts. **Do not hand-edit** — regenerate instead.",
        "",
        "This file exists because decisions were being made in conversation and never",
        "written anywhere a later session could read, so each new session could not",
        "distinguish an operator decision from an assistant assertion. See the",
        "2026-08-01 entries in `docs/FAILURE_LOG.md`.",
        "",
        f"- operator messages: **{len(operator)}**",
        f"- questions asked of the operator: **{len(questions)}**",
        f"- answers recorded: **{len(answers)}**",
        "",
        "---",
        "",
        "## Decisions and answers, in order",
        "",
    ]

    for event in events:
        if event["kind"] == "question":
            out.append(f"### Q — {event['at']} `{event['session']}`")
            out.append("")
            out.append(f"> {event['text']}")
            if event.get("options"):
                out.append("")
                for option in event["options"]:
                    out.append(f"- {option}")
            out.append("")
        elif event["kind"] == "answer":
            out.append(f"**ANSWER** — {event['at']} `{event['session']}`  ")
            out.append(f"*to:* {event['question'][:120]}")
            out.append("")
            out.append("```")
            out.append(event["text"].strip()[:2000])
            out.append("```")
            out.append("")
        else:
            tags = " ".join(f"`{tag}`" for tag in event.get("tags", []))
            out.append(f"### OPERATOR — {event['at']} `{event['session']}` {tags}")
            out.append("")
            for line in event["text"].splitlines():
                out.append(f"> {line}")
            out.append("")

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", type=Path, default=TRANSCRIPT_DIR,
                        help="directory holding the session .jsonl files")
    parser.add_argument("--out", type=Path,
                        default=Path("docs/operator-decision-record.md"),
                        help="markdown file to write")
    parser.add_argument("--since", default=None,
                        help="ISO date; drop events before it, e.g. 2026-07-28")
    args = parser.parse_args()

    paths = sorted(args.transcripts.glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"no transcripts found in {args.transcripts}")

    events = collect(paths)
    if args.since:
        events = [e for e in events if (e["at"] or "") >= args.since]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(events), encoding="utf-8")

    kinds = {kind: sum(1 for e in events if e["kind"] == kind)
             for kind in ("operator", "question", "answer")}
    print(f"transcripts read : {len(paths)}")
    for kind, count in kinds.items():
        print(f"{kind:17s}: {count}")
    print(f"written          : {args.out} ({args.out.stat().st_size // 1024}K)")


if __name__ == "__main__":
    main()
