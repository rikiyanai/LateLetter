"""Recognizer seam tests: proposals are deterministic and coverage blocks honestly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lateletter.transcription import (
    CapabilityProfile,
    EmojiAtlasAdapter,
    FixedLatticeStructuralAdapter,
    StructuralUnicodeRowAdapter,
    UnicodeTemplateRunAdapter,
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
from lateletter.transcription.recognition import (
    _coverage_rank_matrix,
    _fixture_exact_top_k_from_matrix,
    _arabic_ocr_variants,
    _degraded_horizontal_sequence_from_run_mask,
    _latin_cjk_ocr_variants,
    _ocr_latin_confusable_variants,
    _ocr_source_gap_variants,
    _ocr_source_width_variants,
    _tesseract_profile_runs,
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


def test_unicode_template_adapter_fails_closed_without_hash_pinned_font() -> None:
    adapter = UnicodeTemplateRunAdapter()
    source = {"path": "/missing/source.png", "source_sha256": H, "components_hash": H, "geometry_hash": H}
    result = adapter.propose(
        source,
        {
            "mode": "fixed_lattice",
            "run_mask": {"authority": "geometry_proven_run", "pixels": ["0000", "0000"]},
        },
        {},
        build_environment_lock(),
    )
    assert result.status == "rejected"
    assert "template_font_unpinned" in result.rejection_codes
    assert result.proposals[0].candidates[0].text == "?"


def test_unicode_template_adapter_emits_hash_bound_component_owned_proposals() -> None:
    adapter = UnicodeTemplateRunAdapter(beam_width=3, top_k=3)
    font = "/Library/Fonts/DejaVuSans.ttf"
    lock = build_environment_lock(model_paths={"unicode-template-latin.font": font})
    source = {"path": "/missing/source.png", "source_sha256": H, "components_hash": H, "geometry_hash": H, "component_ids": ["c000002", "c000001"]}
    geometry = {
        "mode": "fixed_lattice",
        "mixed_width_display": {"base_advance_px": 12.0},
        "run_mask": {
            "authority": "geometry_proven_run",
            "run_id": "r000",
            "pixels": ["000000000000", "001111110000", "001111110000", "000000000000"],
            "measured_advances": [12.0],
            "component_ids": ["c000002", "c000001"],
        },
    }
    first = adapter.propose(source, geometry, {}, lock)
    second = adapter.propose(source, geometry, {}, lock)
    assert first.status == "proposal_only"
    assert first.output_hash == second.output_hash
    assert first.proposals and first.proposals[0].candidates
    assert all(candidate.component_ids == ("c000001", "c000002") for candidate in first.proposals[0].candidates)
    assert first.proposals[0].provenance["source_only"] is True
    assert first.proposals[0].provenance["ground_truth_input"] is False


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


def test_independent_comparator_profiles_keep_backend_identity() -> None:
    lock = build_environment_lock(script_packs=("eng",))
    adapters = (
        IndependentOfflineAdapter(backend="easyocr", name="independent-offline-easyocr"),
        IndependentOfflineAdapter(backend="surya", name="independent-offline-surya"),
    )
    names = tuple(adapter.capability_profile(lock).adapter for adapter in adapters)
    assert names == ("independent-offline-easyocr", "independent-offline-surya")
    assert len(set(names)) == len(names)


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
    matrix = report["coverage_rank_matrix"][0]
    assert matrix["status"] == "measured"
    assert [row["expected_logical_sequence"] for row in matrix["rows"]] == ["/\\_|", "(=)"]
    assert all(row["classification"] in {"absent", "unsupported", "present_and_winning", "present_but_losing", "visual_collision"} for row in matrix["rows"])
    assert report["results"][0]["coverage_rank_matrix"] == matrix
    assert report["status"] == "blocked_release_coverage"


def test_v2_fixed_ascii_structural_adapter_recovers_exact_rows_without_truth_input() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-fixed-ascii")
    report = benchmark_offline_ensemble(
        [fixture],
        (FixedLatticeStructuralAdapter(),),
        build_environment_lock(script_packs=("ascii",)),
        root=fixture_root,
        adapter_budgets_seconds={"fixed-lattice-structural": 5.0},
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["positive_missing"] == []
    assert report["results"][0]["exact_nfc_target_in_top_k"] is True
    rows = report["coverage_rank_matrix"][0]["rows"]
    assert [(row["expected_logical_sequence"], row["classification"], row["proposal_rank"]) for row in rows] == [
        ("/\\_|", "present_and_winning", 1),
        ("(=)", "present_and_winning", 1),
    ]


def test_ocr_latin_confusable_variants_promote_contextual_l_words() -> None:
    variants = _ocr_latin_confusable_variants("| ate |etter")
    assert "Late letter" in variants[:5]
    assert variants.index("Late letter") < variants.index("| ate |etter")
    assert "café é" not in _ocr_latin_confusable_variants("cafe=")


def test_ocr_source_gap_variants_use_measured_run_count_only() -> None:
    source = {"anchor_evidence": {"source_run_count": 2, "source_run_ids": ["left", "right"]}}

    assert "春 花" in _ocr_source_gap_variants("春花", source)
    assert "かな カナ" in _ocr_source_gap_variants("か な カナ", source)
    assert _ocr_source_gap_variants("春花", {"anchor_evidence": {"source_run_count": 1}}) == ()


def test_ocr_source_width_variants_use_run_masks_and_advances_without_truth_input() -> None:
    from lateletter.transcription.geometry import build_recognition_inputs, route_raster_geometry

    source_path = Path(__file__).parents[1] / "fixtures/transcription-v2/positive/positive-width-mixture/source.png"
    geometry_bundle, decision = route_raster_geometry(source_path)
    assert decision.status == "proved"
    inputs = build_recognition_inputs(source_path, geometry_bundle, mode=decision.mode)
    rows = _tesseract_profile_runs(source_path, inputs)
    assert rows[0]["anchor_evidence"]["source_run_count"] == 3

    variants = _ocr_source_width_variants("AB が", {"anchor_evidence": rows[0]["anchor_evidence"]}, limit=16)

    assert "ＡB ｶﾅ" in variants
    assert all("positive-width-mixture" not in value for value in variants)


def test_v2_proportional_latin_tesseract_variants_cover_target_without_truth_input() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    cache = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-model-cache" / "tesseract_best"
    if not (cache / "eng.traineddata").exists():
        pytest.skip("project-local Tesseract eng traineddata is not available")

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-proportional-latin")
    model_paths = {path.stem: str(path) for path in cache.glob("*.traineddata")}
    report = benchmark_offline_ensemble(
        [fixture],
        (TesseractOfflineAdapter(cache_dir=str(cache)),),
        build_environment_lock(
            model_paths=model_paths,
            script_packs=tuple(sorted(model_paths)),
            preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        ),
        root=fixture_root,
        adapter_budgets_seconds={"tesseract-offline": 12.0},
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["positive_missing"] == []
    assert report["results"][0]["exact_nfc_target_in_top_k"] is True
    rows = report["coverage_rank_matrix"][0]["rows"]
    assert rows[0]["expected_logical_sequence"] == "Late letter"
    assert rows[0]["classification"] == "present_and_winning"
    assert rows[0]["proposal_rank"] == 1
    assert rows[1]["expected_logical_sequence"] == "kindness"
    assert rows[1]["classification"] == "present_and_winning"


def test_tesseract_profile_uses_shaped_row_strips_without_merging_truth() -> None:
    source = Path(__file__).parents[1] / "fixtures" / "transcription-v2" / "positive" / "positive-combining" / "source.png"
    variant = {
        "mode": "shaped_runs",
        "runs": (
            {
                "run_id": "left",
                "row_index": 0,
                "source_bounds": [13, 19, 54, 38],
                "binary_run_mask": ["1" * 41 for _ in range(19)],
                "run_strip_png_base64": "present",
                "component_ids": ["c2", "c1"],
            },
            {
                "run_id": "right",
                "row_index": 0,
                "source_bounds": [60, 19, 71, 38],
                "binary_run_mask": ["1" * 11 for _ in range(19)],
                "run_strip_png_base64": "present",
                "component_ids": ["c3"],
            },
        ),
    }

    rows = _tesseract_profile_runs(source, variant)

    assert len(rows) == 1
    assert rows[0]["run_id"] == "ocr-row-r000"
    assert rows[0]["component_ids"] == ["c1", "c2", "c3"]
    assert rows[0]["anchor_evidence"]["source_run_ids"] == ["left", "right"]
    assert rows[0]["anchor_evidence"]["source_text_group_count"] == 2


def test_v2_combining_latin_tesseract_covers_source_row_without_detached_mark_rewrite() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    cache = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-model-cache" / "tesseract_best"
    if not (cache / "eng.traineddata").exists():
        pytest.skip("project-local Tesseract eng traineddata is not available")

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-combining")
    model_paths = {path.stem: str(path) for path in cache.glob("*.traineddata")}
    report = benchmark_offline_ensemble(
        [fixture],
        (TesseractOfflineAdapter(cache_dir=str(cache)),),
        build_environment_lock(
            model_paths=model_paths,
            script_packs=tuple(sorted(model_paths)),
            preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        ),
        root=fixture_root,
        adapter_budgets_seconds={"tesseract-offline": 12.0},
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["positive_missing"] == []
    assert report["results"][0]["exact_nfc_target_in_top_k"] is True
    rows = report["coverage_rank_matrix"][0]["rows"]
    assert [(row["expected_logical_sequence"], row["classification"], row["proposal_rank"]) for row in rows] == [
        ("café é", "present_and_winning", 1),
    ]


def test_v2_tesseract_row_context_covers_kana_kanji_and_combining_without_truth_input() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    cache = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-model-cache" / "tesseract_best"
    if not (cache / "eng.traineddata").exists() or not (cache / "jpn.traineddata").exists() or not (cache / "chi_sim.traineddata").exists():
        pytest.skip("project-local Tesseract eng/jpn/chi_sim traineddata is not available")

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    wanted = {"positive-kana", "positive-kanji", "positive-combining"}
    fixtures = [item for item in corpus["fixtures"] if item["id"] in wanted]
    model_paths = {path.stem: str(path) for path in cache.glob("*.traineddata")}
    report = benchmark_offline_ensemble(
        fixtures,
        (TesseractOfflineAdapter(cache_dir=str(cache), languages=("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra")),),
        build_environment_lock(
            model_paths=model_paths,
            script_packs=tuple(sorted(model_paths)),
            preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        ),
        root=fixture_root,
        adapter_budgets_seconds={"tesseract-offline": 12.0},
        deterministic_replay=True,
        top_k=8,
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["nondeterministic_adapters"] == []
    assert report["positive_missing"] == []
    rows_by_fixture = {
        matrix["fixture"]: matrix["rows"][0]
        for matrix in report["coverage_rank_matrix"]
    }
    assert rows_by_fixture["positive-kana"]["classification"] == "present_and_winning"
    assert rows_by_fixture["positive-kana"]["proposal_rank"] == 1
    assert rows_by_fixture["positive-kanji"]["classification"] == "present_and_winning"
    assert rows_by_fixture["positive-kanji"]["proposal_rank"] == 1
    assert rows_by_fixture["positive-combining"]["classification"] == "present_and_winning"
    assert rows_by_fixture["positive-combining"]["proposal_rank"] == 1


def test_v2_tesseract_width_mixture_uses_source_run_anchors_without_truth_input() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    cache = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-model-cache"
    tessdata = cache / "tesseract_best"
    cjk_font = cache / "fonts/NotoSansCJKjp-Regular.otf"
    if not (tessdata / "jpn.traineddata").exists() or not (tessdata / "chi_sim.traineddata").exists() or not cjk_font.exists():
        pytest.skip("project-local Tesseract jpn/chi_sim data and CJK template font are not available")

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-width-mixture")
    model_paths = {path.stem: str(path) for path in tessdata.glob("*.traineddata")}
    model_paths["unicode-template-kana.font"] = str(cjk_font)
    report = benchmark_offline_ensemble(
        [fixture],
        (TesseractOfflineAdapter(cache_dir=str(tessdata), languages=("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra")),),
        build_environment_lock(
            model_paths=model_paths,
            script_packs=tuple(sorted(model_paths)),
            preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        ),
        root=fixture_root,
        adapter_budgets_seconds={"tesseract-offline": 12.0},
        deterministic_replay=True,
        top_k=5,
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["nondeterministic_adapters"] == []
    assert report["positive_missing"] == []
    row = report["coverage_rank_matrix"][0]["rows"][0]
    assert row["expected_logical_sequence"] == "ＡB ｶﾅ"
    assert row["classification"] == "present_and_winning"
    assert row["proposal_rank"] == 1


def test_fixture_exact_top_k_uses_row_matrix_not_adapter_union_order() -> None:
    matrix = {
        "status": "measured",
        "rows": [
            {"classification": "present_and_winning", "proposal_rank": 1},
            {"classification": "present_but_losing", "proposal_rank": 5},
        ],
    }
    assert _fixture_exact_top_k_from_matrix(matrix, top_k=5) is True
    assert _fixture_exact_top_k_from_matrix(matrix, top_k=4) is False
    assert _fixture_exact_top_k_from_matrix(
        {"status": "measured", "rows": [{"classification": "visual_collision", "proposal_rank": 1}]},
        top_k=5,
    ) is False


def test_row_coverage_records_unbound_collision_without_poisoning_exact_match() -> None:
    matrix = _coverage_rank_matrix(
        "A",
        [
            {
                "adapter": "wrong",
                "unsupported_status": ["unicode_visual_collision"],
                "row_proposals": [
                    {
                        "hypothesis_id": "h0",
                        "rows": [{"row_index": 0, "runs": [{"proposals": ["B"], "run_input_hash": H}]}],
                    }
                ],
            },
            {
                "adapter": "exact",
                "unsupported_status": [],
                "row_proposals": [
                    {
                        "hypothesis_id": "h1",
                        "rows": [{"row_index": 0, "runs": [{"proposals": ["A"], "run_input_hash": H}]}],
                    }
                ],
            },
        ],
        fixture_id="fixture",
        source_hash=H,
        geometry_status="proved",
        geometry_rejection_codes=[],
        top_k=5,
    )
    row = matrix["rows"][0]
    assert row["classification"] == "present_and_winning"
    assert row["collision_status_sources"] == ["wrong:unicode_visual_collision"]
    assert row["selected_wrong_result"] == [{"adapter": "wrong", "hypothesis_id": "h0", "text": "B"}]


def test_row_coverage_classifies_collision_only_when_winning_proposal_is_marked() -> None:
    matrix = _coverage_rank_matrix(
        "A",
        [
            {
                "adapter": "exact-collision",
                "unsupported_status": ["unicode_visual_collision"],
                "row_proposals": [
                    {
                        "hypothesis_id": "h0",
                        "rows": [
                            {
                                "row_index": 0,
                                "runs": [
                                    {
                                        "proposals": ["A", "Α"],
                                        "run_input_hash": H,
                                        "rejection_codes": ["unicode_visual_collision"],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        fixture_id="fixture",
        source_hash=H,
        geometry_status="proved",
        geometry_rejection_codes=[],
        top_k=5,
    )

    row = matrix["rows"][0]
    assert row["classification"] == "visual_collision"
    assert row["proposal_rank"] == 1
    assert row["observations"][0]["collision_codes"] == ["unicode_visual_collision"]


def test_fixed_ascii_source_png_recovers_both_rows_without_canvas_tail() -> None:
    """The terminal-width guard must preserve the literal structural rows."""

    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_inputs, route_raster_geometry

    source = Path(__file__).parents[1] / "fixtures" / "transcription" / "positive" / "positive-fixed-ascii" / "source.png"
    bundle, decision = route_raster_geometry(source)
    inputs = build_recognition_inputs(source, bundle, mode=decision.mode)
    lock = build_environment_lock(script_packs=("ascii",))
    rows: list[str] = []
    with TemporaryDirectory() as temp:
        for run in inputs["runs"]:
            row_path = Path(temp) / f"{run['row_index']}.png"
            row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
            proposal = StructuralUnicodeRowAdapter().propose(
                {
                    "path": str(row_path),
                    "source_sha256": run["run_strip_png_sha256"],
                    "geometry_hash": inputs["input_hash"],
                    "components_hash": inputs["components_hash"],
                    "run_id": run["run_id"],
                },
                {
                    "mode": "fixed_lattice",
                    "mixed_width_display": inputs["mixed_width_display"],
                    "run_mask": {
                        "authority": "geometry_proven_run",
                        "grapheme_complete": True,
                        "pixels": run["binary_run_mask"],
                    },
                },
                {},
                lock,
            )
            assert proposal.status == "proposal_only"
            rows.append(proposal.proposals[0].candidates[0].text)
    assert rows == ["/\\_|", "(=)"]


def test_proved_sitting_cat_geometry_still_keeps_recognition_proposal_only_without_txt() -> None:
    root = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity"
    fixture = {
        "id": "sitting-cat-hypothesis",
        "source_png": "sitting-cat/source/source.normalized.png",
        "expected_outcome": "rejected",
    }
    report = benchmark_offline_ensemble(
        [fixture],
        (FixedLatticeStructuralAdapter(),),
        build_environment_lock(script_packs=("ascii", "latin", "digits")),
        root=root,
        top_k=3,
    )
    result = report["results"][0]
    adapter = result["adapters"][0]
    assert result["geometry_status"] == "proved"
    assert result["recognition_input_hash"]
    assert adapter["geometry_status"] == "proved"
    assert adapter["status"] == "proposal_only"
    assert adapter["proposal_hypothesis_count"] == 0
    assert adapter["proposal_hypothesis_ids"] == []
    assert adapter["run_count"] > 0


def test_joint_score_keeps_raster_seams_in_the_hypothesis_rank() -> None:
    from lateletter.transcription import jointly_score_geometry_hypotheses

    ownership = {
        "owned_pixel_count": 1,
        "substantive_pixel_count": 1,
        "unowned_pixel_count": 0,
        "multiply_owned_pixel_count": 0,
    }
    hypotheses = [
        {
            "provenance": {
                "hypothesis": {
                    "pitch": 23,
                    "phase": 8,
                    "normalized_seam_energy": 0.04,
                    "seam_to_interior_contrast": 0.79,
                    "ownership": ownership,
                }
            },
            "mixed_width_display": {"base_advance_px": 10.0},
            "runs": [{"row_index": 0, "source_bounds": [0, 0, 10, 10]}],
        },
        {
            "provenance": {
                "hypothesis": {
                    "pitch": 23,
                    "phase": 7,
                    "normalized_seam_energy": 0.06,
                    "seam_to_interior_contrast": 0.64,
                    "ownership": ownership,
                }
            },
            "mixed_width_display": {"base_advance_px": 10.0},
            "runs": [{"row_index": 0, "source_bounds": [0, 0, 10, 10]}],
        },
    ]
    report = jointly_score_geometry_hypotheses(
        hypotheses,
        {"23:8": {0: ("a",)}, "23:7": {0: ("a",)}},
        top_k=1,
    )
    assert report["winner"]["phase"] == 8
    assert report["winner"]["geometry_score"] > report["runner_up"]["geometry_score"]
    assert report["candidate_txt"] is None


def test_joint_score_composes_complete_row_sequence_proposals() -> None:
    from lateletter.transcription import jointly_score_geometry_hypotheses

    ownership = {
        "owned_pixel_count": 2,
        "substantive_pixel_count": 2,
        "unowned_pixel_count": 0,
        "multiply_owned_pixel_count": 0,
    }
    hypotheses = [
        {
            "provenance": {
                "hypothesis": {
                    "pitch": 20,
                    "phase": 2,
                    "normalized_seam_energy": 0.02,
                    "seam_to_interior_contrast": 0.9,
                    "ownership": ownership,
                }
            },
            "mixed_width_display": {"base_advance_px": 10.0},
            "runs": [
                {"row_index": 0, "source_bounds": [0, 0, 10, 10]},
                {"row_index": 1, "source_bounds": [0, 10, 10, 20]},
            ],
        }
    ]
    report = jointly_score_geometry_hypotheses(
        hypotheses,
        {"20:2": {0: ("A", "B"), 1: ("C", "D")}},
        top_k=2,
    )
    winner = report["winner"]
    assert winner["best_logical_sequence"]["normalized_text"] == "A\nC"
    assert len(winner["logical_sequence_proposals"]) == 4
    assert all(item["evidence_hash"] for item in winner["logical_sequence_proposals"])
    assert report["candidate_txt"] is None


def test_joint_decoder_exposes_review_candidate_without_canonical_authority() -> None:
    from lateletter.transcription import jointly_decode_geometry_text

    ownership = {
        "owned_pixel_count": 2,
        "substantive_pixel_count": 2,
        "unowned_pixel_count": 0,
        "multiply_owned_pixel_count": 0,
    }
    hypotheses = [
        {
            "provenance": {
                "hypothesis": {
                    "pitch": 20,
                    "phase": 2,
                    "normalized_seam_energy": 0.02,
                    "seam_to_interior_contrast": 0.9,
                    "ownership": ownership,
                }
            },
            "mixed_width_display": {"base_advance_px": 10.0},
            "runs": [
                {"row_index": 0, "source_bounds": [0, 0, 10, 10]},
                {"row_index": 1, "source_bounds": [0, 10, 10, 20]},
            ],
        }
    ]
    report = jointly_decode_geometry_text(
        hypotheses,
        {"20:2": {0: ("A",), 1: ("C",)}},
    )
    assert report["status"] == "review_pending"
    assert report["review_candidate_txt"] == "A\nC"
    assert report["review_binding_sha256"]
    assert report["candidate_txt"] is None
    assert report["operator_review_required"] is True
    assert report["authority"] == "joint_review_candidate_only"


def test_sitting_cat_structural_unicode_refusal_is_diagnostic_only() -> None:
    root = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity"
    fixture = {
        "id": "sitting-cat-joint-diagnostic",
        "source_png": "sitting-cat/source/source.normalized.png",
        "expected_outcome": "rejected",
    }
    report = benchmark_offline_ensemble(
        [fixture],
        (StructuralUnicodeRowAdapter(beam_width=2),),
        build_environment_lock(script_packs=("ascii", "japanese", "cjk")),
        root=root,
        top_k=1,
        max_geometry_hypotheses=2,
    )
    result = report["results"][0]
    adapter = result["adapters"][0]
    assert result["geometry_status"] == "proved"
    assert adapter["status"] == "rejected"
    assert adapter["top_k_logical_sequences"] == []
    assert adapter["joint_alignment"] is None
    assert adapter["unsupported_status"] == ["structural_display_basis_unresolved"]
    assert adapter["proposal_hypothesis_count"] == 0


def test_sitting_cat_shaped_run_refusal_preserves_row_evidence_without_txt() -> None:
    """Proved geometry may still fail closed before any candidate TXT exists."""

    root = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity"
    fixture = {
        "id": "sitting-cat-nine-row-regression",
        "source_png": "sitting-cat/source/source.normalized.png",
        "expected_outcome": "rejected",
    }
    report = benchmark_offline_ensemble(
        [fixture],
        (StructuralUnicodeRowAdapter(beam_width=3),),
        build_environment_lock(script_packs=("ascii", "japanese", "cjk")),
        root=root,
        top_k=4,
        max_geometry_hypotheses=2,
    )
    result = report["results"][0]
    adapter = result["adapters"][0]
    assert result["geometry_status"] == "proved"
    assert result["recognition_input_hash"]
    assert adapter["run_count"] >= 9
    assert adapter["row_proposals"]
    assert {row["row_index"] for row in adapter["row_proposals"][0]["rows"]} == set(range(9))
    assert adapter["top_k_logical_sequences"] == []
    assert adapter["joint_alignment"] is None
    assert adapter["status"] == "rejected"


def test_structural_unicode_row_adapter_is_real_deterministic_proposal_source() -> None:
    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=1)[0]
    run = hypothesis["runs"][1]
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    with TemporaryDirectory() as temp:
        row_path = Path(temp) / "row.png"
        row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
        source = {
            "path": str(row_path),
            "source_sha256": run["run_strip_png_sha256"],
            "geometry_hash": hypothesis["input_hash"],
            "components_hash": hypothesis["components_hash"],
            "run_id": run["run_id"],
        }
        geometry = {
            "mode": "fixed_lattice",
            "mixed_width_display": hypothesis["mixed_width_display"],
            "run_mask": {
                "authority": "geometry_hypothesis_run",
                "grapheme_complete": True,
                "pixels": run["binary_run_mask"],
            },
        }
        adapter = StructuralUnicodeRowAdapter()
        first = adapter.propose(source, geometry, {}, lock)
        second = adapter.propose(source, geometry, {}, lock)
        assert first.status == "proposal_only"
        assert first.output_hash == second.output_hash
        assert first.proposals[0].candidates[0].text
        # The painted-cluster proposal must preserve the narrow slash/greater
        # pair and the wide Japanese フ as a row-level alternative.  It is
        # still only proposal evidence; no candidate TXT is written here.
        assert any(
            candidate.text.strip() == "/>  フ"
            for candidate in first.proposals[0].candidates
        )
        # The same measured run must also retain the wide-delimiter/ideographic
        # spacing family; width selection is downstream evidence, never a
        # reason to discard the Japanese proposal before joint decoding.
        assert any(
            candidate.text.strip().startswith("／") and "フ" in candidate.text
            for candidate in first.proposals[0].candidates
        )
    assert first.proposals[0].candidates[0].input_hashes["template_font"]


def test_structural_unicode_adapter_splits_connected_horizontal_run_at_lattice() -> None:
    """A connected three-column underline remains three narrow proposals."""

    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = next(
        item
        for item in build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=16)
        if item["provenance"]["hypothesis"]["pitch"] == 23
        and item["provenance"]["hypothesis"]["phase"] == 8
    )
    run = hypothesis["runs"][0]
    with TemporaryDirectory() as temp:
        row_path = Path(temp) / "row.png"
        row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
        proposal = StructuralUnicodeRowAdapter().propose(
            {
                "path": str(row_path),
                "source_sha256": run["run_strip_png_sha256"],
                "geometry_hash": hypothesis["input_hash"],
                "components_hash": hypothesis["components_hash"],
                "run_id": run["run_id"],
            },
            {
                "mode": "fixed_lattice",
                "mixed_width_display": hypothesis["mixed_width_display"],
                "run_mask": {
                    "authority": "geometry_hypothesis_run",
                    "grapheme_complete": True,
                    "pixels": run["binary_run_mask"],
                },
            },
            {},
            build_environment_lock(script_packs=("ascii", "japanese", "cjk")),
        )
    assert any(candidate.text.rstrip().endswith("___") for candidate in proposal.proposals[0].candidates)


def test_structural_unicode_adapter_keeps_middle_bar_and_dash_row_as_alternative() -> None:
    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = next(
        item
        for item in build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=16)
        if item["provenance"]["hypothesis"]["pitch"] == 23
        and item["provenance"]["hypothesis"]["phase"] == 8
    )
    run = hypothesis["runs"][2]
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    with TemporaryDirectory() as temp:
        row_path = Path(temp) / "row.png"
        row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
        source = {
            "path": str(row_path),
            "source_sha256": run["run_strip_png_sha256"],
            "geometry_hash": hypothesis["input_hash"],
            "components_hash": hypothesis["components_hash"],
            "run_id": run["run_id"],
        }
        geometry = {
            "mode": "fixed_lattice",
            "mixed_width_display": hypothesis["mixed_width_display"],
            "run_mask": {
                "authority": "geometry_hypothesis_run",
                "grapheme_complete": True,
                "pixels": run["binary_run_mask"],
            },
        }
        proposal = StructuralUnicodeRowAdapter().propose(source, geometry, {}, lock)
    assert any(candidate.text.strip() == "| _ _|" for candidate in proposal.proposals[0].candidates)


def test_structural_unicode_adapter_accepts_geometry_owned_shaped_runs() -> None:
    """Run-level structural proposals are not a second geometry router."""

    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_inputs, route_raster_geometry

    source_path = Path(__file__).parents[1] / "fixtures" / "transcription" / "positive" / "positive-proportional-latin" / "source.png"
    bundle, decision = route_raster_geometry(source_path)
    inputs = build_recognition_inputs(source_path, bundle, mode=decision.mode)
    run = inputs["runs"][0]
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    with TemporaryDirectory() as temp:
        row_path = Path(temp) / "row.png"
        row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
        proposal = StructuralUnicodeRowAdapter().propose(
            {
                "path": str(row_path),
                "source_sha256": run["run_strip_png_sha256"],
                "geometry_hash": inputs["input_hash"],
                "components_hash": inputs["components_hash"],
                "run_id": run["run_id"],
            },
            {
                "mode": "shaped_runs",
                "mixed_width_display": inputs["mixed_width_display"],
                "run_mask": {
                    "authority": "geometry_proven_run",
                    "grapheme_complete": True,
                    "pixels": run["binary_run_mask"],
                },
            },
            {},
            lock,
        )
    assert "geometry_mode_mismatch" not in proposal.rejection_codes


def test_structural_unicode_adapter_retains_lower_row_sequence_alternatives() -> None:
    """Connected rows must expose competing sequences instead of one greedy label."""

    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = next(
        item
        for item in build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=16)
        if item["provenance"]["hypothesis"]["pitch"] == 23
        and item["provenance"]["hypothesis"]["phase"] == 8
    )
    run = hypothesis["runs"][6]
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    with TemporaryDirectory() as temp:
        row_path = Path(temp) / "row.png"
        row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
        source = {
            "path": str(row_path),
            "source_sha256": run["run_strip_png_sha256"],
            "geometry_hash": hypothesis["input_hash"],
            "components_hash": hypothesis["components_hash"],
            "run_id": run["run_id"],
        }
        geometry = {
            "mode": "fixed_lattice",
            "mixed_width_display": hypothesis["mixed_width_display"],
            "run_mask": {
                "authority": "geometry_hypothesis_run",
                "grapheme_complete": True,
                "pixels": run["binary_run_mask"],
            },
        }
        first = StructuralUnicodeRowAdapter(beam_width=4).propose(source, geometry, {}, lock)
        second = StructuralUnicodeRowAdapter(beam_width=4).propose(source, geometry, {}, lock)
    candidates = first.proposals[0].candidates
    assert first.output_hash == second.output_hash
    assert len(candidates) >= 2
    assert len({candidate.text for candidate in candidates}) == len(candidates)
    from lateletter.transcription.recognition import _proposal_texts

    serialized_alternatives = {
        alternative
        for candidate in candidates
        for alternative in candidate.alternatives
    }
    surfaced = set(_proposal_texts(first, top_k=32))
    assert serialized_alternatives
    assert serialized_alternatives & surfaced


def test_run_level_candidates_preserve_source_component_ids() -> None:
    """A proposal claiming a run must retain the run's source ownership evidence."""

    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=16)[0]
    run = hypothesis["runs"][2]
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    with TemporaryDirectory() as temp:
        row_path = Path(temp) / "row.png"
        row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
        source = {
            "path": str(row_path),
            "source_sha256": run["run_strip_png_sha256"],
            "geometry_hash": hypothesis["input_hash"],
            "components_hash": hypothesis["components_hash"],
            "run_id": run["run_id"],
            "component_ids": ["c000002", "c000001"],
        }
        geometry = {
            "mode": "fixed_lattice",
            "mixed_width_display": hypothesis["mixed_width_display"],
            "run_mask": {
                "authority": "geometry_hypothesis_run",
                "grapheme_complete": True,
                "pixels": run["binary_run_mask"],
                "component_ids": ["c000002", "c000001"],
            },
        }
        proposal = StructuralUnicodeRowAdapter(beam_width=2).propose(source, geometry, {}, lock)
    candidates = proposal.proposals[0].candidates
    assert candidates
    assert all(candidate.component_ids == ("c000001", "c000002") for candidate in candidates)


def test_structural_unicode_adapter_uses_run_level_mixed_span_surface() -> None:
    """Connected cat rows are segmented by measured spans, not components."""

    from base64 import b64decode
    from tempfile import TemporaryDirectory
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = next(
        item
        for item in build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=16)
        if item["provenance"]["hypothesis"]["pitch"] == 23
        and item["provenance"]["hypothesis"]["phase"] == 8
    )
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    outputs: dict[int, tuple[str, ...]] = {}
    with TemporaryDirectory() as temp:
        for row_index in (2, 3):
            run = hypothesis["runs"][row_index]
            row_path = Path(temp) / f"row-{row_index}.png"
            row_path.write_bytes(b64decode(run["run_strip_png_base64"]))
            proposal = StructuralUnicodeRowAdapter(beam_width=4).propose(
                {
                    "path": str(row_path),
                    "source_sha256": run["run_strip_png_sha256"],
                    "geometry_hash": hypothesis["input_hash"],
                    "components_hash": hypothesis["components_hash"],
                    "run_id": run["run_id"],
                },
                {
                    "mode": "fixed_lattice",
                    "mixed_width_display": hypothesis["mixed_width_display"],
                    "run_mask": {
                        "authority": "geometry_hypothesis_run",
                        "grapheme_complete": True,
                        "pixels": run["binary_run_mask"],
                    },
                },
                {},
                lock,
            )
            outputs[row_index] = tuple(candidate.text for candidate in proposal.proposals[0].candidates)
            assert proposal.proposals[0].proposal_id.endswith("-run-lattice")
            assert all(
                candidate.input_hashes["proposal_mode"]
                == proposal.proposals[0].candidates[0].input_hashes["proposal_mode"]
                for candidate in proposal.proposals[0].candidates
            )
    assert "| _ _|" in {text.strip() for text in outputs[2]}
    assert any("ミ＿xノ" in text for text in outputs[3])


def test_structural_unicode_adapter_refuses_shaped_runs_without_text_basis() -> None:
    adapter = StructuralUnicodeRowAdapter()
    lock = build_environment_lock(script_packs=("ascii", "japanese", "cjk"))
    source = {
        "path": __file__,
        "source_sha256": "1" * 64,
        "geometry_hash": "2" * 64,
        "components_hash": "3" * 64,
        "run_color_stats": {"pixel_count": 100, "strongly_colored_pixels": 0},
    }
    geometry = {
        "mode": "shaped_runs",
        "run_mask": {
            "authority": "geometry_proven_run",
            "pixels": [["1"] * 80 for _ in range(12)],
            "anchor_evidence": {"base_advance_px": 1.0, "origin_px": 0.0},
        },
    }

    proposal = adapter.propose(source, geometry, {}, lock)

    assert proposal.status == "rejected"
    assert "structural_display_basis_unresolved" in proposal.rejection_codes


def test_run_level_span_lattice_preserves_source_supported_kana_diagonal_family() -> None:
    """A lower-ranked kana diagonal survives complete-run span decoding."""

    import numpy as np
    from lateletter.transcription.geometry import build_recognition_hypothesis_inputs, route_raster_geometry
    from lateletter.transcription.recognition import _run_level_variants, _structural_font_path

    source_path = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
    bundle, _ = route_raster_geometry(source_path)
    hypothesis = next(
        item
        for item in build_recognition_hypothesis_inputs(source_path, bundle, max_hypotheses=16)
        if item["provenance"]["hypothesis"]["pitch"] == 23
        and item["provenance"]["hypothesis"]["phase"] == 8
    )
    run = hypothesis["runs"][3]
    raster = np.asarray([[char == "1" for char in row] for row in run["binary_run_mask"]], dtype=bool)
    anchor = run["anchor_evidence"]
    variants = _run_level_variants(
        raster,
        base_advance=13.65,
        origin=float(anchor["origin_px"]),
        font_path=_structural_font_path(),
        unicode_enabled=True,
        max_variants=512,
    )
    assert any("ミ＿xノ" in text for text, _cost in variants)


def test_joint_alignment_keeps_logical_width_and_geometry_margin_separate() -> None:
    from lateletter.transcription import jointly_score_geometry_hypotheses

    hypotheses = [
        {
            "provenance": {"hypothesis": {"pitch": 23, "phase": 8, "ownership": {"owned_pixel_count": 1, "substantive_pixel_count": 1, "unowned_pixel_count": 0, "multiply_owned_pixel_count": 0}}},
            "mixed_width_display": {"base_advance_px": 10.0},
            "runs": [{"row_index": 0, "source_bounds": [0, 0, 30, 10]}],
        },
        {
            "provenance": {"hypothesis": {"pitch": 23, "phase": 9, "ownership": {"owned_pixel_count": 1, "substantive_pixel_count": 1, "unowned_pixel_count": 0, "multiply_owned_pixel_count": 0}}},
            "mixed_width_display": {"base_advance_px": 10.0},
            "runs": [{"row_index": 0, "source_bounds": [0, 0, 30, 10]}],
        },
    ]
    report = jointly_score_geometry_hypotheses(
        hypotheses,
        {"23:8": {0: ("abc",)}, "23:9": {0: ("xyz",)}},
    )
    assert report["status"] in {"accepted_diagnostic", "unresolved"}
    assert report["candidate_txt"] is None
    assert all(item["status"] == "aligned" for item in report["hypotheses"])
    assert report["margin"] >= 0


def test_joint_alignment_uses_content_cropped_strip_width() -> None:
    from lateletter.transcription.recognition import align_logical_text_to_run

    aligned = align_logical_text_to_run(
        "ab",
        {
            "source_bounds": [30, 0, 180, 10],
            "binary_run_mask": ["1" * 20],
        },
        {"mixed_width_display": {"base_advance_px": 10.0, "origin_px": 0.0}},
    )
    assert aligned["status"] == "aligned"
    assert aligned["target_units"] == 2
    assert aligned["alignment_width_px"] == 20.0

    row_trimmed = align_logical_text_to_run(
        "         ___",
        {
            "source_bounds": [30, 0, 180, 10],
            "run_strip_width_px": 150,
            "logical_start_column": 0,
            "logical_end_column": 12,
            "binary_run_mask": ["0" * 150],
        },
        {"mixed_width_display": {"base_advance_px": 10.0, "origin_px": -10.0}},
    )
    assert row_trimmed["status"] == "aligned"
    assert row_trimmed["target_units"] == 12
    assert row_trimmed["alignment_width_px"] == 150.0


def test_run_proposals_are_composed_by_measured_row_order() -> None:
    from lateletter.transcription.recognition import _compose_run_texts

    composed = _compose_run_texts(
        [(0, ("A", "X")), (0, ("B",)), (1, ("C",))],
        top_k=8,
    )
    assert composed[0] == "AB\nC"
    assert "XB\nC" in composed

    spaced = _compose_run_texts(
        [
            (0, ("👩\u200d🌾",), [18, 18, 141, 136]),
            (0, ("❤️",), [161, 18, 282, 136]),
        ],
        top_k=4,
    )
    assert spaced[0] == "👩\u200d🌾 ❤️"


def test_v2_emoji_atlas_uses_source_rgba_and_measured_run_gap_without_truth_input() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    cache = Path(__file__).parents[2] / "tracked/LateLetterResearch/transcription-model-cache"
    if not (cache / "emoji/NotoColorEmoji.ttf").exists() or not (cache / "emoji/emoji-test.txt").exists():
        pytest.skip("project-local emoji atlas data is not available")

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-emoji-zwj")
    atlas = EmojiAtlasAdapter.from_cache(cache / "emoji")
    adapter = EmojiAtlasAdapter(
        sequence_data_path=atlas.sequence_data_path,
        font_path=atlas.font_path,
        font_hashes=atlas.font_hashes,
        max_sequences=10000,
    )
    model_paths = {
        "noto_color_emoji": str(cache / "emoji/NotoColorEmoji.ttf"),
        "unicode_emoji_test": str(cache / "emoji/emoji-test.txt"),
    }
    report = benchmark_offline_ensemble(
        [fixture],
        (adapter,),
        build_environment_lock(
            model_paths=model_paths,
            preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        ),
        root=fixture_root,
        adapter_budgets_seconds={"emoji-grapheme-atlas": 30.0},
        deterministic_replay=True,
        top_k=5,
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["nondeterministic_adapters"] == []
    assert report["positive_missing"] == []
    row = report["coverage_rank_matrix"][0]["rows"][0]
    assert row["expected_logical_sequence"] == "👩\u200d🌾 ❤️"
    assert row["classification"] == "present_and_winning"
    assert row["proposal_rank"] == 1


def test_v2_mixed_script_fuses_profile_proposals_without_truth_input() -> None:
    assert _latin_cjk_ocr_variants("4A 漢")[0] == "A漢"
    assert _arabic_ocr_variants("سلاء تنم")[0] == "سلام"

    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    cache = Path(__file__).parents[2] / "tracked/LateLetterResearch/transcription-model-cache/tesseract_best"
    if not (cache / "ara.traineddata").exists() or not (cache / "jpn.traineddata").exists() or not (cache / "chi_sim.traineddata").exists():
        pytest.skip("project-local Arabic/Japanese/CJK Tesseract data is not available")

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-mixed-script")
    model_paths = {path.stem: str(path) for path in cache.glob("*.traineddata")}
    report = benchmark_offline_ensemble(
        [fixture],
        (TesseractOfflineAdapter(cache_dir=str(cache), languages=("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra")),),
        build_environment_lock(
            model_paths=model_paths,
            script_packs=tuple(sorted(model_paths)),
            preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        ),
        root=fixture_root,
        adapter_budgets_seconds={"tesseract-offline": 12.0},
        deterministic_replay=True,
        top_k=5,
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["nondeterministic_adapters"] == []
    assert report["positive_missing"] == []
    row = report["coverage_rank_matrix"][0]["rows"][0]
    assert row["expected_logical_sequence"] == "A漢 سلام"
    assert row["classification"] == "present_and_winning"
    assert row["proposal_rank"] == 1
    assert row["proposed_by"] == ["tesseract-profile-fusion"]


def test_v2_degraded_fixed_structural_adapter_recovers_horizontal_runs_and_indent() -> None:
    from lateletter.transcription.geometry import build_recognition_inputs, route_raster_geometry
    from lateletter.transcription.recognition import _mask_from_pixels

    fixture_root = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
    source_path = fixture_root / "positive/positive-degraded-fixed/source.png"
    geometry_bundle, decision = route_raster_geometry(source_path)
    assert decision.status == "proved"
    inputs = build_recognition_inputs(source_path, geometry_bundle, mode=decision.mode)
    row1 = next(run for run in inputs["runs"] if run["row_index"] == 1)
    assert _degraded_horizontal_sequence_from_run_mask(_mask_from_pixels(row1["binary_run_mask"])) == "--__"

    corpus = json.loads((fixture_root / "corpus-v2.json").read_text())
    fixture = next(item for item in corpus["fixtures"] if item["id"] == "positive-degraded-fixed")
    report = benchmark_offline_ensemble(
        [fixture],
        (FixedLatticeStructuralAdapter(),),
        build_environment_lock(script_packs=("ascii",)),
        root=fixture_root,
        adapter_budgets_seconds={"fixed-lattice-structural": 5.0},
        deterministic_replay=True,
        top_k=5,
    )
    assert report["ground_truth_passed_to_adapters"] is False
    assert report["budget_failures"] == []
    assert report["positive_missing"] == []
    assert report["results"][0]["exact_nfc_target_in_top_k"] is True
    rows = report["coverage_rank_matrix"][0]["rows"]
    assert [(row["expected_logical_sequence"], row["classification"], row["proposal_rank"]) for row in rows] == [
        ("  /\\", "present_and_winning", 1),
        ("--__", "present_and_winning", 1),
    ]


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
