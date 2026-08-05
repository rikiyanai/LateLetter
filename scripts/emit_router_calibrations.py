#!/usr/bin/env python3
"""Run the router calibration emitter across the tracked source queue.

What this script is
-------------------
``lateletter.transcription.geometry.calibration_emitter`` knows how to turn ONE
source PNG into ONE hash-bound calibration artifact, or to refuse with typed
reasons.  This script is the replay driver around it: it walks the tracked
26-source structural-art inventory, calls the emitter on every source, and
writes a single summary of what came out.

Why a replay driver exists at all
---------------------------------
Two questions can only be answered by running the whole queue twice:

1.  *Coverage* — which sources does the router prove well enough to calibrate,
    and which does it refuse, and for which named reason?
2.  *Determinism* — do two independent runs, in two fresh operating-system
    processes, produce byte-identical artifacts?  The emitter is write-once, so
    the second run's honest answer is a refusal
    (``emitter_artifact_already_present``) carrying the SHA-256 of the file
    already on disk.  Comparing that against the first run's recorded
    ``artifact_sha256`` is the determinism check.

Both runs write their summary to a path given on the command line, so the two
summaries can be diffed rather than trusted.

What this script must never do
------------------------------
It resolves source paths from the tracked inventory's ``source`` field and
opens the PNG only.  The ``.txt`` transcript that sits beside each PNG in the
same directory is never opened, and no accepted transcript is consulted.  The
emitter enforces that too; saying it twice is cheaper than discovering a leak.

Usage
-----
::

    PYTHONPATH=src python3 scripts/emit_router_calibrations.py <summary.json>

"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# The repository root, two levels up from this file (scripts/ -> repo).
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from lateletter.transcription.geometry import calibration_emitter  # noqa: E402

# The tracked inventory that names the 26 queue sources and their SHA-256s.
INVENTORY_PATH = (
    REPOSITORY_ROOT
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "geometry-replay"
    / "source-inventory-phase3-8-2026-08-04.json"
)

# Directory holding the queue's normalized PNGs.  The trailing space is part of
# the real directory name on this machine; it is not a typo.
SOURCE_ROOT = Path("/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES ")


def git_head() -> str:
    """Return the current commit hash, or a marker when git is unavailable.

    Recorded in the summary so a reader can tell which tree produced it.  This
    is metadata about the RUN, never part of any emitted artifact — artifacts
    must stay byte-identical across commits that do not change the emitter.
    """

    try:
        return subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def main(argv: list[str]) -> int:
    """Emit for every inventory source and write one summary document.

    :param argv: command-line arguments; ``argv[0]`` is the summary path.
    :returns: process exit status (0 always, unless the inventory is missing —
        a queue full of refusals is a legitimate result, not a failure).
    """

    if len(argv) != 1:
        print(__doc__)
        return 2
    summary_path = Path(argv[0])

    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    emitted = refused = errored = 0

    # Sorted by source name so the run order — and therefore the index's
    # read-modify-write sequence — does not depend on the inventory's ordering.
    for item in sorted(inventory["records"], key=lambda entry: str(entry["source"])):
        name = str(item["source"])
        source_path = SOURCE_ROOT / name
        if not source_path.exists():
            records.append(
                {"source": name, "status": "error", "error": "source_png_missing"}
            )
            errored += 1
            continue
        try:
            receipt = calibration_emitter.emit_calibration(
                source_path, expected_sha256=str(item["source_sha256"])
            )
        except Exception as exception:  # noqa: BLE001 - recorded, never hidden
            records.append(
                {
                    "source": name,
                    "status": "error",
                    "error": f"{type(exception).__name__}: {exception}",
                }
            )
            errored += 1
            continue
        # Trim the receipt down to the fields a replay comparison needs; the
        # full receipt already lives beside its artifact on disk.
        row: dict[str, object] = {
            "source": name,
            "source_sha256": receipt["source_sha256"],
            "status": receipt["status"],
        }
        if receipt["status"] == "emitted":
            emitted += 1
            row.update(
                {
                    "artifact_sha256": receipt["artifact_sha256"],
                    "grid": receipt["grid"],
                    "pitch_margins": receipt["pitch_margins"],
                    "phase_margins": receipt["phase_margins"],
                    "ownership_completeness": receipt["ownership_completeness"],
                    "baseline_regularity": receipt["baseline_regularity"],
                    "boundary_ink_legality": receipt["boundary_ink_legality"],
                }
            )
        else:
            refused += 1
            row.update(
                {
                    "refusal_reasons": receipt["refusal_reasons"],
                    "geometry_mode": receipt["geometry_mode"],
                    # Present only for the write-once refusal; this is the hash
                    # a determinism replay compares against run one.
                    "existing_artifact_sha256": receipt.get("existing_artifact_sha256"),
                }
            )
        records.append(row)

    summary = {
        "purpose": "router-emitted calibration replay over the tracked source queue",
        "emitter": {
            "name": calibration_emitter.EMITTER_NAME,
            "version": calibration_emitter.EMITTER_VERSION,
        },
        "git_head": git_head(),
        "inventory_path": str(INVENTORY_PATH.relative_to(REPOSITORY_ROOT)),
        "counts": {
            "total": len(records),
            "emitted": emitted,
            "refused": refused,
            "error": errored,
        },
        "transcript_input": False,
        "records": records,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"emitted={emitted} refused={refused} error={errored} -> {summary_path}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
