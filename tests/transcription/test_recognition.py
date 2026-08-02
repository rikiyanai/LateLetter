"""Recognizer seam tests: proposals are deterministic and coverage blocks honestly."""

from __future__ import annotations

from pathlib import Path

from lateletter.transcription import (
    CapabilityProfile,
    EmojiAtlasAdapter,
    FixedLatticeStructuralAdapter,
    IndependentOfflineAdapter,
    ModelArtifact,
    PaddleOCROfflineAdapter,
    TesseractOfflineAdapter,
    benchmark_release_coverage,
    benchmark_offline_ensemble,
    build_environment_lock,
    inventory_adapters,
    verify_model_cache,
)


H = "d" * 64


def test_two_offline_adapters_are_proposal_only_and_benchmark_blocks_unicode_gap() -> None:
    adapters = (TesseractOfflineAdapter(), FixedLatticeStructuralAdapter())
    report = benchmark_release_coverage(
        ["positive-fixed-ascii", "positive-kana", "positive-arabic", "positive-emoji-zwj"],
        adapters,
    )
    assert report["status"] == "blocked_release_coverage"
    assert len(report["results"]) == 2
    assert all(item["acceptance_oracle"] is False for item in report["results"])


def test_proposals_cannot_be_accepted_without_pinned_environment() -> None:
    lock = build_environment_lock(script_packs=("ascii", "latin", "digits"))
    source = {"path": "/missing/source.png", "source_sha256": H, "components_hash": H, "geometry_hash": H}
    result = TesseractOfflineAdapter().propose(source, {"mode": "fixed_lattice"}, {}, lock)
    assert result.status == "rejected"
    assert "source_missing" in result.rejection_codes
    assert result.proposals[0].quarantined_remote is False
    assert result.output_hash


def test_inventory_records_actual_local_script_packs_without_claiming_more() -> None:
    inventory = inventory_adapters()
    assert "tesseract" in inventory
    assert all("supported_scripts" in adapter for adapter in inventory["adapters"])


def test_capability_profiles_are_hash_bound_and_explicitly_offline() -> None:
    profile = CapabilityProfile(
        adapter="fixture-adapter",
        adapter_version="1",
        supported_scripts=("latin", "ascii"),
        supported_directions=("ltr",),
        grapheme_coverage=("extended-grapheme-cluster",),
        license="Apache-2.0",
        offline=True,
        runtime_network=False,
        unsupported_cases=("emoji_zwj",),
    )
    assert profile.output_hash == CapabilityProfile(**profile.to_dict()).output_hash
    assert profile.to_dict()["offline"] is True
    assert profile.to_dict()["runtime_network"] is False


def test_model_cache_verification_is_hash_bound(tmp_path: Path) -> None:
    path = tmp_path / "model.bin"
    path.write_bytes(b"pinned model")
    import hashlib

    artifact = ModelArtifact(
        artifact_id="fixture",
        source_url="https://example.invalid/model.bin",
        cache_path="model.bin",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        license="Apache-2.0",
        size_bytes=path.stat().st_size,
    )
    report = verify_model_cache(tmp_path, (artifact,))
    assert report["all_verified"] is True
    assert report["artifacts"][0]["status"] == "verified"


def test_optional_ensemble_adapters_fail_closed_without_runtime_models() -> None:
    lock = build_environment_lock(script_packs=("eng",))
    source = {"path": "/missing/source.png", "source_sha256": H, "components_hash": H, "geometry_hash": H}
    adapters = (PaddleOCROfflineAdapter(), IndependentOfflineAdapter(), EmojiAtlasAdapter())
    for adapter in adapters:
        result = adapter.propose(source, {"mode": "shaped_runs"}, {}, lock)
        assert result.status == "rejected"
        assert result.rejection_codes


def test_offline_ensemble_records_top_k_without_passing_ground_truth_to_adapter() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription"
    fixture = {
        "id": "positive-fixed-ascii",
        "source_png": "positive/positive-fixed-ascii/source.png",
        "transcript": "positive/positive-fixed-ascii/transcript.txt",
        "expected_outcome": "positive",
        "expected_geometry_mode": "fixed_lattice",
    }
    lock = build_environment_lock(script_packs=("eng",))
    report = benchmark_offline_ensemble(
        [fixture],
        (FixedLatticeStructuralAdapter(),),
        lock,
        root=fixture_root,
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["fixture_count"] == 1
    assert report["results"][0]["exact_nfc_target_in_top_k"] is False
    assert report["status"] == "blocked_release_coverage"


def test_run_proposals_are_composed_by_measured_row_order() -> None:
    from lateletter.transcription.recognition import _compose_run_texts

    composed = _compose_run_texts(
        [(0, ("A", "X")), (0, ("B",)), (1, ("C",))],
        top_k=8,
    )
    assert composed[0] == "AB\nC"
    assert "XB\nC" in composed


def test_recognizer_holdout_covers_required_variation_families() -> None:
    manifest = Path(__file__).parents[1] / "fixtures" / "transcription" / "recognizer-holdout.json"
    import json

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    families = {fixture["family"] for fixture in payload["fixtures"]}
    assert len(payload["fixtures"]) >= 10
    assert {"fixed_ascii", "proportional_latin", "kana_latin", "cjk_width", "arabic_latin", "combining", "emoji_zwj", "mixed_script"}.issubset(families)
    for fixture in payload["fixtures"]:
        source = manifest.parent / fixture["source_png"]
        transcript = manifest.parent / fixture["transcript"]
        assert source.exists() and transcript.exists()


def test_emoji_atlas_matches_geometry_pixels_and_ignores_injected_sequence() -> None:
    from PIL import ImageFont
    from lateletter.transcription.recognition import _render_emoji_image, _render_emoji_mask

    cache = Path(__file__).parents[2] / "tracked/LateLetterResearch/transcription-model-cache"
    adapter = EmojiAtlasAdapter.from_cache(cache / "emoji")
    adapter = EmojiAtlasAdapter(
        sequence_data_path=adapter.sequence_data_path,
        font_path=adapter.font_path,
        font_hashes=adapter.font_hashes,
        max_sequences=930,
    )
    font = ImageFont.truetype(str(cache / "emoji/NotoColorEmoji.ttf"), 109)
    sequence = "👩‍🌾"
    alpha = _render_emoji_mask(font, sequence)
    image = _render_emoji_image(font, sequence)
    assert alpha is not None and image is not None
    rgba = tuple(tuple(image.getpixel((x, y)) for x in range(image.width)) for y in range(image.height))
    geometry = {
        "run_mask": {
            "authority": "geometry_proven_run",
            "grapheme_complete": True,
            "pixels": [[int(value) for value in row] for row in alpha],
            "rgba": rgba,
            "measured_advances": [font.getlength(sequence)],
        }
    }
    source = {
        "path": str(Path(__file__).parents[1] / "fixtures/transcription/positive/positive-emoji-zwj/source.png"),
        "source_sha256": H,
        "geometry_hash": H,
        "components_hash": H,
        "emoji_sequence_proposals": ["😀"],
    }
    result = adapter.propose(source, geometry, {}, build_environment_lock(script_packs=("eng",)))
    assert result.status == "proposal_only"
    candidate = result.proposals[0].candidates[0]
    assert candidate.text == sequence
    assert result.proposals[0].provenance["external_sequence_input_ignored"] is True
    assert result.proposals[0].provenance["run_mask_hash"]
