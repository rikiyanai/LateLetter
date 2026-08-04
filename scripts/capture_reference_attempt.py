#!/usr/bin/env python3
"""Capture proposal evidence from one normalized PNG.

This is an evidence writer, not a transcript or acceptance path. It refuses an existing attempt
directory, derives geometry and run strips from the source raster, and records the current offline
proposal report. It deliberately emits no candidate TXT: a proposal is not a transcription.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from lateletter.transcription.geometry import (
    build_recognition_hypothesis_inputs,
    build_recognition_inputs,
    route_raster_geometry,
)
from lateletter.transcription.hashing import sha256_bytes, sha256_file
from lateletter.transcription.recognition import (
    FixedLatticeStructuralAdapter,
    StructuralUnicodeRowAdapter,
    TesseractOfflineAdapter,
    benchmark_offline_ensemble,
    build_environment_lock,
)


def write_json(path: Path, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return sha256_bytes(payload.encode("utf-8"))


def write_geometry_overlay(
    source: Path,
    destination: Path,
    bundle: object,
    decision: object,
) -> str:
    """Write a source-sized review overlay before any recognizer runs.

    This is diagnostic geometry only: it never paints a candidate transcript.
    For a rejected decision the best measured lattice candidate is still shown
    so a reviewer can see why the geometry was rejected.
    """

    image = Image.open(source).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    payload = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle)
    selected = getattr(decision, "provenance", {}).get("selected_geometry")
    if not selected:
        candidates = payload.get("fixed_lattice_candidates") or []
        selected = candidates[0] if candidates else None
    for row in payload.get("row_band_candidates", []):
        y0, y1 = int(row["y0"]), int(row["y1"])
        draw.line((0, y0, image.width - 1, y0), fill=(255, 64, 64, 210), width=1)
        draw.line((0, max(y0, y1 - 1), image.width - 1, max(y0, y1 - 1)), fill=(255, 64, 64, 210), width=1)
    # Orange alternatives expose harmonic/phase competition even when the
    # blank-gap bands are later rejected as under-segmented.  Keep the leading
    # phases for the measured pitch family near the horizontal advance, plus
    # the strongest rejected candidate, so a review cannot hide a one-pixel
    # phase tie or terminal sliver.
    periodic = list(payload.get("projection_evidence", {}).get("periodic_row_candidates", []))
    reference = next(
        (float(item.get("horizontal_advance_reference")) for item in periodic if item.get("horizontal_advance_reference")),
        None,
    )
    families = {}
    for candidate in periodic:
        pitch = int(candidate.get("pitch", 0))
        if reference is None or abs(pitch - reference) <= 4:
            families.setdefault(pitch, []).append(candidate)
    review_candidates = []
    for pitch in sorted(families):
        family = sorted(families[pitch], key=lambda item: (not bool(item.get("valid")), -float(item.get("independent_score", 0.0))))
        review_candidates.extend(family[:2])
    rejected = [item for item in periodic if not item.get("valid")]
    if rejected:
        review_candidates.append(max(rejected, key=lambda item: float(item.get("independent_score", 0.0))))
    colors = ((255, 170, 0, 150), (40, 190, 120, 150), (180, 80, 255, 150), (255, 110, 30, 180))
    for index, candidate in enumerate(review_candidates):
        color = colors[index % len(colors)]
        for y0, y1 in candidate.get("row_bounds", []):
            draw.line((0, int(y0), image.width - 1, int(y0)), fill=color, width=1)
            draw.line((0, max(int(y0), int(y1) - 1), image.width - 1, max(int(y0), int(y1) - 1)), fill=color, width=1)
    if selected and selected.get("mode") == "fixed_lattice":
        origin = int(selected.get("origin_x", 0))
        advance = max(1, int(round(float(selected.get("advance_x", image.width)))))
        for x in range(origin, image.width + advance, advance):
            draw.line((x, 0, x, image.height - 1), fill=(40, 120, 255, 180), width=1)
    elif selected and selected.get("mode") == "shaped_runs":
        for anchor in selected.get("run_anchors", []):
            draw.rectangle(
                (int(anchor["x0"]), int(anchor["y0"]), int(anchor["x1"]) - 1, int(anchor["y1"]) - 1),
                outline=(40, 120, 255, 210),
                width=1,
            )
    image.save(destination, format="PNG", optimize=False)
    if image.size != (int(payload["canvas"]["width"]), int(payload["canvas"]["height"])):
        raise ValueError("geometry overlay is not source-sized")
    return sha256_file(destination)


def write_geometry_contact_sheet(source: Path, destination: Path, bundle: object) -> str:
    """Write candidate seam panels for geometry review only."""

    image = Image.open(source).convert("RGBA")
    payload = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle)
    periodic = list(payload.get("projection_evidence", {}).get("periodic_row_candidates", []))
    reference = next(
        (float(item.get("horizontal_advance_reference")) for item in periodic if item.get("horizontal_advance_reference")),
        None,
    )
    families: dict[int, list[dict[str, object]]] = {}
    for item in periodic:
        pitch = int(item.get("pitch", 0))
        if reference is None or abs(pitch - reference) <= 4:
            families.setdefault(pitch, []).append(item)
    candidates: list[dict[str, object]] = []
    for pitch in sorted(families):
        family = sorted(families[pitch], key=lambda item: (not bool(item.get("valid")), -float(item.get("independent_score", 0.0))))
        candidates.extend(family[:2])
    rejected = [item for item in periodic if not item.get("valid")]
    if rejected:
        candidates.append(max(rejected, key=lambda item: float(item.get("independent_score", 0.0))))
    candidates = candidates[:12]
    if not candidates:
        candidates = [{"pitch": 0, "phase": 0, "row_bounds": [], "valid": False}]
    panel_width, panel_height = image.width, image.height
    columns = min(3, len(candidates))
    rows = (len(candidates) + columns - 1) // columns
    sheet = Image.new("RGBA", (panel_width * columns, panel_height * rows), (245, 245, 245, 255))
    colors = ((255, 170, 0, 180), (40, 190, 120, 180), (180, 80, 255, 180), (255, 110, 30, 210))
    for index, candidate in enumerate(candidates):
        panel = image.copy()
        draw = ImageDraw.Draw(panel, "RGBA")
        color = colors[index % len(colors)]
        for y0, y1 in candidate.get("row_bounds", []):
            draw.line((0, int(y0), panel.width - 1, int(y0)), fill=color, width=1)
            draw.line((0, max(int(y0), int(y1) - 1), panel.width - 1, max(int(y0), int(y1) - 1)), fill=color, width=1)
        label = f"pitch={candidate.get('pitch')} phase={candidate.get('phase')} {'valid' if candidate.get('valid') else 'REJECTED'}"
        draw.rectangle((0, 0, min(panel.width, 260), 14), fill=(0, 0, 0, 180))
        draw.text((3, 2), label, fill=(255, 255, 255, 255))
        x = (index % columns) * panel_width
        y = (index // columns) * panel_height
        sheet.alpha_composite(panel, (x, y))
    sheet.save(destination, format="PNG", optimize=False)
    return sha256_file(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("attempt", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("tracked/LateLetterResearch/transcription-model-cache"))
    parser.add_argument("--geometry-only", action="store_true", help="stop after geometry evidence and review artifacts")
    args = parser.parse_args()
    source = args.source.resolve()
    attempt = args.attempt.resolve()
    if attempt.exists():
        raise SystemExit(f"refusing existing attempt directory: {attempt}")
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")

    bundle, decision = route_raster_geometry(source)
    attempt.mkdir(parents=True)
    source_copy = attempt / "source.png"
    shutil.copy2(source, source_copy)
    source_hash = sha256_file(source)
    source_receipt = {
        "schema_version": "lateletter-reference-attempt-1",
        "source_path": str(source),
        "source_sha256": source_hash,
        "attempt_source_sha256": sha256_file(source_copy),
        "canvas": dict(bundle.canvas),
        "source_mode": "RGBA-preserved; geometry consumes RGB projection",
    }
    source_receipt_hash = write_json(attempt / "source-receipt.json", source_receipt)
    geometry_payload = {
        "decision": decision.to_dict(),
        "bundle": bundle.to_dict(),
    }
    geometry_hash = write_json(attempt / "geometry.json", geometry_payload)
    geometry_overlay_hash = write_geometry_overlay(source, attempt / "geometry-overlay.png", bundle, decision)
    geometry_contact_hash = write_geometry_contact_sheet(source, attempt / "geometry-contact-sheet.png", bundle)
    if decision.mode == "unresolved":
        # Preserve measured hypothesis strips for a future joint decoder. They
        # remain proposal-only evidence and can never become candidate TXT.
        hypotheses = build_recognition_hypothesis_inputs(source, bundle)
        hypothesis_hash = write_json(
            attempt / "recognition-hypotheses.json",
            {
                "authority": "proposal_only",
                "source_sha256": source_hash,
                "geometry_sha256": geometry_hash,
                "count": len(hypotheses),
                "inputs": list(hypotheses),
                "candidate_txt": None,
                "accepted_txt": None,
            },
        )
        # Run the real proposal seam over every measured hypothesis.  This is
        # intentionally a separate JSON evidence artifact: unresolved geometry
        # may be compared jointly with row proposals, but it still cannot
        # write candidate.txt or accepted.txt.
        proposal_report = benchmark_offline_ensemble(
            [
                {
                    "id": attempt.name,
                    "source_png": str(source),
                    "expected_outcome": "rejected",
                }
            ],
            (StructuralUnicodeRowAdapter(),),
            build_environment_lock(script_packs=("ascii", "japanese", "cjk")),
            top_k=3,
        )
        proposal_hash = write_json(attempt / "recognition-proposals.json", proposal_report)
        joint_reviews = []
        for result in proposal_report.get("results", []):
            for adapter in result.get("adapters", []):
                decoder = adapter.get("joint_decoder")
                if decoder is not None:
                    joint_reviews.append(
                        {
                            "fixture": result.get("fixture"),
                            "adapter": adapter.get("adapter"),
                            "geometry_status": adapter.get("geometry_status"),
                            "joint_decoder": decoder,
                        }
                    )
        joint_review_hash = write_json(
            attempt / "joint-review.json",
            {
                "authority": "review_candidate_only",
                "candidate_txt": None,
                "accepted_txt": None,
                "reviews": joint_reviews,
            },
        )
        joint_reasons = sorted(
            {
                str(reason)
                for item in joint_reviews
                for reason in item.get("joint_decoder", {}).get("rejection_reasons", [])
            }
        )
        gate = {
            "status": "rejected_geometry_unresolved",
            "rejection_reasons": sorted(set((*decision.rejection_reasons, *joint_reasons))),
            "geometry_overlay_sha256": geometry_overlay_hash,
            "geometry_contact_sheet_sha256": geometry_contact_hash,
            "recognition_hypotheses_sha256": hypothesis_hash,
            "recognition_proposals_sha256": proposal_hash,
            "joint_review_sha256": joint_review_hash,
            "recognition": "proposal_only; joint alignment diagnostic; no candidate authority",
        }
        gate_hash = write_json(attempt / "gate-report.json", gate)
        manifest = {
            "schema_version": "lateletter-reference-attempt-1",
            "attempt": attempt.name,
            "status": gate["status"],
            "source_receipt_sha256": source_receipt_hash,
            "geometry_sha256": geometry_hash,
            "recognition_hypotheses_sha256": hypothesis_hash,
            "recognition_proposals_sha256": proposal_hash,
            "joint_review_sha256": joint_review_hash,
            "gate_report_sha256": gate_hash,
            "artifacts": {"source": "source.png", "source_receipt": "source-receipt.json", "geometry": "geometry.json", "geometry_overlay": "geometry-overlay.png", "geometry_contact_sheet": "geometry-contact-sheet.png", "recognition_hypotheses": "recognition-hypotheses.json", "recognition_proposals": "recognition-proposals.json", "joint_review": "joint-review.json", "gate_report": "gate-report.json"},
        }
        write_json(attempt / "manifest.json", manifest)
        return 2

    if args.geometry_only:
        gate = {
            "status": "geometry_only_review_pending",
            "geometry_status": decision.status,
            "geometry_mode": decision.mode,
            "geometry_overlay_sha256": geometry_overlay_hash,
            "geometry_contact_sheet_sha256": geometry_contact_hash,
            "recognition": "not_run",
            "candidate_sha256": None,
            "rejection_reasons": ["operator_geometry_review_pending"],
        }
        gate_hash = write_json(attempt / "gate-report.json", gate)
        manifest = {
            "schema_version": "lateletter-reference-attempt-1",
            "attempt": attempt.name,
            "status": gate["status"],
            "source_receipt_sha256": source_receipt_hash,
            "geometry_sha256": geometry_hash,
            "geometry_overlay_sha256": geometry_overlay_hash,
            "geometry_contact_sheet_sha256": geometry_contact_hash,
            "candidate_sha256": None,
            "gate_report_sha256": gate_hash,
            "artifacts": {
                "source": "source.png",
                "source_receipt": "source-receipt.json",
                "geometry": "geometry.json",
                "geometry_overlay": "geometry-overlay.png",
                "geometry_contact_sheet": "geometry-contact-sheet.png",
                "gate_report": "gate-report.json",
            },
            "accepted_txt": None,
            "renderer": {"status": "not_run", "reason": "geometry_only"},
        }
        write_json(attempt / "manifest.json", manifest)
        print(json.dumps({"status": gate["status"], "attempt": str(attempt), "candidate_sha256": None}, ensure_ascii=False))
        return 2

    inputs = build_recognition_inputs(source, bundle, mode=decision.mode)
    inputs_hash = write_json(attempt / "recognition-inputs.json", inputs)
    model_paths = {path.stem: str(path) for path in (args.cache / "tesseract_best").glob("*.traineddata")}
    script_packs = tuple(sorted(model_paths))
    lock = build_environment_lock(
        model_paths=model_paths,
        script_packs=script_packs,
        preprocessing={"network": "disabled", "source_only": True},
    )
    fixture = {
        "id": "sitting-cat",
        "source_png": str(source),
        # Capture has no operator-approved evaluation truth.  A proposal
        # report must therefore remain diagnostic and cannot manufacture a
        # positive release fixture.
        "expected_outcome": "rejected",
    }
    adapters = (
        TesseractOfflineAdapter(
            cache_dir=str(args.cache / "tesseract_best"),
            languages=("eng", "jpn", "jpn_vert", "chi_sim", "chi_tra", "ara"),
        ),
        FixedLatticeStructuralAdapter(),
        StructuralUnicodeRowAdapter(),
    )
    report = benchmark_offline_ensemble([fixture], adapters, lock, root=None)
    report_hash = write_json(attempt / "proposal-report.json", report)
    gate = {
        "status": "rejected_proposal_only",
        "geometry_status": decision.status,
        "geometry_mode": decision.mode,
        "recognition_input_hash": inputs["input_hash"],
        "geometry_overlay_sha256": geometry_overlay_hash,
        "geometry_contact_sheet_sha256": geometry_contact_hash,
        "proposal_report_sha256": report_hash,
        "candidate_sha256": None,
        "candidate_profile": None,
        "candidate_review": "not_emitted",
        "comparison": "not_run_before_proposal_gate",
        "rejection_reasons": ["proposal_only_no_transcript", "exact_nfc_target_unavailable", "recognizer_coverage_not_proven", "operator_review_pending"],
    }
    gate_hash = write_json(attempt / "gate-report.json", gate)
    manifest = {
        "schema_version": "lateletter-reference-attempt-1",
        "attempt": attempt.name,
        "status": gate["status"],
        "source_receipt_sha256": source_receipt_hash,
        "geometry_sha256": geometry_hash,
        "recognition_inputs_sha256": inputs_hash,
        "proposal_report_sha256": report_hash,
        "candidate_sha256": None,
        "gate_report_sha256": gate_hash,
        "artifacts": {
            "source": "source.png",
            "source_receipt": "source-receipt.json",
            "geometry": "geometry.json",
            "geometry_overlay": "geometry-overlay.png",
            "geometry_contact_sheet": "geometry-contact-sheet.png",
            "recognition_inputs": "recognition-inputs.json",
            "proposal_report": "proposal-report.json",
            "gate_report": "gate-report.json",
        },
        "accepted_txt": None,
        "renderer": {"status": "not_run", "reason": "proposal_gate_rejected"},
    }
    write_json(attempt / "manifest.json", manifest)
    print(json.dumps({"status": gate["status"], "attempt": str(attempt), "candidate_sha256": None}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
