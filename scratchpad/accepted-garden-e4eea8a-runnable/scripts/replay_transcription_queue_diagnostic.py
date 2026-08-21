#!/usr/bin/env python3
"""Fresh diagnostic replay for the external normalized PNG queue.

This script intentionally does not read existing TXT, accepted transcripts, or
historical attempt artifacts.  It runs the current production ``transcribe()``
owner into a new immutable diagnostic directory, then writes a source-only
review page and hash-bound receipt.
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from lateletter.transcription import AttemptError, transcribe
from lateletter.transcription.hashing import sha256_bytes, sha256_file
from lateletter.transcription.schema import canonical_bytes


def _slug(path: Path) -> str:
    allowed = []
    for char in path.stem.lower():
        if char.isalnum():
            allowed.append(char)
        elif char in {"-", "_", ".", " "}:
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:64] or "source"


def _git_state() -> dict[str, Any]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], text=True)
    return {
        "commit": commit,
        "dirty": bool(status.strip()),
        "status_short": status.splitlines(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(payload) + b"\n"
    path.write_bytes(data)
    return sha256_bytes(data)


def _rel(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _html_review(output_root: Path, rows: list[dict[str, Any]], receipt: dict[str, Any]) -> str:
    cards = []
    for row in rows:
        attempt = Path(row["attempt_dir"])
        normalized = attempt / "normalized.png"
        candidate = attempt / "candidate.txt"
        candidate_html = (
            "<pre class='candidate'>"
            + html.escape(candidate.read_text(encoding="utf-8"))
            + "</pre>"
            if candidate.exists()
            else "<div class='no-candidate'>NO CURRENT CANDIDATE</div>"
        )
        reasons = "".join(f"<li>{html.escape(str(item))}</li>" for item in row.get("rejection_reasons", ()))
        cards.append(
            f"""
            <section class="card status-{html.escape(str(row['status']))}">
              <h2>{html.escape(row['id'])}</h2>
              <div class="meta">
                <div><b>Status:</b> {html.escape(row['status'])}</div>
                <div><b>Candidate written:</b> {str(row['candidate_written']).lower()}</div>
                <div><b>SHA-256:</b> <code>{html.escape(row['source_sha256'])}</code></div>
                <div><b>Size:</b> {row['width']}×{row['height']}</div>
              </div>
              <div class="compare">
                <figure>
                  <figcaption>Current source normalized PNG</figcaption>
                  <img src="{html.escape(_rel(normalized, output_root))}" />
                </figure>
                <figure>
                  <figcaption>Current production candidate</figcaption>
                  {candidate_html}
                </figure>
              </div>
              <details open>
                <summary>Gate rejection reasons</summary>
                <ul>{reasons or "<li>none</li>"}</ul>
              </details>
            </section>
            """
        )
    summary_rows = "".join(
        f"<tr><td>{html.escape(str(key))}</td><td>{value}</td></tr>"
        for key, value in sorted(receipt["summary"].items())
    )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>LateLetter fresh PNG→TXT diagnostic replay</title>"
        "<style>"
        "body{font-family:system-ui,-apple-system,sans-serif;margin:24px;background:#f7f7f7;color:#111}"
        "h1{margin-bottom:0}.note{max-width:980px;line-height:1.45}.summary{border-collapse:collapse;margin:16px 0;background:white}"
        ".summary td{border:1px solid #ccc;padding:6px 10px}.card{background:white;border:1px solid #ccc;border-radius:10px;margin:18px 0;padding:16px}"
        ".meta{font-size:13px;color:#333;display:grid;gap:4px;margin:8px 0 12px}"
        ".compare{display:grid;grid-template-columns:minmax(240px,1fr) minmax(240px,1fr);gap:18px;align-items:start}"
        "figure{margin:0}figcaption{font-weight:600;margin-bottom:8px}img{max-width:100%;background:white;border:1px solid #ddd;image-rendering:auto}"
        "pre.candidate{white-space:pre;overflow:auto;background:#1f1f1f;color:#f7f7f7;padding:12px;border-radius:8px;font:18px/1.2 monospace;min-height:120px}"
        ".no-candidate{background:#eee;border:1px dashed #999;border-radius:8px;padding:24px;color:#555;font-weight:700}"
        "code{font-family:ui-monospace,monospace;font-size:12px}details{margin-top:12px}li{font-family:ui-monospace,monospace;font-size:12px}"
        "</style>"
        "<h1>Fresh diagnostic replay: current production transcribe()</h1>"
        "<p class='note'>This page was regenerated from the current 26 normalized PNGs only. It does not read old TXT, accepted TXT, historical attempts, or provisional candidate files. A missing candidate is the current production result, not a visual omission.</p>"
        f"<table class='summary'>{summary_rows}</table>"
        + "\n".join(cards)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES "),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("tracked/LateLetterResearch/transcription-parity/queue-diagnostic-replays"),
    )
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    sources = tuple(sorted(source_dir.glob("*.normalized.png")))
    if not sources:
        raise SystemExit(f"no *.normalized.png files found under {source_dir}")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-current-transcribe")
    run_root = (args.output_root / run_id).resolve()
    if run_root.exists():
        raise SystemExit(f"diagnostic run already exists: {run_root}")
    attempts_root = run_root / "attempts"
    run_root.mkdir(parents=True)

    git = _git_state()
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        source_hash = sha256_file(source)
        with Image.open(source) as image:
            width, height = image.size
        attempt_id = f"{index:03d}-{_slug(source)}"
        print(f"[{index:02d}/{len(sources):02d}] {source.name}", flush=True)
        try:
            result = transcribe(source, attempts_root, attempt_id)
            attempt = Path(result["attempt_dir"])
            gate = result.get("gate_report", {})
            rejection_reasons = list(gate.get("rejection_reasons", ())) if isinstance(gate, dict) else []
            row = {
                "id": source.name,
                "source_path": str(source),
                "source_sha256": source_hash,
                "width": width,
                "height": height,
                "attempt_id": attempt_id,
                "attempt_dir": str(attempt),
                "status": str(result.get("status")),
                "candidate_written": bool(result.get("candidate_written")),
                "candidate_sha256": sha256_file(attempt / "candidate.txt") if (attempt / "candidate.txt").exists() else None,
                "manifest_path": str(attempt / "manifest.json"),
                "rejection_reasons": rejection_reasons,
            }
        except (AttemptError, OSError, ValueError) as exc:
            row = {
                "id": source.name,
                "source_path": str(source),
                "source_sha256": source_hash,
                "width": width,
                "height": height,
                "attempt_id": attempt_id,
                "attempt_dir": str(attempts_root / attempt_id),
                "status": "harness_error",
                "candidate_written": False,
                "candidate_sha256": None,
                "manifest_path": None,
                "rejection_reasons": [f"{type(exc).__name__}: {exc}"],
            }
        rows.append(row)

    summary: dict[str, int] = {
        "source_count": len(rows),
        "candidate_written": sum(1 for row in rows if row["candidate_written"]),
        "harness_error": sum(1 for row in rows if row["status"] == "harness_error"),
    }
    for row in rows:
        key = f"status:{row['status']}"
        summary[key] = summary.get(key, 0) + 1
    inventory = {
        "schema": "lateletter-queue-diagnostic-inventory-1",
        "source_dir": str(source_dir),
        "git": git,
        "sources": [
            {
                "path": row["source_path"],
                "sha256": row["source_sha256"],
                "width": row["width"],
                "height": row["height"],
            }
            for row in rows
        ],
    }
    inventory_hash = _write_json(run_root / "source-inventory.json", inventory)
    replay = {
        "schema": "lateletter-queue-diagnostic-replay-1",
        "run_id": run_id,
        "authority": "diagnostic_only",
        "old_txt_read": False,
        "accepted_txt_read": False,
        "historical_attempts_read": False,
        "source_inventory_hash": inventory_hash,
        "git": git,
        "summary": summary,
        "rows": rows,
    }
    replay_hash = _write_json(run_root / "replay.json", replay)
    receipt = {
        "schema": "lateletter-queue-diagnostic-receipt-1",
        "run_id": run_id,
        "authority": "diagnostic_only",
        "run_root": str(run_root),
        "source_inventory_sha256": inventory_hash,
        "replay_sha256": replay_hash,
        "summary": summary,
        "old_txt_read": False,
        "accepted_txt_read": False,
        "historical_attempts_read": False,
        "next_step": "Use this replay to separate stale/provisional review output from current production transcribe results; do not accept or advance queue from this diagnostic artifact.",
    }
    receipt_hash = _write_json(run_root / "receipt.json", receipt)
    receipt["receipt_sha256"] = receipt_hash
    (run_root / "review.html").write_text(_html_review(run_root, rows, receipt), encoding="utf-8")
    print(json.dumps({"run_root": str(run_root), "review": str(run_root / "review.html"), "summary": summary}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
