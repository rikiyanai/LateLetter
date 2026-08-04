"""Pinned offline recognizer seam and fail-closed adapter inventory."""

from __future__ import annotations

import hashlib
import base64
import itertools
import json
import math
import os
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Protocol

import PIL
import numpy as np
import regex
import wcwidth
from PIL import Image, ImageDraw, ImageFont

from .hashing import is_sha256, safe_relative_path, sha256_bytes, sha256_file
from .model import GraphemeCandidate, RecognitionProposal
from .schema import canonical_bytes


# ProposalSets are frozen evidence records.  Reusing one for an identical
# hash-bound input is safe and keeps deterministic replay from rebuilding the
# same expensive raster topology surface.  The cache is deliberately bounded
# and keyed by every input that can affect recognition.
# Expensive proposal adapters are pure functions of their hash-bound inputs.
# Reusing an identical result makes the in-process determinism replay cheap;
# the release harness still replays the whole process separately when it
# checks cross-process byte identity.
_PROPOSAL_CACHE: dict[tuple[str, ...], "ProposalSet"] = {}
_PROPOSAL_CACHE_LIMIT = 512


class RecognizerError(ValueError):
    """Raised when a recognizer cannot produce a deterministic proposal."""


@dataclass(frozen=True)
class CapabilityProfile:
    """Version-pinned, machine-readable limits of one proposal adapter.

    A profile is deliberately separate from ``Recognizer``.  The adapter may
    be installed but still not support a script, direction, or grapheme family
    required by a fixture.  Those cases must be reported as unsupported rather
    than silently guessed.
    """

    adapter: str
    adapter_version: str
    supported_scripts: tuple[str, ...] = ()
    supported_directions: tuple[str, ...] = ("ltr",)
    grapheme_coverage: tuple[str, ...] = ()
    emoji_coverage: tuple[str, ...] = ()
    model_hashes: Mapping[str, str] = field(default_factory=dict)
    runtime_hashes: Mapping[str, str] = field(default_factory=dict)
    runtime_versions: Mapping[str, str] = field(default_factory=dict)
    license: str = ""
    offline: bool = True
    runtime_network: bool = False
    tested_fixture_families: tuple[str, ...] = ()
    unsupported_cases: tuple[str, ...] = ()
    status: str = "available"
    output_hash: str = ""

    def __post_init__(self) -> None:
        if not self.adapter or not self.adapter_version:
            raise ValueError("capability profile needs adapter and version")
        if not self.license:
            raise ValueError("capability profile needs a license")
        for name, value in self.model_hashes.items():
            if not is_sha256(value):
                raise ValueError(f"model hash is not SHA-256: {name}")
        for name, value in self.runtime_hashes.items():
            if not is_sha256(value):
                raise ValueError(f"runtime hash is not SHA-256: {name}")
        object.__setattr__(self, "supported_scripts", tuple(sorted(set(self.supported_scripts))))
        object.__setattr__(self, "supported_directions", tuple(sorted(set(self.supported_directions))))
        object.__setattr__(self, "grapheme_coverage", tuple(sorted(set(self.grapheme_coverage))))
        object.__setattr__(self, "emoji_coverage", tuple(sorted(set(self.emoji_coverage))))
        object.__setattr__(self, "tested_fixture_families", tuple(sorted(set(self.tested_fixture_families))))
        object.__setattr__(self, "unsupported_cases", tuple(sorted(set(self.unsupported_cases))))
        payload = self.to_dict(include_output_hash=False)
        digest = sha256_bytes(canonical_bytes(payload))
        if self.output_hash and self.output_hash != digest:
            raise ValueError("capability profile output hash mismatch")
        object.__setattr__(self, "output_hash", digest)

    def to_dict(self, *, include_output_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "supported_scripts": list(self.supported_scripts),
            "supported_directions": list(self.supported_directions),
            "grapheme_coverage": list(self.grapheme_coverage),
            "emoji_coverage": list(self.emoji_coverage),
            "model_hashes": dict(self.model_hashes),
            "runtime_hashes": dict(self.runtime_hashes),
            "runtime_versions": dict(self.runtime_versions),
            "license": self.license,
            "offline": self.offline,
            "runtime_network": self.runtime_network,
            "tested_fixture_families": list(self.tested_fixture_families),
            "unsupported_cases": list(self.unsupported_cases),
            "status": self.status,
        }
        if include_output_hash:
            payload["output_hash"] = self.output_hash
        return payload


@dataclass(frozen=True)
class ModelArtifact:
    """A cache entry whose bytes are independently hash-bound."""

    artifact_id: str
    source_url: str
    cache_path: str
    sha256: str
    license: str
    size_bytes: int = 0
    status: str = "missing"

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.source_url or not self.cache_path:
            raise ValueError("model artifact identity, URL, and cache path are required")
        safe_relative_path(self.cache_path, field="cache_path")
        if not is_sha256(self.sha256):
            raise ValueError("model artifact sha256 must be lowercase SHA-256")
        if self.size_bytes < 0:
            raise ValueError("model artifact size cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "source_url": self.source_url,
            "cache_path": self.cache_path,
            "sha256": self.sha256,
            "license": self.license,
            "size_bytes": self.size_bytes,
            "status": self.status,
        }


def verify_model_cache(cache_root: str | os.PathLike[str], artifacts: tuple[ModelArtifact, ...]) -> dict[str, Any]:
    """Verify project-local model bytes without downloading or network access."""

    root = Path(cache_root).resolve()
    results: list[dict[str, Any]] = []
    for artifact in artifacts:
        target = (root / artifact.cache_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RecognizerError(f"model cache path escapes cache root: {artifact.cache_path}") from exc
        if not target.exists():
            results.append({**artifact.to_dict(), "status": "missing"})
            continue
        actual = sha256_file(target)
        status = "verified" if actual == artifact.sha256 else "stale_hash"
        results.append({**artifact.to_dict(), "status": status, "actual_sha256": actual})
    return {
        "cache_root": str(root),
        "offline": True,
        "artifacts": results,
        "all_verified": bool(results) and all(item["status"] == "verified" for item in results),
    }


@dataclass(frozen=True)
class EnvironmentLock:
    unicode_database: str
    uax29: str
    wcwidth_version: str
    pillow_version: str
    harfbuzz: str = "not-installed"
    freetype: str = "not-recorded"
    model_hashes: Mapping[str, str] = field(default_factory=dict)
    script_packs: tuple[str, ...] = ()
    preprocessing: Mapping[str, Any] = field(default_factory=dict)
    capability_profiles: tuple[CapabilityProfile, ...] = ()
    output_hash: str = ""

    def __post_init__(self) -> None:
        for key, value in self.model_hashes.items():
            if not is_sha256(value):
                raise ValueError(f"model hash is not SHA-256: {key}")
        object.__setattr__(
            self,
            "capability_profiles",
            tuple(
                profile if isinstance(profile, CapabilityProfile) else CapabilityProfile(**profile)
                for profile in self.capability_profiles
            ),
        )
        payload = self.to_dict(include_output_hash=False)
        digest = sha256_bytes(canonical_bytes(payload))
        if self.output_hash and self.output_hash != digest:
            raise ValueError("environment lock output hash mismatch")
        object.__setattr__(self, "output_hash", digest)

    def to_dict(self, *, include_output_hash: bool = True) -> dict[str, Any]:
        payload = {
            "unicode_database": self.unicode_database,
            "uax29": self.uax29,
            "wcwidth_version": self.wcwidth_version,
            "pillow_version": self.pillow_version,
            "harfbuzz": self.harfbuzz,
            "freetype": self.freetype,
            "model_hashes": dict(self.model_hashes),
            "script_packs": list(self.script_packs),
            "preprocessing": dict(self.preprocessing),
            "capability_profiles": [profile.to_dict() for profile in self.capability_profiles],
        }
        if include_output_hash:
            payload["output_hash"] = self.output_hash
        return payload


@dataclass(frozen=True)
class ProposalSet:
    adapter: str
    adapter_version: str
    environment_lock_hash: str
    proposals: tuple[RecognitionProposal, ...] = ()
    supported_scripts: tuple[str, ...] = ()
    status: str = "rejected"
    rejection_codes: tuple[str, ...] = ()
    output_hash: str = ""

    def __post_init__(self) -> None:
        if not is_sha256(self.environment_lock_hash):
            raise ValueError("proposal set needs an environment lock hash")
        payload = self.to_dict(include_output_hash=False)
        digest = sha256_bytes(canonical_bytes(payload))
        if self.output_hash and self.output_hash != digest:
            raise ValueError("proposal set output hash mismatch")
        object.__setattr__(self, "output_hash", digest)

    def to_dict(self, *, include_output_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "environment_lock_hash": self.environment_lock_hash,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "supported_scripts": list(self.supported_scripts),
            "status": self.status,
            "rejection_codes": list(self.rejection_codes),
        }
        if include_output_hash:
            payload["output_hash"] = self.output_hash
        return payload


class Recognizer(Protocol):
    name: str
    version: str
    supported_scripts: tuple[str, ...]

    def propose(
        self,
        source: Mapping[str, Any],
        geometry: Mapping[str, Any],
        components: Mapping[str, Any],
        environment_lock: EnvironmentLock,
    ) -> ProposalSet: ...


def build_environment_lock(
    *,
    model_paths: Mapping[str, str | os.PathLike[str]] | None = None,
    script_packs: tuple[str, ...] = (),
    preprocessing: Mapping[str, Any] | None = None,
    capability_profiles: tuple[CapabilityProfile, ...] = (),
) -> EnvironmentLock:
    model_hashes = {name: sha256_file(path) for name, path in (model_paths or {}).items()}
    return EnvironmentLock(
        unicode_database=unicodedata.unidata_version,
        uax29=f"regex/{regex.__version__}",
        wcwidth_version=getattr(wcwidth, "__version__", "unknown"),
        pillow_version=PIL.__version__,
        model_hashes=model_hashes,
        script_packs=script_packs,
        preprocessing=dict(preprocessing or {}),
        capability_profiles=capability_profiles,
    )


def _hash_for_source(source: Mapping[str, Any], key: str, fallback: str) -> str:
    value = str(source.get(key, ""))
    return value if is_sha256(value) else fallback


def _source_hashes(source: Mapping[str, Any]) -> tuple[str, str, str]:
    path = source.get("path")
    fallback = "0" * 64
    if path and Path(str(path)).exists():
        fallback = sha256_file(str(path))
    return (
        _hash_for_source(source, "source_sha256", fallback),
        _hash_for_source(source, "geometry_hash", fallback),
        _hash_for_source(source, "components_hash", fallback),
    )


def _candidate(
    *,
    text: str,
    source_hash: str,
    geometry_hash: str,
    components_hash: str,
    environment_hash: str,
    confidence: float = 0.0,
    rejection_reasons: tuple[str, ...] = (),
    run_id: str | None = None,
    component_ids: tuple[str, ...] | list[str] = (),
    alternatives: tuple[str, ...] = (),
    extra_input_hashes: Mapping[str, str] | None = None,
) -> GraphemeCandidate:
    normalized = unicodedata.normalize("NFC", text)
    return GraphemeCandidate(
        text=text,
        normalized_text=normalized,
        codepoints=tuple(f"U+{ord(char):04X}" for char in normalized),
        display_width=wcwidth.wcswidth(normalized),
        confidence=confidence,
        component_ids=tuple(sorted({str(value) for value in component_ids if str(value)})),
        input_hashes={
            "source": source_hash,
            "geometry": geometry_hash,
            "components": components_hash,
            "environment": environment_hash,
            **dict(extra_input_hashes or {}),
        },
        alternatives=alternatives,
        rejection_reasons=rejection_reasons,
    )


def _unsupported_proposal(adapter: str, version: str, source: Mapping[str, Any], lock: EnvironmentLock, reason: str) -> ProposalSet:
    source_hash, geometry_hash, components_hash = _source_hashes(source)
    candidate = _candidate(
        text="?",
        source_hash=source_hash,
        geometry_hash=geometry_hash,
        components_hash=components_hash,
        environment_hash=lock.output_hash,
        rejection_reasons=(reason,),
    )
    proposal = RecognitionProposal(
        proposal_id=f"{adapter}-unsupported",
        adapter=adapter,
        adapter_version=version,
        model_hashes=lock.model_hashes,
        candidates=(candidate,),
        input_hashes={"source": source_hash, "geometry": geometry_hash, "components": components_hash, "environment": lock.output_hash},
        status="rejected",
        rejection_reasons=(reason,),
    )
    return ProposalSet(
        adapter=adapter,
        adapter_version=version,
        environment_lock_hash=lock.output_hash,
        proposals=(proposal,),
        status="rejected",
        rejection_codes=(reason,),
    )


@dataclass(frozen=True)
class TesseractOfflineAdapter:
    """Tesseract proposal source using only the project-local tessdata cache."""

    name: str = "tesseract-offline"
    version: str = "5.5.1"
    languages: tuple[str, ...] = ("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra", "osd")
    supported_scripts: tuple[str, ...] = ("ascii", "latin", "arabic", "japanese", "cjk", "digits")
    cache_dir: str | None = None
    executable: str | None = None

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        executable = self.executable or shutil.which("tesseract")
        available_packs = set(environment_lock.script_packs)
        installed = tuple(language for language in self.languages if language in available_packs)
        status = "available" if executable and installed else "unavailable"
        language_scripts = {
            "eng": {"ascii", "latin", "digits"},
            "ara": {"arabic"},
            "jpn": {"japanese"},
            "jpn_vert": {"japanese", "vertical_text"},
            "chi_sim": {"cjk"},
            "chi_tra": {"cjk"},
        }
        scripts = set().union(*(language_scripts.get(language, set()) for language in installed))
        return CapabilityProfile(
            adapter=self.name,
            adapter_version=self.version,
            supported_scripts=tuple(sorted(scripts)) if installed else (),
            supported_directions=("ltr", "rtl"),
            grapheme_coverage=("extended-grapheme-candidate",),
            model_hashes={key: value for key, value in environment_lock.model_hashes.items() if key in installed},
            runtime_hashes={"tesseract_binary": sha256_file(executable)} if executable else {},
            runtime_versions={"tesseract": self.version, "python": sys.version.split()[0]},
            license="Apache-2.0",
            offline=True,
            runtime_network=False,
            tested_fixture_families=("ascii", "latin", "arabic", "japanese", "cjk"),
            unsupported_cases=("emoji_zwj", "visual_unicode_collision", "joined_text_art_runs"),
            status=status,
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        if not source.get("path") or not Path(str(source["path"])).exists():
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "source_missing")
        executable = self.executable or shutil.which("tesseract")
        if not executable:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "recognizer_unavailable")
        tessdata_dir = Path(self.cache_dir or os.environ.get("LATELETTER_TRANSCRIPTION_MODEL_CACHE", ""))
        if not tessdata_dir.exists():
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "model_cache_missing")
        requested_hint = source.get("tesseract_languages")
        if isinstance(requested_hint, (list, tuple)) and requested_hint:
            requested = [
                str(language)
                for language in requested_hint
                if str(language) in self.languages and (tessdata_dir / f"{language}.traineddata").exists()
            ]
        else:
            requested = [language for language in self.languages if (tessdata_dir / f"{language}.traineddata").exists()]
        if not requested:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "recognizer_unsupported")
        source_hash, geometry_hash, components_hash = _source_hashes(source)
        command = [
            executable,
            str(source["path"]),
            "stdout",
            "--tessdata-dir",
            str(tessdata_dir),
            "--psm",
            str(source.get("tesseract_psm", 6)),
            "-l",
            "+".join(requested),
        ]
        timeout_seconds = float(source.get("tesseract_timeout_seconds", 30.0))
        if timeout_seconds <= 0:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "recognizer_timeout_invalid")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env={**os.environ, "TESSDATA_PREFIX": str(tessdata_dir)},
            )
        except subprocess.TimeoutExpired:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "recognizer_timeout")
        except (OSError, subprocess.SubprocessError) as exc:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, f"recognizer_execution:{type(exc).__name__}")
        if completed.returncode != 0:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "recognizer_execution_failed")
        text = completed.stdout.rstrip("\n")
        if not text:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "empty_proposal")
        alternatives = tuple(item for item in _ocr_latin_confusable_variants(text) if item != unicodedata.normalize("NFC", text))
        candidate = _candidate(
            text=text,
            source_hash=source_hash,
            geometry_hash=geometry_hash,
            components_hash=components_hash,
            environment_hash=environment_lock.output_hash,
            confidence=0.25,
            component_ids=tuple(str(value) for value in source.get("component_ids", ())),
            alternatives=alternatives,
        )
        proposal = RecognitionProposal(
            proposal_id=f"{self.name}-run",
            adapter=self.name,
            adapter_version=self.version,
            model_hashes=environment_lock.model_hashes,
            candidates=(candidate,),
            run_id=str(source.get("run_id", "row-0")),
            input_hashes={"source": source_hash, "geometry": geometry_hash, "components": components_hash, "environment": environment_lock.output_hash},
            status="proposal",
        )
        return ProposalSet(
            adapter=self.name,
            adapter_version=self.version,
            environment_lock_hash=environment_lock.output_hash,
            proposals=(proposal,),
            supported_scripts=self.supported_scripts,
            status="proposal_only",
        )


def _ocr_latin_confusable_variants(text: str, *, limit: int = 64) -> tuple[str, ...]:
    """Return bounded OCR alternatives for Latin vertical-bar confusions.

    OCR commonly reads capital/lowercase L or I as ``|`` in rendered text art
    and sometimes inserts a space after that bar.  This is proposal coverage
    only: the original OCR text remains present, and final acceptance still
    requires source evidence, collision checks, and ranking gates.
    """

    normalized = unicodedata.normalize("NFC", text)
    completed: list[tuple[float, str]] = []
    stack: list[tuple[int, str, float]] = [(0, "", 0.0)]
    while stack and len(completed) < limit:
        index, prefix, cost = stack.pop()
        if index >= len(normalized):
            completed.append((cost, unicodedata.normalize("NFC", prefix)))
            continue
        char = normalized[index]
        if char == "|":
            at_word_start = index == 0 or normalized[index - 1].isspace()
            replacements = (
                (("L", 0.0), ("l", 0.20), ("I", 0.45), ("|", 1.0))
                if at_word_start
                else (("l", 0.0), ("L", 0.20), ("I", 0.45), ("|", 1.0))
            )
            next_is_spurious_gap = (
                index + 2 < len(normalized)
                and normalized[index + 1] == " "
                and normalized[index + 2].islower()
            )
            options: list[tuple[float, int, str]] = []
            for replacement, replacement_cost in replacements:
                options.append((replacement_cost + (0.35 if next_is_spurious_gap else 0.0), index + 1, prefix + replacement))
                if next_is_spurious_gap and replacement != "|":
                    options.append((replacement_cost - 0.10, index + 2, prefix + replacement))
            for option_cost, next_index, next_prefix in sorted(options, reverse=True):
                stack.append((next_index, next_prefix, cost + option_cost))
        else:
            stack.append((index + 1, prefix + char, cost))
    return tuple(dict.fromkeys(text for _cost, text in sorted(completed, key=lambda item: (item[0], item[1]))))[:limit]


@dataclass(frozen=True)
class FixedLatticeStructuralAdapter:
    name: str = "fixed-lattice-structural"
    version: str = "2-run-mask-ascii-components"
    supported_scripts: tuple[str, ...] = ("ascii", "digits")

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        return CapabilityProfile(
            adapter=self.name,
            adapter_version=self.version,
            supported_scripts=self.supported_scripts,
            supported_directions=("ltr",),
            grapheme_coverage=("ascii-structural",),
            license="CC0-1.0",
            tested_fixture_families=("fixed_lattice_ascii",),
            unsupported_cases=("proportional_runs", "unicode_scripts", "emoji_zwj", "ambiguous_spill"),
            status="proposal_only",
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        geometry_mask = _run_mask(geometry)
        source_mask = _source_ink_mask_from_path(source)
        mask = source_mask if source_mask is not None else (np.asarray(geometry_mask, dtype=bool) if geometry_mask is not None else None)
        if mask is None:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "structural_row_input_unavailable")
        # The geometry owner may expose a fixed source as shaped run strips
        # when the public routing decision is still unsettled.  This adapter
        # does not select geometry; it only consumes a source-owned complete
        # run mask and emits ASCII structural proposals for that run.
        text = _ascii_structural_text_from_run_mask(np.asarray(mask, dtype=bool))
        if text is None:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "ascii_structural_run_unresolved")
        source_hash, geometry_hash, components_hash = _source_hashes(source)
        evidence = geometry.get("run_mask") if isinstance(geometry.get("run_mask"), Mapping) else {}
        run_hash = str(evidence.get("mask_sha256", ""))
        if not is_sha256(run_hash):
            run_hash = sha256_bytes(canonical_bytes({"pixels": evidence.get("pixels") if isinstance(evidence, Mapping) else mask}))
        component_ids = tuple(
            str(value)
            for value in (
                evidence.get("component_ids", ())
                if isinstance(evidence, Mapping)
                else source.get("component_ids", ())
            )
        )
        candidate = _candidate(
            text=text,
            source_hash=source_hash,
            geometry_hash=geometry_hash,
            components_hash=components_hash,
            environment_hash=environment_lock.output_hash,
            confidence=0.72,
            run_id=str(source.get("run_id", evidence.get("run_id", "run-0") if isinstance(evidence, Mapping) else "run-0")),
            component_ids=component_ids,
            extra_input_hashes={"run_mask": run_hash},
        )
        proposal = RecognitionProposal(
            proposal_id=f"{self.name}-run",
            adapter=self.name,
            adapter_version=self.version,
            model_hashes=environment_lock.model_hashes,
            candidates=(candidate,),
            run_id=str(source.get("run_id", evidence.get("run_id", "run-0") if isinstance(evidence, Mapping) else "run-0")),
            input_hashes={
                "source": source_hash,
                "geometry": geometry_hash,
                "components": components_hash,
                "environment": environment_lock.output_hash,
                "run_mask": run_hash,
            },
            configuration={"recognizer": "source-mask-ascii-structural", "glyph_authority": "proposal_only"},
            provenance={
                "source_only": True,
                "ground_truth_input": False,
                "geometry_authority": evidence.get("authority") if isinstance(evidence, Mapping) else None,
                "component_ids": list(component_ids),
            },
            status="proposal",
        )
        return ProposalSet(
            adapter=self.name,
            adapter_version=self.version,
            environment_lock_hash=environment_lock.output_hash,
            proposals=(proposal,),
            supported_scripts=self.supported_scripts,
            status="proposal_only",
        )


def _ascii_run_components(mask: np.ndarray) -> tuple[dict[str, Any], ...]:
    """Return stable 8-connected component crops for one source-owned run mask."""

    if mask.ndim != 2 or not mask.any():
        return ()
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or seen[y, x]:
                continue
            stack = [(int(y), int(x))]
            seen[y, x] = True
            pixels: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                pixels.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if not dx and not dy:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            ys = np.asarray([item[0] for item in pixels], dtype=int)
            xs = np.asarray([item[1] for item in pixels], dtype=int)
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            crop = mask[y0:y1, x0:x1]
            components.append(
                {
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1,
                    "crop": crop,
                    "area": int(crop.sum()),
                }
            )
    components.sort(key=lambda item: (int(item["x0"]), int(item["y0"]), int(item["x1"]), int(item["y1"])))
    return tuple(components)


def _source_ink_mask_from_path(source: Mapping[str, Any]) -> np.ndarray | None:
    """Recover actual foreground ink from a geometry-owned run-strip PNG."""

    path_value = source.get("path")
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.exists():
        return None
    try:
        image = Image.open(path).convert("RGBA")
    except OSError:
        return None
    pixels = np.asarray(image, dtype=np.uint8)
    alpha = pixels[:, :, 3]
    rgb = pixels[:, :, :3].astype(np.int16)
    if alpha.max(initial=0) == 0:
        return None
    luminance = (
        0.299 * rgb[:, :, 0]
        + 0.587 * rgb[:, :, 1]
        + 0.114 * rgb[:, :, 2]
    )
    opaque = alpha > 8
    if not opaque.any():
        return None
    # Most corpus run strips are dark ink on light background; retain a
    # contrast fallback for inverted or non-white captures without requiring
    # fixture metadata.
    opaque_luma = luminance[opaque]
    low = float(np.percentile(opaque_luma, 10))
    high = float(np.percentile(opaque_luma, 90))
    if high - low < 10.0:
        return None
    dark_ink = opaque & (luminance <= low + (high - low) * 0.35)
    light_ink = opaque & (luminance >= high - (high - low) * 0.35)
    dark_count = int(dark_ink.sum())
    light_count = int(light_ink.sum())
    if dark_count and light_count:
        mask = dark_ink if dark_count <= light_count else light_ink
    else:
        mask = dark_ink if dark_count else light_ink
    return np.asarray(mask, dtype=bool) if mask.any() else None


def _ascii_component_shape(component: Mapping[str, Any], *, run_height: int) -> str | None:
    """Classify one structural ASCII component from source morphology only."""

    crop = np.asarray(component.get("crop"), dtype=bool)
    ys, xs = np.where(crop)
    if not len(xs):
        return None
    height, width = crop.shape
    bbox_width = int(xs.max() - xs.min() + 1)
    bbox_height = int(ys.max() - ys.min() + 1)
    area = int(len(xs))
    y_center = float(int(component.get("y0", 0)) + ys.mean()) / max(1.0, float(run_height - 1))
    horizontal_band = float(np.max(crop.sum(axis=1))) / max(1, bbox_width)
    vertical_band = float(np.max(crop.sum(axis=0))) / max(1, bbox_height)
    if (
        bbox_width >= max(4, bbox_height * 2)
        and bbox_height <= max(4, int(run_height * 0.28))
        and horizontal_band >= 0.45
    ):
        return "_" if y_center >= 0.62 else "-"
    if bbox_width >= 3 and bbox_height >= max(5, int(run_height * 0.40)):
        thirds: list[float] = []
        for start, stop in ((0.0, 0.34), (0.33, 0.67), (0.66, 1.01)):
            lo = int(np.floor(start * max(1, height - 1)))
            hi = max(lo + 1, int(np.ceil(stop * height)))
            cols = np.where(crop[lo:hi, :].any(axis=0))[0]
            if len(cols):
                thirds.append(float(cols.mean()))
        if len(thirds) == 3:
            outer = (thirds[0] + thirds[2]) / 2.0
            if abs(outer - thirds[1]) >= max(0.75, width * 0.12):
                return "(" if thirds[1] < outer else ")"
    if (
        bbox_height >= max(5, int(run_height * 0.55))
        and bbox_width <= max(5, int(bbox_height * 0.45))
        and vertical_band >= 0.45
    ):
        return "|"
    if bbox_width >= 3 and bbox_height >= max(5, int(run_height * 0.40)):
        y_values = ys.astype(float)
        x_values = xs.astype(float)
        if float(np.var(y_values)) > 0.0:
            centred_y = y_values - float(np.mean(y_values))
            centred_x = x_values - float(np.mean(x_values))
            slope = float(np.mean(centred_y * centred_x) / max(float(np.mean(centred_y * centred_y)), 1e-9))
            if abs(slope) >= 0.18:
                return "\\" if slope > 0 else "/"
    if area <= max(6, int(run_height * 0.20)):
        return "."
    return None


def _ascii_structural_text_from_run_mask(mask: np.ndarray) -> str | None:
    """Emit one bounded ASCII structural proposal from a complete run mask."""

    components = list(_ascii_run_components(mask))
    if not components:
        return ""
    # Group two or more stacked horizontal components with overlapping x-range
    # as an equals sign.  The source still owns the components; this only
    # emits proposal text for the measured run.
    if len(components) >= 2:
        shapes = [_ascii_component_shape(item, run_height=mask.shape[0]) for item in components]
        x0 = max(int(item["x0"]) for item in components)
        x1 = min(int(item["x1"]) for item in components)
        if (
            all(shape in {"-", "_"} for shape in shapes)
            and x1 > x0
            and (x1 - x0) / max(1, max(int(item["x1"]) for item in components) - min(int(item["x0"]) for item in components)) >= 0.45
        ):
            return "="
    chars: list[str] = []
    for component in components:
        shape = _ascii_component_shape(component, run_height=mask.shape[0])
        if shape is None:
            return None
        chars.append(shape)
    return "".join(chars)


_STRUCTURAL_GLYPHS: tuple[tuple[str, int], ...] = (
    ("/", 1), ("\\", 1), ("|", 1), ("_", 1), ("-", 1), ("(", 1), (")", 1),
    ("[", 1), ("]", 1), ("<", 1), (">", 1), ("~", 1), ("`", 1), ("'", 1),
    (",", 1), (".", 1), ("=", 1), ("x", 1), ("l", 1), ("│", 1), ("￣", 1),
    ("\u3000", 2),
    ("／", 2), ("＞", 2), ("＿", 2), ("フ", 2), ("ミ", 2), ("ノ", 2),
    ("ヽ", 2), ("丶", 2), ("、", 2),
    ("ﾉ", 1),
)


def _ascii_structural_variant(text: str) -> str:
    """Project visual structural lookalikes into an ASCII-safe proposal.

    This is an alternate representation, not Unicode normalization: the
    source candidate remains intact and the decoder must retain both until a
    width/script profile and ownership gate decide between them.
    """

    replacements = str.maketrans({
        "／": "/",
        "＼": "\\",
        "│": "|",
        "￣": "-",
        "＿": "_",
        "＞": ">",
        "＜": "<",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]",
        "　": "  ",
    })
    return text.translate(replacements)


def _unicode_structural_variant(text: str) -> str:
    """Emit a fullwidth/ideographic spelling as proposal evidence.

    The transform is intentionally conservative: it only runs for a string
    that already contains a non-ASCII grapheme, and it does not normalize the
    original candidate.  A source row can legitimately mix ASCII and Japanese
    forms, so this is an alternative rather than a preference.
    """

    if not any(ord(char) > 0x7F for char in text):
        return text
    replacements = str.maketrans({
        "/": "／",
        "\\": "＼",
        "|": "│",
        "_": "＿",
        "-": "￣",
        ">": "＞",
        "<": "＜",
        "(": "（",
        ")": "）",
        "[": "［",
        "]": "］",
    })
    variant = text.translate(replacements)
    # A pair of ordinary spaces between Japanese/structural tokens is a
    # common one-unit rendering of two ideographic advances.  Preserve the
    # ordinary-space candidate and add this display alternative separately.
    leading = len(variant) - len(variant.lstrip(" "))
    trailing = len(variant) - len(variant.rstrip(" "))
    end = len(variant) - trailing if trailing else len(variant)
    core = variant[leading:end].replace("  ", "　　")
    return (" " * leading) + core + (" " * trailing)


def _mixed_width_variants(text: str) -> tuple[str, ...]:
    """Return bounded spacing/vertical-lookalike proposal alternatives.

    East-Asian text-art often mixes ordinary ASCII punctuation with
    ideographic spaces and a visually identical ``l``/bar.  These are logical
    alternatives, not normalization: leading/trailing ASCII whitespace stays
    byte-identical and every variant remains proposal evidence.
    """

    leading = len(text) - len(text.lstrip(" "))
    trailing = len(text) - len(text.rstrip(" "))
    end = len(text) - trailing if trailing else len(text)
    core = text[leading:end]
    variants: list[str] = []
    if core:
        # Preserve one-space and two-space forms separately; a renderer may
        # paint either one narrow or one wide measured gap.  Build a small
        # product over *internal* gaps rather than applying one global
        # replacement.  Connected/overlapping painted runs can require a
        # wide gap plus an adjacent ordinary space, and that evidence must
        # survive without allowing an unbounded whitespace search.
        converted_one = regex.sub(r"(?<=\S) (?=\S)", "\u3000", core)
        converted_runs = regex.sub(r"(?<=\S) {2,}(?=\S)", lambda match: "\u3000" * len(match.group(0)), core)
        variants.extend((converted_one, converted_runs))
        parts = regex.split(r"([ \u3000]+)", core)
        expansions: list[str] = [""]
        for part in parts:
            if not part:
                continue
            if regex.fullmatch(r"[ \u3000]+", part):
                choices = [part]
                if "\u3000" not in part:
                    wide = "\u3000" * max(1, len(part))
                    choices.extend((wide, wide + " ", " " + wide))
                else:
                    choices.extend((part + " ", " " + part))
                choices = tuple(dict.fromkeys(choices))
            else:
                choices = (part,)
            expanded: list[str] = []
            for prefix in expansions:
                for choice in choices:
                    expanded.append(prefix + choice)
                    if len(expanded) >= 24:
                        break
                if len(expanded) >= 24:
                    break
            expansions = list(dict.fromkeys(expanded))
        variants.extend(expansions)
        for value in tuple(variants):
            if value.endswith(("|", "│")):
                variants.append(value[:-1] + "l")
                variants.append(value[:-1] + " l")
            if value.endswith("l"):
                variants.append(value[:-1] + "|")
                variants.append(value[:-1] + " |")
    return tuple(
        (" " * leading) + value + (" " * trailing)
        for value in dict.fromkeys(variants)
        if value != text
    )


@lru_cache(maxsize=8)
def _structural_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _structural_font_path() -> str | None:
    candidates = (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    return next((path for path in candidates if Path(path).exists()), None)


@lru_cache(maxsize=8)
def _structural_font_hash(path: str) -> str:
    """Hash a pinned template font once per process/path.

    Every proposal candidate references the same immutable font bytes. Reusing
    the digest keeps bounded inference proportional to candidate search rather
    than repeated font-file I/O, while the recorded hash remains identical.
    """

    return sha256_file(path)


def _normalized_shape(mask: np.ndarray, *, width: int = 18, height: int = 20) -> np.ndarray | None:
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    crop = Image.fromarray(
        (mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] * 255).astype(np.uint8),
        mode="L",
    )
    scale = min(width / max(1, crop.width), height / max(1, crop.height))
    resized = crop.resize(
        (
            max(1, min(width, int(round(crop.width * scale)))),
            max(1, min(height, int(round(crop.height * scale)))),
        ),
        Image.Resampling.BILINEAR,
    )
    canvas = Image.new("L", (width, height), 0)
    canvas.paste(
        resized,
        ((width - resized.width) // 2, (height - resized.height) // 2),
    )
    return np.asarray(canvas, dtype=np.uint8) > 80


@lru_cache(maxsize=128)
def _structural_template(font_path: str, glyph: str, units: int, base_advance: int, height: int) -> tuple[tuple[bool, ...], ...] | None:
    try:
        font = _structural_font(font_path, 17)
        bbox = font.getbbox(glyph)
        if bbox is None:
            return None
        width = max(1, int(round(base_advance * units)))
        image = Image.new("L", (max(width, 40), max(height, 32)), 0)
        from PIL import ImageDraw

        ImageDraw.Draw(image).text((4 - bbox[0], 2 - bbox[1]), glyph, font=font, fill=255)
        normalized = _normalized_shape(np.asarray(image, dtype=np.uint8) > 32)
        if normalized is None:
            return None
        return tuple(tuple(bool(value) for value in row) for row in normalized)
    except (OSError, ValueError):
        return None


def _structural_shape_score(source: np.ndarray, template: tuple[tuple[bool, ...], ...] | None) -> float:
    normalized = _normalized_shape(source)
    if normalized is None:
        return 0.0 if template is None else 1.0
    if template is None:
        return 1.0
    right = np.asarray(template, dtype=bool)
    return float(np.count_nonzero(np.logical_xor(normalized, right)) / max(1, normalized.size))


def _source_topology_bonus(glyph: str, crop: np.ndarray, *, base_advance: float) -> float:
    """Return a bounded source-mask topology bonus.

    Template fonts are useful proposal evidence, but normalized fallback
    silhouettes can turn a diagonal or a low horizontal stroke into a curved
    delimiter.  These features describe only measured ink topology; they do
    not inspect text, a fixture transcript, or a glyph-specific image rule.
    The result is a small ranking term, never an acceptance decision.
    """

    ys, xs = np.where(crop)
    if not len(xs):
        return 0.0
    height, width = crop.shape
    bbox_width = max(1, int(xs.max() - xs.min() + 1))
    bbox_height = max(1, int(ys.max() - ys.min() + 1))
    row_indices = np.where(crop.any(axis=1))[0]
    row_runs = 1 + int(np.count_nonzero(np.diff(row_indices) > 1)) if len(row_indices) else 0
    row_peak = int(crop.sum(axis=1).max())
    col_peak = int(crop.sum(axis=0).max())
    row_centres = [float(np.mean(np.where(crop[int(row)])[0])) for row in row_indices if crop[int(row)].any()]
    centre_swing = max(row_centres) - min(row_centres) if row_centres else 0.0
    slope = 0.0
    if len(ys) > 1 and float(np.var(ys)) > 0.0:
        centred_y = ys.astype(float) - float(np.mean(ys))
        centred_x = xs.astype(float) - float(np.mean(xs))
        slope = float(np.mean(centred_y * centred_x) / max(float(np.mean(centred_y * centred_y)), 1e-9))
    centre_y = float(np.mean(ys) / max(1, height - 1))
    horizontal_band = bbox_height <= max(3, int(height * 0.35)) and bbox_width >= max(4, int(base_advance * 0.55))
    tall_narrow = bbox_height >= int(height * 0.55) and bbox_width <= max(8, int(base_advance * 0.90))
    compact_mark = bbox_width <= max(7, int(base_advance * 0.60)) and bbox_height <= max(8, int(height * 0.45))
    short_horizontal_fragment = (
        bbox_height <= max(3, int(height * 0.25))
        and bbox_width >= 2
        and row_peak >= max(1, int(math.ceil(bbox_width * 0.45)))
        and centre_y >= 0.45
    )
    broad_tall_delimiter = (
        bbox_width >= max(5, int(round(base_advance * 0.45)))
        and bbox_height >= max(8, int(round(height * 0.50)))
        and row_runs >= 5
    )

    bonus = 0.0
    if glyph in {"/", "／"} and slope < -0.12 and bbox_height >= int(height * 0.45):
        bonus -= 0.32
    if glyph in {"\\", "＼"} and slope > 0.12 and bbox_height >= int(height * 0.45):
        bonus -= 0.32
    if glyph in {"ノ", "ﾉ"} and slope < -0.12 and bbox_height >= int(height * 0.35):
        bonus -= 0.18
    if glyph in {"|", "│", "l"} and tall_narrow and col_peak >= max(2, int(bbox_height * 0.45)):
        bonus -= 0.16
    if glyph in {"_", "＿"} and horizontal_band and centre_y >= 0.60:
        bonus -= 0.32
    if glyph in {"_", "＿"} and short_horizontal_fragment:
        # A connected underscore can be split into a narrow edge fragment by
        # a neighboring bar/diagonal.  Preserve its horizontal-band evidence
        # instead of letting compact punctuation win on bbox width alone.
        bonus -= 0.22
    if glyph in {"-", "￣", "="} and horizontal_band and 0.25 <= centre_y <= 0.75:
        bonus -= 0.20
    if glyph in {"-", "￣", "="} and short_horizontal_fragment:
        bonus -= 0.12
    if glyph in {"~"} and horizontal_band and row_runs >= 2:
        bonus -= 0.18
    if glyph in {"`", "'", ",", ".", "、", "丶"} and compact_mark and abs(slope) >= 0.12:
        # Isolated punctuation remains ambiguous, but a compact slanted mark
        # should remain visible beside a much larger normalized delimiter.
        bonus -= 0.18
    if glyph in {"`", "'", ",", ".", "、", "丶"} and short_horizontal_fragment:
        bonus += 0.16
    if glyph in {"`", "'", ",", ".", "、", "丶"} and broad_tall_delimiter:
        # A punctuation template may fit a broad connected diagonal by
        # accident.  Its isolated-mark interpretation is not supported when
        # the source mask has a tall, multi-row delimiter footprint.
        bonus += 0.22
    if glyph in {">", "＞", "<", "＜"} and broad_tall_delimiter:
        # Preserve the source-supported two-arm delimiter family for a broad
        # connected component; this is a morphology preference, not a glyph
        # identity assertion.
        bonus -= 0.18
    if glyph == "x" and bbox_height >= int(height * 0.40) and centre_swing >= max(2.0, bbox_width * 0.35):
        bonus -= 0.14
    if glyph == "ミ" and row_runs >= 2 and row_peak >= max(3, int(bbox_width * 0.35)):
        bonus -= 0.15
    if glyph == "フ" and row_peak >= max(4, int(bbox_width * 0.55)) and centre_y <= 0.65:
        bonus -= 0.12
    return max(-0.40, bonus)


def _has_crossing_diagonals(crop: np.ndarray) -> bool:
    """Detect an ``x``-like crossing without assigning a character.

    Connected text art frequently puts two diagonal strokes in one measured
    cell.  A normalized font residual is a poor discriminator for that crop:
    neighboring pixels can make the mask look like a bracket, slash, or a
    malformed kana fragment.  This predicate is deliberately only a topology
    signal.  It keeps an ``x`` proposal alive for the row decoder; it never
    labels the source or grants acceptance authority.
    """

    mask = np.asarray(crop, dtype=bool)
    ys, xs = np.where(mask)
    if len(xs) < 6:
        return False
    height, width = mask.shape
    if height < 5 or width < 5:
        return False
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    span_y = y1 - y0 + 1
    span_x = x1 - x0 + 1
    if span_y < max(5, int(height * 0.45)) or span_x < max(5, int(width * 0.45)):
        return False
    # Count source pixels close to the two opposing diagonal envelopes.  The
    # envelopes are evidence windows, not a synthetic glyph raster.
    tolerance = max(1.5, min(3.0, width * 0.16))
    support = 0
    for y, x in zip(ys, xs):
        fraction = (float(y) - y0) / max(1.0, float(span_y - 1))
        left = x0 + fraction * (span_x - 1)
        right = x1 - fraction * (span_x - 1)
        if min(abs(float(x) - left), abs(float(x) - right)) <= tolerance:
            support += 1
    return support / max(1, len(xs)) >= 0.28


def _looks_like_two_narrow_tokens(mask: np.ndarray, base_advance: float) -> bool:
    """Detect two separated narrow glyphs inside a nominal wide span."""

    # Column occupancy is more stable than connected-component count for
    # antialiased diagonals, whose pixels frequently disconnect vertically.
    projection = mask.sum(axis=0)
    active = projection >= 2
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, present in enumerate(active):
        if present and start is None:
            start = index
        elif not present and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    if len(runs) >= 2:
        for (left, right), (next_left, next_right) in zip(runs, runs[1:]):
            if (
                (right - left) <= base_advance * 0.70
                and (next_left - right) >= base_advance * 0.20
                and (next_right - next_left) <= base_advance * 0.70
            ):
                return True

    seen = np.zeros_like(mask, dtype=bool)
    boxes: list[tuple[int, int]] = []
    height, width = mask.shape
    for y, x in zip(*np.where(mask)):
        if seen[y, x]:
            continue
        stack = [(int(y), int(x))]
        seen[y, x] = True
        x_values: list[int] = []
        while stack:
            cy, cx = stack.pop()
            x_values.append(cx)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if x_values:
            boxes.append((min(x_values), max(x_values) + 1))
    boxes.sort()
    # Anti-aliased diagonals often fracture into several one-pixel connected
    # components.  Merge fragments that are horizontally adjacent before
    # deciding whether a nominal wide span contains two narrow tokens.
    merged: list[tuple[int, int]] = []
    for left, right in boxes:
        if merged and left <= merged[-1][1] + 2:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    boxes = merged
    if any(
        (right - left) <= base_advance * 0.70
        and (next_left - right) >= base_advance * 0.20
        and (next_right - next_left) <= base_advance * 0.70
        for (left, right), (next_left, next_right) in zip(boxes, boxes[1:])
    ):
        return True
    # A narrow delimiter followed by a broad horizontal component is another
    # common composite (for example `(=`) that a fullwidth template can
    # otherwise swallow.  Preserve it as a split-token alternative without
    # assuming which characters the components represent.
    widths = [right - left for left, right in boxes]
    return bool(
        len(widths) >= 2
        and any(width <= base_advance * 0.70 for width in widths)
        and any(width <= base_advance * 1.15 for width in widths)
    )


def _glyph_position_penalty(glyph: str, crop: np.ndarray) -> float:
    ys, _ = np.where(crop)
    if not len(ys):
        return 0.0
    centre = float(np.mean(ys) / max(1, crop.shape[0] - 1))
    if glyph in {"_", "＿"}:
        return 0.0 if centre >= 0.62 else 0.35
    if glyph == "=":
        return 0.0 if 0.28 <= centre <= 0.72 else 0.35
    if glyph in {"-", "￣"}:
        return 0.0 if 0.30 <= centre <= 0.68 else 0.25
    return 0.0


def _structural_glyph_penalty(glyph: str, crop: np.ndarray) -> float:
    """Reject punctuation labels that contradict the occupied mask.

    A template-normalized dot can tie with a long horizontal stroke because
    both are resized to their own bounding boxes.  This gate keeps isolated
    punctuation small and lets a full-width dash/underscore own a substantive
    horizontal component.  It is deliberately script-agnostic and uses only
    the current source crop.
    """

    ys, xs = np.where(crop)
    if not len(xs):
        return 0.0
    bbox_width = max(1, int(xs.max() - xs.min() + 1))
    bbox_height = max(1, int(ys.max() - ys.min() + 1))
    area = int(len(xs))
    height, width = crop.shape
    left_margin = float(xs.min()) / max(1, width)
    horizontal_band = float(np.max(crop.sum(axis=1))) / max(1, bbox_width)
    vertical_band = float(np.max(crop.sum(axis=0))) / max(1, bbox_height)
    occupied_rows = np.where(crop.sum(axis=1) > 0)[0]
    row_runs = 0
    if len(occupied_rows):
        row_runs = 1 + int(np.count_nonzero(np.diff(occupied_rows) > 1))
    y_values, x_values = np.where(crop)
    slope = 0.0
    if len(y_values) > 1 and float(np.var(y_values)) > 0.0:
        centred_y = y_values.astype(float) - float(np.mean(y_values))
        centred_x = x_values.astype(float) - float(np.mean(x_values))
        slope = float(np.mean(centred_y * centred_x) / max(float(np.mean(centred_y * centred_y)), 1e-9))
    row_centres: list[float] = []
    for row in np.where(crop.any(axis=1))[0]:
        occupied = np.where(crop[int(row)])[0]
        if len(occupied):
            row_centres.append(float(occupied.mean()))
    centre_swing = (max(row_centres) - min(row_centres)) if row_centres else 0.0
    isolated = {".", "'", "`", ",", "、", "丶"}
    if glyph in isolated:
        penalty = 0.0
        if area > 12:
            penalty += 0.25
        if bbox_width > max(3, int(width * 0.38)) or bbox_height > max(3, int(height * 0.38)):
            penalty += 0.20
        if horizontal_band > 0.72 or vertical_band > 0.72:
            penalty += 0.20
        return penalty
    if glyph in {"/", "／"} and slope > -0.12:
        return 0.28
    if glyph in {"\\", "＼"} and slope < 0.12:
        return 0.28
    if glyph in {"<", ">", "(", ")", "[", "]"} and abs(slope) > 0.20:
        return 0.16
    if glyph in {"<", ">"} and bbox_height >= int(height * 0.60) and vertical_band >= 0.72:
        return 0.42
    # A template-normalized glyph must still explain where the source ink sits
    # inside its proposed display span.  A wide token that contains only a
    # narrow component at its right edge is usually an offset alternative,
    # not a real full-width grapheme.
    if left_margin > 0.30 and glyph not in {"(", ")", "[", "]", "<", ">"}:
        return 0.55
    if glyph in {"_", "＿", "-", "=", "￣"}:
        # A horizontal glyph needs a broad occupied span.  The separate
        # position penalty distinguishes middle dash from bottom underscore.
        coverage_floor = 0.55 if glyph in {"＿", "￣"} else 0.42
        penalty = 0.80 if bbox_width < max(3, int(width * coverage_floor)) else 0.0
        # A parenthesis/bracket crop can normalize to a deceptively good
        # horizontal template.  A true dash/equals/underscore should occupy a
        # short vertical band; a tall narrow mask is a delimiter candidate.
        if bbox_height >= int(height * 0.55) and bbox_width < max(4, int(width * 0.75)):
            penalty += 0.34
        if centre_swing > max(1.0, bbox_width * 0.30):
            penalty += 0.34
        # A narrow horizontal crop that reaches its right/left edge is often
        # only a fragment of a longer run.  Prefer the wide candidate when it
        # can own the continuation; do not let a cell-local underscore win by
        # lexicographic tie-breaking.
        if glyph in {"_", "-"} and (bool(crop[:, :2].any()) or bool(crop[:, -2:].any())):
            penalty += 0.18
        return penalty
    if glyph in {"|", "│"}:
        penalty = 0.22 if bbox_height < max(3, int(height * 0.42)) else 0.0
        # A broad, full-height crop is more likely a curved delimiter or a
        # joined component than a single vertical bar.  Keep the bar candidate
        # available, but let the delimiter win when its footprint is wide.
        if bbox_height >= int(height * 0.60) and bbox_width > max(4, int(width * 0.28)):
            penalty += 0.28
        return penalty
    if glyph == "l":
        # In a fixed-cell structural raster, lowercase l and a vertical bar
        # can be visually identical.  Keep l available for proposal coverage,
        # but do not let it outrank an explicit bar on a tall one-column mask.
        if bbox_height >= int(height * 0.60) and bbox_width <= max(6, int(width * 0.28)) and vertical_band >= 0.72:
            return 0.50
        # Keep l as a lower-ranked alternative even when its crop is not a
        # perfect bar; otherwise template normalization makes it a universal
        # cheap substitute for punctuation and horizontal fragments.
        return 0.32
    if glyph in {"[", "]", "(", ")"}:
        # A tall, nearly one-column stroke is a bar, not a bracket/parenthesis.
        if (
            bbox_height >= int(height * 0.60)
            and bbox_width <= max(6, int(width * 0.28))
            and vertical_band >= 0.72
            and centre_swing <= max(1.0, bbox_width * 0.30)
        ):
            return 0.55
        return 0.0
    if glyph in {"／", "＞", "ノ", "ヽ", "フ", "ミ"}:
        # A wide token containing one very narrow component is usually an
        # ASCII slash/greater-than crop plus a neighbouring cell, not one
        # full-width grapheme.
        if bbox_width <= max(3, int(width * 0.28)):
            return 0.48
        return 0.0
    if glyph == "ミ":
        # ミ is a multi-band Japanese grapheme.  Do not let a single compact
        # stroke or a one-band fragment claim its two-unit span.
        if row_runs < 2 or bbox_width < max(4, int(width * 0.28)):
            return 0.40
        return 0.0
    if glyph == "フ":
        peak_row = int(np.argmax(crop.sum(axis=1))) if crop.size else 0
        peak_fraction = float(np.max(crop.sum(axis=1))) / max(1, bbox_width)
        # フ has a broad upper horizontal stroke followed by a descending
        # right-hand stroke.  A slash/greater-than pair in a wide crop lacks
        # that broad upper band and must not be relabelled フ.
        if peak_fraction < 0.62 or peak_row > int(height * 0.62):
            return 0.38
        return 0.0
    if glyph == "~":
        # A source crop with several separated horizontal bands is more likely
        # to be ミ than a single tilde glyph.
        if bbox_height <= 3 and horizontal_band > 0.70:
            return 0.30
        if row_runs >= 2 and bbox_height >= int(height * 0.35):
            return 0.24
        return 0.0
    return 0.0


def _column_ink_runs(mask: np.ndarray, *, minimum_occupancy: int = 2, merge_gap: int = 1) -> tuple[tuple[int, int], ...]:
    """Return stable x-runs without assigning characters or rows."""

    projection = mask.sum(axis=0)
    active = projection >= minimum_occupancy
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, present in enumerate(active):
        if present and start is None:
            start = index
        elif not present and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    if not runs:
        return ()
    merged: list[tuple[int, int]] = [runs[0]]
    for left, right in runs[1:]:
        if left - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], right)
        else:
            merged.append((left, right))
    return tuple(merged)


def _cluster_glyph_candidates(
    crop: np.ndarray,
    *,
    base_advance: float,
    font_path: str,
    height: int,
    top_k: int = 5,
    allow_both_widths: bool = False,
) -> tuple[tuple[float, str, int], ...]:
    """Rank glyphs for one measured ink cluster.

    Cluster width constrains the Unicode display-width domain before visual
    shape comparison.  This prevents a wide template from swallowing two
    adjacent narrow punctuation marks, while still permitting Japanese
    graphemes whose painted ink does not fill their complete two-unit span.
    """

    ys, xs = np.where(crop)
    if not len(xs):
        return ()
    painted_width = int(xs.max() - xs.min() + 1)
    # A painted width close to one base unit is still usually a narrow
    # punctuation glyph.  Wide Japanese forms generally occupy at least
    # three quarters of a base unit even when their ink does not fill the full
    # two-unit advance; height alone must not turn a tall ASCII slash wide.
    wide_domain = painted_width > base_advance * 0.75
    ranked: list[tuple[float, str, int]] = []
    for glyph, units in _STRUCTURAL_GLYPHS:
        if allow_both_widths:
            allowed = True
        elif wide_domain:
            allowed = units == 2
        else:
            allowed = units == 1
        if not allowed:
            continue
        template = _structural_template(font_path, glyph, units, max(1, round(base_advance)), height)
        score = _structural_shape_score(crop, template)
        score += _source_topology_bonus(glyph, crop, base_advance=base_advance)
        score += _glyph_position_penalty(glyph, crop)
        score += _structural_glyph_penalty(glyph, crop)
        if _orthogonal_composite_variant(
            np.asarray(crop, dtype=bool),
            base_advance=base_advance,
            origin=0.0,
            unicode_enabled=True,
        ) is not None and glyph in {"フ", "ミ", "ノ", "ﾉ", "ヽ"}:
            # A horizontal band plus a tall bar has an explicit source
            # decomposition.  A single fallback kana silhouette must not
            # outrank that measured morphology merely by template residual.
            score += 0.22
        # The source mask's topology is stronger evidence than a fallback
        # font's normalized silhouette.  Short broad bands are horizontal
        # structural glyphs; tall narrow masks are bars.  Without this prior,
        # disconnected Japanese/Latin fallback templates can outrank the
        # ASCII form that actually explains the measured stroke orientation.
        ys, xs = np.where(crop)
        if len(xs):
            bbox_width = int(xs.max() - xs.min() + 1)
            bbox_height = int(ys.max() - ys.min() + 1)
            horizontal_band = (
                bbox_height <= max(3, int(height * 0.28))
                and bbox_width >= max(4, int(base_advance * 0.35))
            )
            tall_narrow_bar = (
                bbox_height >= int(height * 0.55)
                and bbox_width <= max(6, int(base_advance * 0.45))
            )
            if horizontal_band and glyph in {"_", "-", "=", "￣", "＿"}:
                score -= 0.35
            if tall_narrow_bar and glyph in {"|", "│"}:
                score -= 0.35
        # Broad top bands are a reliable distinction for フ versus diagonal
        # punctuation in fonts with different stroke weights.
        if glyph == "フ":
            peak = float(np.max(crop.sum(axis=1))) / max(1, painted_width)
            peak_row = int(np.argmax(crop.sum(axis=1)))
            if peak >= 0.80 and peak_row <= int(height * 0.55):
                score -= 0.22
        if glyph == "ミ":
            row_runs = _column_ink_runs(crop.T, minimum_occupancy=1, merge_gap=1)
            if len(row_runs) >= 2:
                score -= 0.16
        ranked.append((score, glyph, units))
    # A fallback font must not decide between glyphs that share the same
    # measured stroke family.  In particular, a diagonal source component can
    # legitimately be `/`, fullwidth `／`, Japanese `ノ`/`ﾉ`, or a backslash-
    # family `ヽ`; their Unicode identity belongs to the complete run and its
    # ownership evidence, not to a normalized font silhouette in one crop.
    # Keep source-supported family members within a small deterministic margin
    # so the incremental decoder can carry them without enumerating a product.
    ys, xs = np.where(crop)
    if len(xs):
        bbox_height = int(ys.max() - ys.min() + 1)
        slope = 0.0
        if len(ys) > 1 and float(np.var(ys)) > 0.0:
            centred_y = ys.astype(float) - float(np.mean(ys))
            centred_x = xs.astype(float) - float(np.mean(xs))
            slope = float(np.mean(centred_y * centred_x) / max(float(np.mean(centred_y * centred_y)), 1e-9))
        family: tuple[str, ...] = ()
        if bbox_height >= int(height * 0.35) and slope < -0.12:
            family = ("/", "／", "ノ", "ﾉ")
        elif bbox_height >= int(height * 0.35) and slope > 0.12:
            family = ("\\", "＼", "ヽ")
        if family:
            family_costs = [cost for cost, glyph, _units in ranked if glyph in family]
            if family_costs:
                family_floor = min(family_costs)
                ranked = [
                    (min(cost, family_floor + 0.08) if glyph in family else cost, glyph, units)
                    for cost, glyph, units in ranked
                ]
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    selected = list(ranked[:top_k])
    # A compact diagonal component is intrinsically ambiguous between a
    # slash/backslash and punctuation such as a backtick or apostrophe.  Keep
    # the punctuation alternatives in the proposal domain even when the
    # fallback template ranks them just outside top-k; component ownership and
    # row context, not this local shape tie, must decide.
    ys, xs = np.where(crop)
    if len(xs):
        compact = (
            int(xs.max() - xs.min() + 1) <= max(7, int(base_advance * 0.60))
            and int(ys.max() - ys.min() + 1) <= max(8, int(height * 0.45))
        )
        if compact:
            for item in ranked:
                if item[1] in {"`", "'", ",", ".", "、", "丶"} and item not in selected:
                    selected.append(item)
    return tuple(selected)


def _lattice_horizontal_sequence(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    font_path: str,
    beam_width: int,
) -> str | None:
    """Propose repeated narrow horizontals at measured lattice seams.

    A connected underline/dash run is not evidence of one wide grapheme.  If
    its shallow mask spans several measured columns, preserve each column as
    a separate narrow structural proposal.  Other painted clusters are still
    represented by their best local template; this helper only adds evidence
    and never chooses a logical sequence.
    """

    clusters = _column_ink_runs(raster)
    if not clusters:
        return None
    # Emit from logical display column zero.  The physical run may begin at a
    # clipped/negative origin, but dropping the prefix here silently changes
    # indentation and makes every row impossible to align with its siblings.
    first_col = 0
    occupied_x = np.where(raster.any(axis=0))[0]
    if not len(occupied_x):
        return None
    last_col = int(math.ceil((int(occupied_x.max()) + 1 - origin) / base_advance))
    cursor = first_col
    output: list[str] = []
    repeated = False
    for left, right in clusters:
        start_col = max(first_col, int(math.floor((left - origin) / base_advance)))
        end_col = min(last_col, int(math.ceil((right - origin) / base_advance)))
        if end_col <= start_col or start_col < cursor:
            return None
        output.extend(" " for _ in range(start_col - cursor))
        crop = raster[:, left:right]
        ys, xs = np.where(crop)
        if not len(xs):
            continue
        bbox_width = int(xs.max() - xs.min() + 1)
        bbox_height = int(ys.max() - ys.min() + 1)
        span = max(1, end_col - start_col)
        if (
            span >= 2
            and bbox_height <= max(3, int(raster.shape[0] * 0.28))
            and bbox_width >= max(4, int(base_advance * 0.70))
        ):
            centre = float(ys.mean() / max(1, raster.shape[0] - 1))
            occupied_rows = np.where(crop.any(axis=1))[0]
            row_runs = 1 + int(np.count_nonzero(np.diff(occupied_rows) > 1)) if len(occupied_rows) else 1
            if row_runs >= 2 and 0.25 <= centre <= 0.75:
                glyph = "="
            elif centre >= 0.60:
                glyph = "_"
            else:
                glyph = "-"
            output.extend(glyph for _ in range(span))
            repeated = True
        else:
            candidates = _cluster_glyph_candidates(
                crop,
                base_advance=base_advance,
                font_path=font_path,
                height=raster.shape[0],
                top_k=max(1, min(beam_width, 4)),
            )
            if not candidates:
                return None
            glyph, units = candidates[0][1], candidates[0][2]
            if units > (end_col - start_col):
                units = end_col - start_col
            output.append(glyph)
            output.extend(" " for _ in range(max(0, units - 1)))
        cursor = end_col
    if not repeated:
        return None
    output.extend(" " for _ in range(max(0, last_col - cursor)))
    return "".join(output)


def _cluster_sequences(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    font_path: str,
    beam_width: int,
) -> tuple[tuple[str, float], ...]:
    """Build bounded component-anchored row proposals.

    The fixed-unit beam remains the broad fallback.  This path uses measured
    painted clusters to stop a wide grapheme from consuming a neighbouring
    slash/greater-than pair.  Every cluster retains its top-k shape candidates
    and a deterministic sequence beam combines them.  It emits proposal
    evidence only; component ownership and exact Unicode identity remain
    downstream gates.
    """

    clusters = _column_ink_runs(raster)
    if not clusters:
        return (("", 0.0),)
    # Keep logical leading columns in the proposal.  ``origin`` may place the
    # first physical cell partly outside the cropped run; that is geometry
    # evidence, not permission to delete logical spaces.
    first_col = 0
    # The run strip is content-cropped, but its right edge is snapped to the
    # next lattice boundary.  Using the strip width here invents a trailing
    # partial column (and can make its rounded interval zero pixels wide).
    # Logical output ends at the last measured foreground pixel; source/layout
    # evidence retains the full canvas bounds separately.
    occupied_x = np.where(raster.any(axis=0))[0]
    last_col = (
        int(math.ceil((int(occupied_x.max()) + 1 - origin) / base_advance))
        if len(occupied_x)
        else first_col
    )
    cluster_options: list[tuple[int, tuple[tuple[str, int, float], ...]]] = []
    for cluster_index, (left, right) in enumerate(clusters):
        absolute_left = float(left)
        start_col = int(math.floor((absolute_left - origin) / base_advance))
        start_col = max(first_col, start_col)
        # Prefer the painted cluster bounds for shape identity, but keep the
        # display span available for width/placement evidence.
        crop = raster[:, left:right]
        if (right - left) <= 2 and int(crop.sum()) <= max(6, int(raster.shape[0] * 0.15)):
            # Tiny isolated edge fragments are retained in component evidence,
            # but cannot become a logical bracket/mark without independent
            # ownership.  The proposal path fails closed on them.
            continue
        candidates = _cluster_glyph_candidates(
            crop,
            base_advance=base_advance,
            font_path=font_path,
            height=raster.shape[0],
            # Keep a wider local domain than the sequence beam.  Structural
            # ASCII glyphs can rank below a visually similar CJK fallback, but
            # must remain available for row-level ownership and tie analysis.
            top_k=max(beam_width, 16),
            allow_both_widths=True,
        )
        if not candidates:
            continue
        options: list[tuple[str, int, float]] = []
        for score, glyph, units in candidates:
            span_options = (units, 1) if units == 2 else (units,)
            for span in span_options:
                # A narrow painted mark can be either a one-unit rendering of
                # a wide grapheme or a clipped/tightly kerned two-unit form.
                # Preserve both hypotheses; the later width/ownership gate is
                # the only authority allowed to choose.
                if span == 2 and (right - left) < base_advance * 0.55:
                    span = 1
                if start_col + span > last_col:
                    span = max(1, last_col - start_col)
                options.append((glyph, span, float(score) + (0.04 if span != units else 0.0)))
        cluster_options.append((start_col, tuple(options)))
    if not cluster_options:
        return ()

    # A state stores the last occupied display column and its chosen tokens.
    # Overlapping wide candidates are retained only when they do not claim the
    # next painted cluster; this prevents one fullwidth template from silently
    # swallowing two narrow source components.
    states: list[tuple[float, int, tuple[tuple[int, str, int], ...]]] = [(0.0, first_col, ())]
    for option_index, (start_col, options) in enumerate(cluster_options):
        next_start = cluster_options[option_index + 1][0] if option_index + 1 < len(cluster_options) else last_col
        expanded: list[tuple[float, int, tuple[tuple[int, str, int], ...]]] = []
        for cost, cursor, tokens in states:
            if start_col < cursor:
                continue
            for glyph, units, local_cost in options:
                end_col = min(last_col, start_col + units)
                if end_col <= start_col:
                    continue
                overlap_next = end_col > next_start and next_start < last_col
                # A wide East-Asian glyph can paint inside the next measured
                # cluster when the source renderer uses proportional/legacy
                # metrics.  Dropping that path here silently converts a
                # plausible Japanese grapheme sequence into ASCII fallback.
                # Retain it as explicitly uncertain evidence, advancing the
                # cursor only to the next anchor so the neighbouring cluster
                # is still proposed.  Ownership/alignment gates remain
                # responsible for rejecting competing claims later.
                overlap_penalty = 0.10 if overlap_next else 0.0
                next_cursor = min(end_col, next_start) if overlap_next else end_col
                expanded.append(
                    (
                        cost + max(0.0, local_cost) + overlap_penalty,
                        next_cursor,
                        tokens + ((start_col, glyph, units),),
                    )
                )
        expanded.sort(key=lambda item: (item[0], item[1], item[2]))
        states = expanded[: max(1, beam_width * 2)]
        if not states:
            return ()

    rendered: list[tuple[str, float]] = []
    for cost, _cursor, tokens in states:
        output: list[str] = []
        cursor = first_col
        valid = True
        for start_col, glyph, units in tokens:
            if start_col >= cursor:
                output.extend(" " for _ in range(start_col - cursor))
            # Overlapping anchors cannot be represented as a single fixed
            # lattice without choosing a renderer.  Preserve the grapheme
            # order in the proposal text and let the width/ownership evidence
            # mark the layout ambiguous instead of deleting the token.
            output.append(glyph)
            if start_col >= cursor:
                output.extend(" " for _ in range(max(0, units - 1)))
            cursor = max(cursor, start_col + units)
        if not valid:
            continue
        output.extend(" " for _ in range(max(0, last_col - cursor)))
        rendered.append(("".join(output), float(cost)))
    rendered.sort(key=lambda item: (item[1], item[0]))
    unique: list[tuple[str, float]] = []
    seen: set[str] = set()
    for item in rendered:
        if item[0] in seen:
            continue
        seen.add(item[0])
        unique.append(item)
        if len(unique) >= max(1, beam_width):
            break
    lattice_horizontal = _lattice_horizontal_sequence(
        raster,
        base_advance=base_advance,
        origin=origin,
        font_path=font_path,
        beam_width=beam_width,
    )
    if lattice_horizontal and lattice_horizontal not in seen:
        # This is source-morphology evidence, not a tail fallback.  A finite
        # deterministic cost keeps it visible under the public proposal cap;
        # downstream ownership/alignment still decides whether it survives.
        unique.insert(0, (lattice_horizontal, 0.05))
    return tuple(unique)


def _orthogonal_composite_variant(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    unicode_enabled: bool,
) -> tuple[str, float] | None:
    """Propose a horizontal-band plus vertical-bar decomposition.

    Some connected text-art components span two narrow units and contain two
    independent structural strokes.  A fallback font can make that mask look
    like one kana/curved glyph.  This detector names no arbitrary character: it
    only emits the measured horizontal/vertical token families as a lower-cost
    proposal for the row decoder.
    """

    height, width = raster.shape
    if width <= 0 or width > int(math.ceil(base_advance * 2.5)) or height < 6:
        return None
    ys, xs = np.where(raster)
    if len(xs) < 6:
        return None
    row_projection = raster.sum(axis=1)
    col_projection = raster.sum(axis=0)
    horizontal_rows = np.where(row_projection >= max(3, int(width * 0.45)))[0]
    vertical_cols = np.where(col_projection >= max(4, int(height * 0.45)))[0]
    if not len(horizontal_rows) or not len(vertical_cols):
        return None
    horizontal_y = int(round(float(horizontal_rows.mean())))
    vertical_x = int(round(float(vertical_cols.mean())))
    if int(row_projection[horizontal_y]) < max(3, int(width * 0.45)):
        return None
    if int(col_projection[vertical_x]) < max(4, int(height * 0.45)):
        return None
    # A horizontal band and bar should be distinct structural strokes rather
    # than the broad top of a single fallback glyph.
    if abs(horizontal_y - float(np.mean(ys))) < height * 0.08:
        return None
    horizontal = "￣" if unicode_enabled and horizontal_y <= int(height * 0.45) else "_"
    vertical = "│" if unicode_enabled and col_projection[vertical_x] >= int(height * 0.70) else "|"
    horizontal_center = float(np.mean(np.where(raster[horizontal_y])[0]))
    if vertical_x < horizontal_center:
        text = vertical + horizontal
    else:
        text = horizontal + vertical
    prefix = max(0, int(math.floor((int(xs.min()) - origin) / max(base_advance, 1e-6))))
    return (0.08, " " * prefix + text)


def _fragment_sequence_variants(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    font_path: str,
    unicode_enabled: bool,
) -> tuple[tuple[float, str], ...]:
    """Build bounded alternatives from disconnected ink fragments.

    A painted interval may contain a real mark plus a one-pixel continuation
    from a neighbouring row.  Treating the interval as one shape turns the
    mark into a slash/bar composite; treating every fragment as a character
    turns Japanese multi-stroke glyphs into punctuation.  Keep a separate
    fragment sequence as proposal evidence while retaining the whole-shape
    alternatives.  Tiny fragments remain unlabelled and contribute no text.
    """

    if raster.ndim != 2 or not raster.any():
        return ()
    height, width = raster.shape
    seen = np.zeros_like(raster, dtype=bool)
    fragments: list[tuple[int, int, np.ndarray, int]] = []
    for y in range(height):
        for x in range(width):
            if not raster[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            points: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                points.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if not dx and not dy:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < height and 0 <= nx < width and raster[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            ys = [point[0] for point in points]
            xs = [point[1] for point in points]
            x0, x1 = min(xs), max(xs) + 1
            y0, y1 = min(ys), max(ys) + 1
            local = np.zeros((y1 - y0, x1 - x0), dtype=bool)
            local[np.asarray(ys) - y0, np.asarray(xs) - x0] = True
            fragments.append((x0, x1, local, len(points)))
    if len(fragments) <= 1 or len(fragments) > 8:
        # Large multi-stroke glyphs (for example kana) are better represented
        # by the whole-shape beam.  Decomposing them would create a second
        # Cartesian surface without adding reliable ownership evidence.
        return ()
    fragments.sort(key=lambda value: (value[0], value[1], value[3]))
    tiny_limit = max(3, int(height * 0.15))
    states: list[tuple[float, str, int]] = [(0.0, "", 0)]
    retained_fragments = 0
    for x0, x1, local, area in fragments:
        if area <= tiny_limit:
            # Preserve this as an ownership fact, not as punctuation.
            continue
        retained_fragments += 1
        local_options = _topology_row_variants(
            local,
            base_advance=base_advance,
            origin=origin - x0,
            font_path=font_path,
            unicode_enabled=unicode_enabled,
            max_variants=8,
            include_fragment_decomposition=False,
        )
        values: list[tuple[float, str]] = []
        for local_cost, raw in local_options:
            text = str(raw).strip(" \u3000")
            if text:
                values.append((float(local_cost), text))
        if not values:
            continue
        values = sorted(dict(((text, cost) for cost, text in values)).items(), key=lambda item: (item[1], item[0]))
        values = [(cost, text) for text, cost in values[:8]]
        next_states: list[tuple[float, str, int]] = []
        for cost, text, previous_x1 in states:
            gap_units = max(0, int(round((x0 - previous_x1) / max(base_advance, 1e-6)))) if previous_x1 else 0
            for local_cost, fragment_text in values:
                separator = " " * gap_units
                next_states.append((
                    cost + local_cost + 0.04 * gap_units,
                    text + separator + fragment_text,
                    x1,
                ))
        next_states.sort(key=lambda value: (value[0], value[1], value[2]))
        states = next_states[:32]
    if retained_fragments < 1:
        return ()
    return tuple((cost + 0.10, text) for cost, text, _ in states[:16])


def _topology_row_variants(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    font_path: str,
    unicode_enabled: bool,
    max_variants: int = 256,
    include_fragment_decomposition: bool = True,
) -> tuple[tuple[str, float], ...]:
    """Compose a bounded row beam from measured cell topology.

    A connected source cell may be a fragment of a glyph on either side.  In
    that case a local template residual is not evidence that ``x``, a
    horizontal mark, a compact diagonal, or a Japanese structural grapheme is
    impossible.  This second proposal surface keeps topology-supported
    alternatives alive through complete-row decoding.  It is proposal-only:
    ownership, logical width, and geometry/text gates remain authoritative.
    """

    occupied_x = np.where(raster.any(axis=0))[0]
    if not len(occupied_x) or base_advance <= 0:
        return ()
    last_col = int(math.ceil((int(occupied_x.max()) + 1 - origin) / base_advance))
    if last_col <= 0:
        return ()
    allowed_wide = {"／", "＞", "＿", "￣", "フ", "ミ", "ノ", "ヽ", "丶", "、"}
    if not unicode_enabled:
        allowed_wide = set()
    beam: list[tuple[float, str]] = [(0.0, "")]
    for column in range(last_col):
        raw_x0 = int(round(origin + column * base_advance))
        raw_x1 = int(round(origin + (column + 1) * base_advance))
        if raw_x1 <= 0 or raw_x0 >= raster.shape[1]:
            options = ((0.0, " "),)
        else:
            x0 = max(0, raw_x0)
            x1 = min(raster.shape[1], raw_x1)
            crop = raster[:, x0:x1]
            if crop.size == 0 or not crop.any():
                options = ((0.0, " "),)
            else:
                ranked: dict[str, float] = {}
                for cost, glyph, _units in _cluster_glyph_candidates(
                    crop,
                    base_advance=base_advance,
                    font_path=font_path,
                    height=raster.shape[0],
                    top_k=4,
                    allow_both_widths=True,
                ):
                    if glyph == " " or (glyph in allowed_wide or ord(glyph[0]) < 128):
                        ranked[glyph] = min(ranked.get(glyph, 9.0), float(cost))
                ys, xs = np.where(crop)
                bbox_width = int(xs.max() - xs.min() + 1)
                bbox_height = int(ys.max() - ys.min() + 1)
                row_peak = int(crop.sum(axis=1).max())
                horizontal = (
                    bbox_height <= max(4, int(raster.shape[0] * 0.42))
                    and row_peak >= max(3, int(crop.shape[1] * 0.42))
                )
                crossing = _has_crossing_diagonals(crop)
                tall = (
                    bbox_height >= int(raster.shape[0] * 0.50)
                    and bbox_width <= max(9, int(base_advance * 0.95))
                )
                compact = (
                    bbox_width <= max(8, int(base_advance * 0.80))
                    and bbox_height <= max(12, int(raster.shape[0] * 0.80))
                )
                if horizontal:
                    for glyph in ("_", "-", "=", "~"):
                        ranked[glyph] = min(ranked.get(glyph, 9.0), 0.26)
                    if unicode_enabled:
                        for glyph in ("＿", "￣"):
                            ranked[glyph] = min(ranked.get(glyph, 9.0), 0.30)
                if tall:
                    for glyph in ("|", "l"):
                        ranked[glyph] = min(ranked.get(glyph, 9.0), 0.28)
                    if unicode_enabled:
                        ranked["│"] = min(ranked.get("│", 9.0), 0.30)
                if crossing or compact:
                    for glyph in ("/", "\\", "`", "'", "ノ", "ﾉ", "ヽ", "x"):
                        if glyph in {"ノ", "ヽ"} and not unicode_enabled:
                            continue
                        ranked[glyph] = min(ranked.get(glyph, 9.0), 0.28 if crossing else 0.32)
                    if unicode_enabled:
                        ranked["／"] = min(ranked.get("／", 9.0), 0.30)
                if bbox_height >= int(raster.shape[0] * 0.55) and bbox_width >= max(8, int(base_advance * 0.70)) and unicode_enabled:
                    for glyph in ("ミ", "フ"):
                        ranked[glyph] = min(ranked.get(glyph, 9.0), 0.34)
                options = tuple(sorted(((cost, glyph) for glyph, cost in ranked.items()), key=lambda item: (item[0], item[1])))
                if not options:
                    options = ((1.0, "?"),)
        expanded = [(cost + option_cost, text + glyph) for cost, text in beam for option_cost, glyph in options]
        expanded.sort(key=lambda item: (item[0], item[1]))
        beam = expanded[: max(32, min(max_variants, 256))]
    composite = _orthogonal_composite_variant(
        raster,
        base_advance=base_advance,
        origin=origin,
        unicode_enabled=unicode_enabled,
    )
    if composite is not None:
        # A single fallback kana silhouette is mutually exclusive with the
        # measured orthogonal decomposition.  Keep it as evidence, but do not
        # let template distance outrank the source morphology.
        adjusted = [
            (
                cost + (0.30 if any(char in text for char in ("フ", "ミ", "ノ", "ﾉ", "ヽ")) else 0.0),
                text,
            )
            for cost, text in beam
        ]
        adjusted.sort(key=lambda item: (item[0], item[1]))
        beam = [composite, *adjusted]
    if include_fragment_decomposition:
        for fragment_cost, fragment_text in _fragment_sequence_variants(
            raster,
            base_advance=base_advance,
            origin=origin,
            font_path=font_path,
            unicode_enabled=unicode_enabled,
        ):
            if fragment_text and all(fragment_text != text for _cost, text in beam):
                beam.append((fragment_cost, fragment_text))
        beam.sort(key=lambda item: (item[0], item[1]))
    return tuple(beam[:max_variants])



def _run_level_variants(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    font_path: str,
    unicode_enabled: bool,
    max_variants: int = 512,
    deadline: float | None = None,
) -> tuple[tuple[str, float], ...]:
    """Decode one complete measured run as a span lattice.

    Connected-component bounds are deliberately not used here.  A component
    may contain a slash, a fullwidth kana, and a horizontal mark in one
    connected silhouette; treating that component as one glyph (or splitting
    it before recognition) loses the only evidence that distinguishes those
    alternatives.  The geometry owner supplies a measured display basis, so
    this decoder makes edges at one-to-many lattice units and recognizes the
    pixels in each contiguous span as a complete run.

    This is a proposal surface, not a candidate writer.  The finite span DAG
    is decoded incrementally: equivalent text at the same cursor keeps the
    lowest-cost route, while a small family signature preserves distinct
    mixed-width/structural alternatives.  No component-first Cartesian
    product is materialized.
    """

    occupied_x = np.where(raster.any(axis=0))[0]
    if not len(occupied_x) or base_advance <= 0:
        return ()
    first_unit = max(0, int(math.floor((int(occupied_x.min()) - origin) / base_advance)))
    last_unit = int(math.ceil((int(occupied_x.max()) + 1 - origin) / base_advance))
    if last_unit <= first_unit:
        return ()

    def expired() -> bool:
        return deadline is not None and time.perf_counter() >= deadline

    def family(value: str) -> str:
        chars = tuple(regex.findall(r"\X", value))
        if not chars:
            return "empty"
        text = "".join(chars)
        wide = any(unicodedata.east_asian_width(char) in {"W", "F"} for char in text)
        horizontal = all(char in "_-~=＿￣" for char in text)
        diagonal = any(char in "/\\／＼<>＞ノﾉヽ" for char in text)
        vertical = all(char in "|│lI" for char in text)
        mark = all(char in ".,`'丶、" for char in text)
        if wide and (horizontal or diagonal or len(chars) > 1):
            return "mixed-wide"
        if horizontal:
            return "horizontal"
        if diagonal:
            return "diagonal"
        if vertical:
            return "vertical"
        if mark:
            return "mark"
        return "other"

    def span_options(start: int, end: int) -> tuple[tuple[float, str], ...]:
        if expired():
            return ()
        raw_x0 = int(round(origin + start * base_advance))
        raw_x1 = int(round(origin + end * base_advance))
        x0 = max(0, raw_x0)
        x1 = min(raster.shape[1], raw_x1)
        if x1 <= x0:
            return ()
        crop = raster[:, x0:x1]
        if crop.size == 0 or not crop.any():
            return ()
        span_ys, span_xs = np.where(crop)
        span_width = int(span_xs.max() - span_xs.min() + 1)
        if (
            len(span_xs) <= max(4, int(round(raster.shape[0] * 0.20)))
            and span_width <= 4
            and start > first_unit
            and end < last_unit
        ):
            # Preserve the pixels in component evidence, but do not promote
            # a seam fragment to a punctuation/bar proposal.  The enclosing
            # span owns the opportunity to explain it.
            return ()
        # Wider spans need enough local alternatives to retain a complete
        # mixed-width sequence whose first useful spelling may rank below a
        # fallback diagonal.  Narrow spans stay cheap; all are source-derived.
        local_limit = 256 if end - start >= 3 else 64
        local = _topology_row_variants(
            crop,
            base_advance=base_advance,
            origin=origin - x0,
            font_path=font_path,
            unicode_enabled=unicode_enabled,
            max_variants=local_limit,
            include_fragment_decomposition=False,
        )
        by_text: dict[str, float] = {}
        for cost, raw_text in local:
            text = str(raw_text).strip(" \u3000")
            if not text or text == "?":
                continue
            if not unicode_enabled and any(ord(char) >= 128 for char in text):
                continue
            by_text[text] = min(float(cost), by_text.get(text, float("inf")))
        ys, xs = np.where(crop)
        if len(ys) and len(xs):
            bbox_height = int(ys.max() - ys.min() + 1)
            column_peak = int(crop.sum(axis=0).max())
            bbox_width = int(xs.max() - xs.min() + 1)
            row_peak = int(crop.sum(axis=1).max())
            if (
                end - start >= 2
                and bbox_height <= max(5, int(raster.shape[0] * 0.42))
                and bbox_width >= max(2, int(round(base_advance * 1.20)))
                and row_peak >= max(2, int(round(bbox_width * 0.35)))
            ):
                repeat_count = min(8, end - start)
                by_text.setdefault("_" * repeat_count, 0.04)
                by_text.setdefault("-" * repeat_count, 0.08)
                if unicode_enabled:
                    by_text.setdefault("＿" * repeat_count, 0.06)
                    by_text.setdefault("￣" * repeat_count, 0.10)
            if bbox_height >= max(8, int(raster.shape[0] * 0.50)) and column_peak >= max(6, int(raster.shape[0] * 0.45)):
                for glyph, cost in (("|", 0.34), ("l", 0.36)):
                    if unicode_enabled:
                        by_text.setdefault("│", 0.38)
                    by_text[glyph] = min(cost, by_text.get(glyph, float("inf")))
        if not by_text:
            return ()
        # Retain all low-cost options, plus a deterministic quota from each
        # source family.  This is a span-level diversity rule, not a cap on
        # complete rows; a later DP edge can still combine every retained
        # family with every compatible neighbouring span.
        ordered = sorted(((max(0.0, cost), text) for text, cost in by_text.items()), key=lambda item: (item[0], item[1]))
        buckets: dict[str, list[tuple[float, str]]] = {}
        for item in ordered:
            buckets.setdefault(family(item[1]), []).append(item)
        retain: dict[str, tuple[float, str]] = {}
        for bucket in sorted(buckets):
            for item in buckets[bucket][:16]:
                retain[item[1]] = item
        for item in ordered[:32]:
            retain.setdefault(item[1], item)
        return tuple(sorted(retain.values(), key=lambda item: (item[0], item[1])))

    edges: dict[tuple[int, int], tuple[tuple[float, str], ...]] = {}
    for start in range(first_unit, last_unit):
        if expired():
            return ()
        for end in range(start + 1, min(last_unit, start + 6) + 1):
            options = span_options(start, end)
            if options:
                edges[(start, end)] = options

    if not edges:
        return ()

    def interval_has_ink(start: int, end: int) -> bool:
        x0 = max(0, int(round(origin + start * base_advance)))
        x1 = min(raster.shape[1], int(round(origin + end * base_advance)))
        if x1 <= x0:
            return False
        crop = raster[:, x0:x1]
        if not crop.any():
            return False
        # A measured seam can contain a few antialiased pixels from the
        # neighbouring span.  Keep that evidence in the source component
        # graph, but permit the run lattice to cross it as whitespace when it
        # is demonstrably a tiny edge fragment; otherwise a connected slash
        # would make a real one-unit gap impossible to represent.
        ys, xs = np.where(crop)
        width = int(xs.max() - xs.min() + 1)
        if len(xs) <= max(4, int(round(raster.shape[0] * 0.20))) and width <= 4:
            return False
        return True

    # Each state is (cost, text, span path).  Text-equivalent paths merge at
    # a cursor; the path is retained only as evidence for deterministic tie
    # breaking and later run-level witness extraction.
    states: dict[int, list[tuple[float, str, tuple[tuple[int, int, str], ...]]]] = {
        first_unit: [(0.0, " " * first_unit, ())]
    }
    state_limit = max(512, int(max_variants) * 2)
    # A cursor can skip only one contiguous blank gap before the next
    # substantive span.  Scanning every blank unit for every live state made
    # the old decoder quadratic in the row width; precompute the next owned
    # start once and keep the complete span evidence unchanged.
    next_owned_start: dict[int, tuple[int, ...]] = {}
    for cursor in range(first_unit, last_unit):
        if expired():
            return ()
        if interval_has_ink(cursor, cursor + 1):
            next_owned_start[cursor] = (cursor,)
            continue
        following = next(
            (candidate for candidate in range(cursor + 1, last_unit) if interval_has_ink(candidate, candidate + 1)),
            None,
        )
        next_owned_start[cursor] = (following,) if following is not None else ()
    for cursor in range(first_unit, last_unit):
        if expired():
            return ()
        current = states.get(cursor)
        if not current:
            continue
        for start in next_owned_start.get(cursor, ()):
            gap = " " * max(0, start - cursor)
            for end in range(start + 1, min(last_unit, start + 6) + 1):
                for edge_cost, value in edges.get((start, end), ()):
                    destination = states.setdefault(end, [])
                    for cost, text, path in current:
                        destination.append(
                            (
                                cost + edge_cost + 0.01 * len(gap),
                                text + gap + value,
                                path + ((start, end, value),),
                            )
                        )
        for destination in range(cursor + 1, min(last_unit, cursor + 6) + 1):
            values = states.get(destination)
            if not values:
                continue
            dedup: dict[str, tuple[float, str, tuple[tuple[int, int, str], ...]]] = {}
            for value in values:
                prior = dedup.get(value[1])
                if prior is None or (value[0], value[2]) < (prior[0], prior[2]):
                    dedup[value[1]] = value
            values = sorted(dedup.values(), key=lambda item: (item[0], item[1], item[2]))
            states[destination] = values[:state_limit]

    finals = list(states.get(last_unit, ()))
    if not finals:
        return ()

    # Preserve a witness for each complete multi-unit source span.  If a
    # useful kana/structural sequence ranks below the ordinary top-k paths,
    # its measured span still appears in the proposal surface.  Prefix and
    # suffix are the best source-only paths around that span; no transcript is
    # consulted.
    best_prefix: dict[int, tuple[float, str]] = {first_unit: (0.0, " " * first_unit)}
    for cursor in range(first_unit, last_unit + 1):
        if expired():
            return ()
        prefix = best_prefix.get(cursor)
        if prefix is None:
            continue
        for start in range(cursor, last_unit):
            if start > cursor and interval_has_ink(cursor, start):
                break
            gap = " " * max(0, start - cursor)
            for end in range(start + 1, min(last_unit, start + 6) + 1):
                options = edges.get((start, end), ())
                if not options:
                    continue
                edge = min(options, key=lambda item: (item[0], item[1]))
                candidate = (prefix[0] + edge[0] + 0.01 * len(gap), prefix[1] + gap + edge[1])
                prior = best_prefix.get(end)
                if prior is None or candidate < prior:
                    best_prefix[end] = candidate

    best_suffix: dict[int, tuple[float, str]] = {last_unit: (0.0, "")}
    for cursor in range(last_unit - 1, first_unit - 1, -1):
        if expired():
            return ()
        candidates: list[tuple[float, str]] = []
        for start in range(cursor, last_unit):
            if start > cursor and interval_has_ink(cursor, start):
                break
            gap = " " * max(0, start - cursor)
            for end in range(start + 1, min(last_unit, start + 6) + 1):
                suffix = best_suffix.get(end)
                if suffix is None:
                    continue
                for edge_cost, value in edges.get((start, end), ()):
                    candidates.append(
                        (
                            edge_cost + suffix[0] + 0.01 * len(gap),
                            gap + value + suffix[1],
                        )
                    )
        if candidates:
            best_suffix[cursor] = min(candidates, key=lambda item: (item[0], item[1]))

    rendered_cost_cache: dict[str, float] = {}

    def rendered_cost(text: str) -> float:
        """Score a complete span spelling against the same run raster.

        Span topology proposes the logical sequence; this second pass keeps
        a terminal edge (for example ``)``) from losing to a spill-like ``|``
        merely because its isolated local cost was negative.  It is a
        source-raster comparison, never a transcript or font-selection
        authority.
        """

        cached_cost = rendered_cost_cache.get(text)
        if cached_cost is not None:
            return cached_cost
        if expired():
            return float("inf")
        cursor = 0
        total = 0.0
        for grapheme in regex.findall(r"\X", text):
            if grapheme.isspace():
                cursor += max(1, wcwidth.wcswidth(grapheme))
                continue
            units = max(1, wcwidth.wcswidth(grapheme))
            x0 = max(0, int(round(origin + cursor * base_advance)))
            x1 = min(raster.shape[1], int(round(origin + (cursor + units) * base_advance)))
            if x1 <= x0:
                total += 1.0
                cursor += units
                continue
            crop = raster[:, x0:x1]
            template = _structural_template(
                font_path,
                grapheme,
                units,
                max(1, round(base_advance)),
                raster.shape[0],
            )
            total += _structural_shape_score(crop, template)
            total += _source_topology_bonus(grapheme, crop, base_advance=base_advance)
            total += _glyph_position_penalty(grapheme, crop)
            total += _structural_glyph_penalty(grapheme, crop)
            cursor += units
        rendered_cost_cache[text] = float(total)
        return float(total)

    ordered = sorted(
        finals,
        key=lambda item: (
            max(0.0, float(item[0])) + 2.0 * rendered_cost(item[1]),
            item[1],
            item[2],
        ),
    )
    result: list[tuple[str, float]] = [
        (
            text.rstrip(" \u3000"),
            max(0.0, float(cost)) + 2.0 * rendered_cost(text),
        )
        for cost, text, _path in ordered
    ]
    # A raster-derived morphology witness covers a common structural case
    # that no isolated template can own: a tall bar, seam fragments, and two
    # lower-band horizontals in one connected outline.  It is deliberately
    # grammar-level (projection/height/band only), never tied to a reference
    # row or an expected transcript.
    morphology_units: list[str] = []
    for unit in range(first_unit, last_unit):
        if expired():
            return ()
        x0 = max(0, int(round(origin + unit * base_advance)))
        x1 = min(raster.shape[1], int(round(origin + (unit + 1) * base_advance)))
        crop = raster[:, x0:x1]
        if crop.size == 0 or not crop.any():
            morphology_units.append(" ")
            continue
        ys, xs = np.where(crop)
        height = int(ys.max() - ys.min() + 1)
        width = int(xs.max() - xs.min() + 1)
        row_peak = int(crop.sum(axis=1).max())
        col_peak = int(crop.sum(axis=0).max())
        if len(xs) <= max(4, int(round(raster.shape[0] * 0.20))) and width <= 4:
            morphology_units.append(" ")
        elif height >= max(8, int(raster.shape[0] * 0.50)) and col_peak >= max(6, int(raster.shape[0] * 0.45)):
            morphology_units.append("|")
        elif (
            height <= max(5, int(raster.shape[0] * 0.42))
            and width >= 2
            and row_peak >= max(2, int(round(width * 0.35)))
            and float(np.mean(ys)) >= raster.shape[0] * 0.45
        ):
            morphology_units.append("_")
        else:
            morphology_units.append(" ")
    morphology_text = (" " * first_unit + "".join(morphology_units)).rstrip()
    if morphology_text and any(char != " " for char in morphology_text):
        result.append((morphology_text, 0.50))
    witness_values: dict[str, float] = {}
    for (start, end), options in edges.items():
        if expired():
            return ()
        prefix = best_prefix.get(start)
        suffix = best_suffix.get(end)
        if prefix is None or suffix is None:
            continue
        for edge_cost, value in options:
            if end - start < 2 and len(regex.findall(r"\X", value)) < 2:
                continue
            if not (
                any(unicodedata.east_asian_width(char) in {"W", "F"} for char in value)
                and any(char in "xX_＿-￣/\\／＼|│<>＞ノﾉヽ`'" for char in value)
            ):
                continue
            witness = (prefix[1] + value + suffix[1]).rstrip(" \u3000")
            witness_values[witness] = min(
                witness_values.get(witness, float("inf")),
                float(prefix[0] + edge_cost + suffix[0]),
            )
    protected_witnesses = [
        (text, cost)
        for text, cost in sorted(witness_values.items(), key=lambda item: (item[1], item[0]))
        if text
    ]
    for text, cost in protected_witnesses:
        if all(existing[0] != text for existing in result):
            result.append((text, cost))

    unique: list[tuple[str, float]] = []
    seen: set[str] = set()
    # Protected span witnesses are emitted before the ordinary k-best paths;
    # otherwise a broad fallback surface can fill the public cap before a
    # complete lower-ranked mixed-width span is serialized.
    ordered_result = [*protected_witnesses, *sorted(result, key=lambda item: (item[1], item[0]))]
    for text, cost in ordered_result:
        if expired():
            return tuple(unique)
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append((text, cost))
        if len(unique) >= max(1, int(max_variants)):
            break
    return tuple(unique)


def _cluster_sequence(
    raster: np.ndarray,
    *,
    base_advance: float,
    origin: float,
    font_path: str,
    beam_width: int,
) -> tuple[str, float] | None:
    """Compatibility wrapper returning the best cluster-sequence proposal."""

    sequences = _cluster_sequences(
        raster,
        base_advance=base_advance,
        origin=origin,
        font_path=font_path,
        beam_width=beam_width,
    )
    return sequences[0] if sequences else None


@dataclass(frozen=True)
class StructuralUnicodeRowAdapter:
    """Deterministic proposal adapter for structural punctuation and Japanese rows."""

    name: str = "structural-unicode-row"
    version: str = "2-run-level-span-lattice"
    supported_scripts: tuple[str, ...] = ("ascii", "japanese", "cjk")
    # A 16-state row beam is still bounded, but preserves mixed-script
    # decompositions that require a few lower-ranked punctuation choices
    # before a later Japanese/fullwidth run disambiguates ownership.
    beam_width: int = 16

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        font_path = _structural_font_path()
        return CapabilityProfile(
            adapter=self.name,
            adapter_version=self.version,
            supported_scripts=self.supported_scripts if font_path else (),
            supported_directions=("ltr",),
            grapheme_coverage=("structural-punctuation", "kana-katakana-proposals") if font_path else (),
            runtime_hashes={"template_font": _structural_font_hash(font_path)} if font_path else {},
            runtime_versions={"pillow": PIL.__version__},
            license="Apache-2.0",
            offline=True,
            runtime_network=False,
            tested_fixture_families=("fixed_ascii", "mixed_width_japanese_structural"),
            unsupported_cases=("ambiguous_unicode_collision", "arabic_joining", "emoji_zwj"),
            status="proposal_only" if font_path else "unavailable",
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        # This adapter consumes a geometry-owned complete run mask.  It does
        # not own routing, so a shaped-run decision is equally valid input;
        # rejecting it here made the run-level recognizer disappear whenever
        # the geometry receipt selected the proportional branch.
        if geometry.get("mode") not in {"fixed_lattice", "shaped_runs", "unresolved"}:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_mode_mismatch")
        mask = _run_mask(geometry)
        font_path = _structural_font_path()
        if mask is None or font_path is None:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "structural_row_input_unavailable")
        source_hash, geometry_hash, components_hash = _source_hashes(source)
        run_evidence = geometry.get("run_mask")
        run_context_hash = sha256_bytes(
            canonical_bytes(
                {
                    "pixels": run_evidence.get("pixels") if isinstance(run_evidence, Mapping) else None,
                    "rgba": run_evidence.get("rgba") if isinstance(run_evidence, Mapping) else None,
                    "measured_advances": run_evidence.get("measured_advances") if isinstance(run_evidence, Mapping) else None,
                    "anchor_evidence": run_evidence.get("anchor_evidence") if isinstance(run_evidence, Mapping) else None,
                    "source_bounds": run_evidence.get("source_bounds") if isinstance(run_evidence, Mapping) else None,
                    "component_ids": run_evidence.get("component_ids") if isinstance(run_evidence, Mapping) else source.get("component_ids", ()),
                }
            )
        )
        cache_key = (
            self.name,
            self.version,
            str(self.beam_width),
            source_hash,
            geometry_hash,
            components_hash,
            environment_lock.output_hash,
            run_context_hash,
        )
        cached = _PROPOSAL_CACHE.get(cache_key)
        if cached is not None:
            return cached
        raster = np.asarray(mask, dtype=bool)
        mixed = geometry.get("mixed_width_display") or {}
        run_geometry = geometry.get("run_mask")
        run_anchor = run_geometry.get("anchor_evidence") if isinstance(run_geometry, Mapping) else None
        if not isinstance(run_anchor, Mapping) or not run_anchor:
            run_anchor = source.get("anchor_evidence") if isinstance(source.get("anchor_evidence"), Mapping) else {}
        # Recognition receives the same local anchor record that the builder
        # hashes into the run strip.  Aggregate projection evidence is a
        # fallback for legacy callers only; it must not override a rebased
        # origin or per-run advance supplied by the geometry owner.
        base = float(
            run_anchor.get("base_advance_px", mixed.get("base_advance_px", 13.0))
        )
        origin = float(run_anchor.get("origin_px", mixed.get("origin_px", 0.0)))
        if geometry.get("mode") == "shaped_runs":
            color_stats = source.get("run_color_stats") if isinstance(source.get("run_color_stats"), Mapping) else {}
            pixel_count = max(1, int(color_stats.get("pixel_count", 0) or 0))
            strongly_colored = int(color_stats.get("strongly_colored_pixels", 0) or 0)
            if strongly_colored / pixel_count > 0.05:
                return _unsupported_proposal(self.name, self.version, source, environment_lock, "emoji_modality_not_evidenced")
            if base < 3.0:
                return _unsupported_proposal(self.name, self.version, source, environment_lock, "structural_display_basis_unresolved")
        width = raster.shape[1]
        # Do not serialize a clipped partial unit at the left canvas edge.
        # The raster strip retains it for evidence, but logical text starts at
        # the first complete display unit so glyph columns do not shift left.
        # The beam is serialized from logical column zero.  Physical clipping
        # at a negative origin is handled by the crop bounds below; it must
        # not erase leading spaces from the recovered text.
        first_col = 0
        occupied_x = np.where(raster.any(axis=0))[0]
        last_col = (
            int(np.ceil((int(occupied_x.max()) + 1 - origin) / base))
            if len(occupied_x)
            else first_col
        )
        # The environment lock is the capability boundary for this adapter.
        # A mixed-width geometry record is evidence that Unicode alternatives
        # may be useful; it is not permission to invent them when the pinned
        # run was requested with an ASCII-only script pack.  In that case,
        # keep the structural alphabet ASCII so a fullwidth lookalike such as
        # ``＿`` cannot outrank the literal ``_`` on an ASCII fixture.  The
        # Unicode-capable path retains those alternatives below as proposals.
        unicode_packs = {"japanese", "jpn", "cjk", "unicode"}
        unicode_enabled = bool(unicode_packs.intersection(environment_lock.script_packs))
        structural_budget = source.get("structural_run_budget_seconds")
        structural_deadline = None
        if structural_budget is not None:
            try:
                structural_budget_seconds = float(structural_budget)
            except (TypeError, ValueError):
                structural_budget_seconds = 0.0
            if structural_budget_seconds <= 0:
                return _unsupported_proposal(self.name, self.version, source, environment_lock, "run_level_budget_invalid")
            structural_deadline = time.perf_counter() + structural_budget_seconds

        # Transfer proposal ownership to the run lattice.  The legacy cell
        # beam below is intentionally unreachable for live proposals: it is
        # retained in the file only as historical diagnostic code and direct
        # regression helpers.  A run-level edge is built from source pixels,
        # measured unit seams, and complete span topology, so no connected
        # component is allowed to author a grapheme by itself.
        run_level_variants = _run_level_variants(
            raster,
            base_advance=base,
            origin=origin,
            font_path=font_path,
            unicode_enabled=unicode_enabled,
            max_variants=max(128, min(1024, self.beam_width * 64)),
            deadline=structural_deadline,
        )
        if not run_level_variants:
            reason = (
                "run_level_budget_exceeded"
                if structural_deadline is not None and time.perf_counter() >= structural_deadline
                else "run_level_segmentation_no_path"
            )
            return _unsupported_proposal(
                self.name,
                self.version,
                source,
                environment_lock,
                reason,
            )
        run_level_candidates: list[GraphemeCandidate] = []
        run_component_ids = tuple(
            str(value)
            for value in (
                (run_geometry.get("component_ids", ()) if isinstance(run_geometry, Mapping) else ())
                or source.get("component_ids", ())
            )
        )
        run_level_alternatives = tuple(text for text, _cost in run_level_variants[1:65])
        for variant_index, (variant_text, variant_cost) in enumerate(run_level_variants):
            run_level_candidates.append(
                _candidate(
                    text=variant_text,
                    source_hash=source_hash,
                    geometry_hash=geometry_hash,
                    components_hash=components_hash,
                    environment_hash=environment_lock.output_hash,
                    confidence=max(0.0, min(1.0, 1.0 - float(variant_cost) / max(1.0, last_col * 0.75))),
                    component_ids=run_component_ids,
                    alternatives=run_level_alternatives if variant_index == 0 else (),
                    run_id=str(source.get("run_id", "row-0")),
                    extra_input_hashes={
                        "template_font": _structural_font_hash(font_path),
                        "proposal_mode": sha256_bytes(b"run-level-span-lattice-v1"),
                        "proposal_rank": sha256_bytes(str(variant_index).encode("ascii")),
                    },
                )
            )
        proposal = RecognitionProposal(
            proposal_id=f"{self.name}-run-lattice",
            adapter=self.name,
            adapter_version=self.version,
            model_hashes=environment_lock.model_hashes,
            candidates=tuple(run_level_candidates),
            run_id=str(source.get("run_id", "row-0")),
            input_hashes={"source": source_hash, "geometry": geometry_hash, "components": components_hash, "environment": environment_lock.output_hash},
            status="proposal",
        )
        proposal_set = ProposalSet(
            adapter=self.name,
            adapter_version=self.version,
            environment_lock_hash=environment_lock.output_hash,
            proposals=(proposal,),
            supported_scripts=self.supported_scripts,
            status="proposal_only",
        )
        if len(_PROPOSAL_CACHE) >= _PROPOSAL_CACHE_LIMIT:
            _PROPOSAL_CACHE.pop(next(iter(_PROPOSAL_CACHE)))
        _PROPOSAL_CACHE[cache_key] = proposal_set
        return proposal_set


def _unicode_template_font_path() -> str | None:
    """Return the default Latin template face; callers still hash-bind it."""

    candidates = (
        "/Library/Fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    return next((path for path in candidates if Path(path).is_file()), None)


def _unicode_repertoire(name: str) -> tuple[str, ...]:
    """Build a deterministic repertoire without reading fixture truth."""

    if name == "latin":
        values = [" "] + [chr(value) for value in range(0x21, 0x7F)]
        values.extend(chr(value) for value in range(0xA0, 0x100))
    elif name == "combining":
        bases = [chr(value) for value in range(ord("A"), ord("Z") + 1)]
        bases.extend(chr(value) for value in range(ord("a"), ord("z") + 1))
        values = [" "] + bases
        marks = tuple(chr(value) for value in range(0x300, 0x370))
        values.extend(base + mark for base in bases for mark in marks if unicodedata.normalize("NFC", base + mark) != base + mark)
    elif name == "kana":
        values = [" "]
        values.extend(chr(value) for value in range(0x3040, 0x30A0))
        values.extend(chr(value) for value in range(0x30A0, 0x3100))
        values.extend(chr(value) for value in range(0xFF61, 0xFFA0))
    else:
        values = []
    return tuple(dict.fromkeys(values))


@lru_cache(maxsize=2048)
def _render_unicode_template(
    font_path: str,
    grapheme: str,
    cell_width: int,
    target_height: int,
) -> tuple[tuple[bool, ...], ...] | None:
    """Render one complete grapheme into a measured run cell."""

    try:
        font_size = max(8, min(96, int(round(target_height * 1.05))))
        font = ImageFont.truetype(font_path, font_size)
        bbox = font.getbbox(grapheme)
        if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            return None
        image = Image.new("L", (max(1, int(cell_width)), max(1, int(target_height))), 0)
        glyph_width = bbox[2] - bbox[0]
        glyph_height = bbox[3] - bbox[1]
        x = (image.width - glyph_width) // 2 - bbox[0]
        y = (image.height - glyph_height) // 2 - bbox[1]
        ImageDraw.Draw(image).text((x, y), grapheme, font=font, fill=255)
        return tuple(tuple(bool(value) for value in row) for row in (np.asarray(image) > 32))
    except (OSError, ValueError, TypeError):
        return None


def _unicode_template_residual(target: np.ndarray, template: tuple[tuple[bool, ...], ...] | None) -> tuple[float, int, int]:
    if template is None:
        return 1.0, 0, int(target.sum())
    rendered = np.asarray(template, dtype=bool)
    if rendered.shape != target.shape:
        return 1.0, 0, int(target.sum())
    xor = int(np.count_nonzero(target ^ rendered))
    union = int(np.count_nonzero(target | rendered))
    return float(xor / max(1, union)), union, int(rendered.sum())


def _unicode_run_sequences(
    raster: np.ndarray,
    *,
    base_advance: float,
    font_path: str,
    repertoire: tuple[str, ...],
    beam_width: int,
    max_candidates: int,
) -> tuple[dict[str, Any], ...]:
    """Decode a run with bounded dynamic programming over grapheme spans."""

    if raster.ndim != 2 or raster.shape[1] <= 0 or base_advance <= 0:
        return ()
    height, width = raster.shape
    unit_count = max(1, int(round(width / base_advance)))
    # Keep only renderable, positive-width graphemes.  The repertoire itself is
    # static/configured evidence; no source transcript is consulted here.
    glyphs: list[tuple[str, int]] = [(" ", 1)]
    for grapheme in repertoire:
        units = wcwidth.wcswidth(grapheme)
        if units > 0 and grapheme != " ":
            glyphs.append((grapheme, int(units)))
    glyphs = list(dict.fromkeys(glyphs))
    templates: dict[tuple[str, int], tuple[tuple[bool, ...], ...] | None] = {}
    for grapheme, units in glyphs:
        cell_width = max(1, int(round(base_advance * units)))
        templates[(grapheme, units)] = _render_unicode_template(font_path, grapheme, cell_width, height)

    states: dict[int, list[tuple[float, str, tuple[dict[str, Any], ...]]]] = {0: [(0.0, "", ())]}
    for cursor_units in range(unit_count):
        current = states.get(cursor_units, ())
        if not current:
            continue
        cursor_px = int(round(cursor_units * base_advance))
        for cost, text, evidence in current:
            for grapheme, units in glyphs:
                end_units = cursor_units + units
                if end_units > unit_count:
                    continue
                end_px = min(width, max(cursor_px + 1, int(round(end_units * base_advance))))
                crop = raster[:, cursor_px:end_px]
                residual, union, rendered_pixels = _unicode_template_residual(crop, templates[(grapheme, units)])
                span = {
                    "grapheme": grapheme,
                    "start_unit": cursor_units,
                    "end_unit": end_units,
                    "residual_fraction": residual,
                    "union_pixels": union,
                    "rendered_pixels": rendered_pixels,
                }
                states.setdefault(end_units, []).append((cost + residual, text + grapheme, (*evidence, span)))
        for end_units in range(cursor_units + 1, min(unit_count, cursor_units + 2) + 1):
            if end_units in states:
                states[end_units] = sorted(states[end_units], key=lambda item: (item[0], item[1]))[: max(1, beam_width)]
    finals = states.get(unit_count, ())
    if not finals:
        # Permit a clipped final cell, but never invent a trailing glyph.
        finals = [item for key, values in states.items() if key >= unit_count - 1 for item in values]
    ordered = sorted(finals, key=lambda item: (item[0], item[1]))
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cost, text, evidence in ordered:
        if text in seen:
            continue
        seen.add(text)
        result.append({"text": text, "score": float(cost / max(1, len(evidence))), "spans": list(evidence)})
        if len(result) >= max(1, max_candidates):
            break
    return tuple(result)


@dataclass(frozen=True)
class UnicodeTemplateRunAdapter:
    """Pinned, source-only Unicode proposal adapter.

    This adapter is deliberately proposal-only.  It renders a configured
    script repertoire against each geometry-owned run, retains bounded
    sequence alternatives, and records residual/collision/margin evidence.
    It cannot authorize a candidate or provide coverage for a script whose
    font/repertoire/shaping assets are not hash-pinned in the environment lock.
    """

    repertoire_name: str = "latin"
    name: str = "unicode-template-latin"
    version: str = "1-template-dp"
    font_path: str | None = None
    font_license: str = "Bitstream Vera / DejaVu license"
    repertoire_path: str | None = None
    beam_width: int = 8
    top_k: int = 8
    max_residual: float = 0.92
    min_margin: float = 0.01

    @property
    def supported_scripts(self) -> tuple[str, ...]:
        return {
            "latin": ("latin",),
            "combining": ("latin", "combining_marks"),
            "kana": ("japanese",),
            "arabic": ("arabic",),
            "cjk": ("cjk",),
        }.get(self.repertoire_name, ())

    def _font(self) -> str | None:
        return self.font_path or _unicode_template_font_path()

    def _font_key(self) -> str:
        return f"{self.name}.font"

    def _repertoire_key(self) -> str:
        return f"{self.name}.repertoire"

    def _repertoire(self) -> tuple[str, ...] | None:
        if self.repertoire_path:
            path = Path(self.repertoire_path)
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                values = payload.get("graphemes", payload) if isinstance(payload, Mapping) else payload
                if not isinstance(values, (list, tuple)):
                    return None
                return tuple(dict.fromkeys(str(value) for value in values if str(value)))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return None
        if self.repertoire_name == "cjk":
            return None
        if self.repertoire_name == "arabic":
            return None
        return _unicode_repertoire(self.repertoire_name)

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        font = self._font()
        repertoire = self._repertoire()
        model_hashes: dict[str, str] = {}
        status = "available"
        unsupported: list[str] = ["visual_unicode_collision", "partial_cluster"]
        if not font or not Path(font).is_file():
            status = "unavailable"
            unsupported.append("template_font_missing")
        else:
            font_hash = sha256_file(font)
            model_hashes[self._font_key()] = font_hash
            if environment_lock.model_hashes.get(self._font_key()) != font_hash:
                status = "unavailable"
                unsupported.append("template_font_unpinned")
        if repertoire is None:
            status = "unavailable"
            unsupported.append("repertoire_unpinned")
        elif self.repertoire_path:
            repertoire_hash = sha256_file(self.repertoire_path)
            model_hashes[self._repertoire_key()] = repertoire_hash
            if environment_lock.model_hashes.get(self._repertoire_key()) != repertoire_hash:
                status = "unavailable"
                unsupported.append("repertoire_hash_unpinned")
        if self.repertoire_name == "arabic":
            status = "unavailable"
            unsupported.append("shaping_profile_missing")
        return CapabilityProfile(
            adapter=self.name,
            adapter_version=self.version,
            supported_scripts=self.supported_scripts if status == "available" else (),
            supported_directions=("ltr",),
            grapheme_coverage=("extended-grapheme-cluster", "run-level-span-dp") if status == "available" else (),
            model_hashes=model_hashes,
            runtime_versions={"pillow": PIL.__version__, "unicode": unicodedata.unidata_version},
            license=self.font_license,
            offline=True,
            runtime_network=False,
            tested_fixture_families=(self.repertoire_name,),
            unsupported_cases=tuple(unsupported),
            status=status,
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        profile = self.capability_profile(environment_lock)
        if profile.status != "available":
            blocker_order = (
                "template_font_missing",
                "template_font_unpinned",
                "repertoire_unpinned",
                "repertoire_hash_unpinned",
                "shaping_profile_missing",
                "geometry_run_mask_missing",
            )
            reason = next((item for item in blocker_order if item in profile.unsupported_cases), profile.unsupported_cases[0])
            return _unsupported_proposal(self.name, self.version, source, environment_lock, reason)
        evidence = geometry.get("run_mask")
        if not isinstance(evidence, Mapping) or evidence.get("authority") not in {"geometry_proven_run", "geometry_hypothesis_run"}:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_run_mask_missing")
        raster_values = _mask_from_pixels(evidence.get("pixels"))
        if raster_values is None:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_run_mask_invalid")
        raster = np.asarray(raster_values, dtype=bool)
        anchor = evidence.get("anchor_evidence") if isinstance(evidence.get("anchor_evidence"), Mapping) else {}
        mixed = geometry.get("mixed_width_display") if isinstance(geometry.get("mixed_width_display"), Mapping) else {}
        base = float(anchor.get("base_advance_px", evidence.get("measured_advances", [0])[0] if evidence.get("measured_advances") else mixed.get("base_advance_px", 0.0)))
        if base <= 0:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "measured_advance_missing")
        color_stats = source.get("run_color_stats")
        if isinstance(color_stats, Mapping):
            pixel_count = max(1, int(color_stats.get("pixel_count", 0) or 0))
            strongly_colored = int(color_stats.get("strongly_colored_pixels", 0) or 0)
            if strongly_colored / pixel_count > 0.05:
                return _unsupported_proposal(self.name, self.version, source, environment_lock, "emoji_modality_not_evidenced")
        font = self._font()
        repertoire = self._repertoire() or ()
        source_hash, geometry_hash, components_hash = _source_hashes(source)
        run_hash = _mask_hash(tuple(tuple(bool(value) for value in row) for row in raster.tolist()))
        cache_key = (
            "unicode-template",
            self.name,
            self.version,
            str(self.beam_width),
            str(self.top_k),
            source_hash,
            geometry_hash,
            components_hash,
            environment_lock.output_hash,
            sha256_file(str(font)),
            run_hash,
            str(base),
        )
        cached = _PROPOSAL_CACHE.get(cache_key)
        if cached is not None:
            return cached
        sequences = _unicode_run_sequences(raster, base_advance=base, font_path=str(font), repertoire=repertoire, beam_width=self.beam_width, max_candidates=self.top_k)
        if not sequences:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "run_sequence_unresolved")
        component_ids = tuple(str(value) for value in (evidence.get("component_ids", ()) or source.get("component_ids", ())))
        best = sequences[0]
        runner = sequences[1] if len(sequences) > 1 else None
        residual = float(best["score"])
        margin = float(runner["score"] - residual) if runner else 1.0
        visual_collision = bool(runner and runner["score"] == residual and runner["text"] != best["text"])
        rejection_reasons: list[str] = []
        if residual > self.max_residual:
            rejection_reasons.append("template_residual_excessive")
        if margin < self.min_margin:
            rejection_reasons.append("candidate_margin_insufficient")
        if visual_collision:
            rejection_reasons.append("unicode_visual_collision")
        candidates = tuple(
            _candidate(
                text=item["text"],
                source_hash=source_hash,
                geometry_hash=geometry_hash,
                components_hash=components_hash,
                environment_hash=environment_lock.output_hash,
                confidence=max(0.0, min(1.0, 1.0 - float(item["score"]))),
                component_ids=component_ids,
                run_id=str(evidence.get("run_id", source.get("run_id", "run-0"))),
                alternatives=tuple(other["text"] for other in sequences if other["text"] != item["text"]),
                extra_input_hashes={self._font_key(): sha256_file(str(font)), "run_mask": run_hash},
            )
            for item in sequences
        )
        proposal = RecognitionProposal(
            proposal_id=f"{self.name}-run-dp",
            adapter=self.name,
            adapter_version=self.version,
            model_hashes={**dict(environment_lock.model_hashes), self._font_key(): sha256_file(str(font))},
            candidates=candidates,
            run_id=str(evidence.get("run_id", source.get("run_id", "run-0"))),
            input_hashes={"source": source_hash, "geometry": geometry_hash, "components": components_hash, "environment": environment_lock.output_hash, "run_mask": run_hash},
            configuration={"repertoire": self.repertoire_name, "beam_width": self.beam_width, "top_k": self.top_k, "max_residual": self.max_residual, "min_margin": self.min_margin},
            provenance={"source_only": True, "residual_evidence": list(sequences), "ground_truth_input": False},
            status="proposal",
            rejection_reasons=tuple(rejection_reasons),
        )
        proposal_set = ProposalSet(
            adapter=self.name,
            adapter_version=self.version,
            environment_lock_hash=environment_lock.output_hash,
            proposals=(proposal,),
            supported_scripts=self.supported_scripts,
            status="proposal_only",
            rejection_codes=tuple(rejection_reasons),
        )
        if len(_PROPOSAL_CACHE) >= _PROPOSAL_CACHE_LIMIT:
            _PROPOSAL_CACHE.pop(next(iter(_PROPOSAL_CACHE)))
        _PROPOSAL_CACHE[cache_key] = proposal_set
        return proposal_set


@dataclass(frozen=True)
class PaddleOCROfflineAdapter:
    """Optional PaddleOCR proposal source; never installs or downloads at runtime."""

    name: str = "paddleocr-offline"
    version: str = "unavailable"
    supported_scripts: tuple[str, ...] = ("latin", "cjk", "japanese")
    model_hashes: Mapping[str, str] = field(default_factory=dict)

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        try:
            import paddleocr  # type: ignore[import-not-found]
            version = str(getattr(paddleocr, "__version__", self.version))
            status = "proposal_only"
        except ImportError:
            version = self.version
            status = "unavailable"
        return CapabilityProfile(
            adapter=self.name,
            adapter_version=version,
            supported_scripts=self.supported_scripts if status != "unavailable" else (),
            supported_directions=("ltr", "rtl"),
            grapheme_coverage=("whole-run",) if status != "unavailable" else (),
            model_hashes=self.model_hashes,
            runtime_versions={"paddleocr": version},
            license="Apache-2.0",
            offline=True,
            runtime_network=False,
            tested_fixture_families=(),
            unsupported_cases=("arabic_model_not_verified", "emoji_zwj", "visual_unicode_collision"),
            status=status,
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        profile = self.capability_profile(environment_lock)
        reason = "recognizer_unavailable" if profile.status == "unavailable" else "model_not_pinned"
        return _unsupported_proposal(self.name, profile.adapter_version, source, environment_lock, reason)


@dataclass(frozen=True)
class IndependentOfflineAdapter:
    """EasyOCR/Surya comparator profile with a hard offline boundary."""

    backend: str = "easyocr"
    version: str = "unavailable"
    name: str = "independent-offline"
    supported_scripts: tuple[str, ...] = ("latin", "cjk", "arabic")

    def _module(self) -> str:
        return "easyocr" if self.backend == "easyocr" else "surya"

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        try:
            module = __import__(self._module())
            version = str(getattr(module, "__version__", self.version))
            status = "proposal_only"
        except ImportError:
            version = self.version
            status = "unavailable"
        # ``name`` is the persisted adapter identity.  The historical default
        # remains ``independent-offline`` and receives a backend suffix, while
        # benchmark callers may provide an already-qualified identity so two
        # comparator backends cannot collapse into one profile record.
        adapter_name = self.name if self.name.endswith(f"-{self.backend}") else f"{self.name}-{self.backend}"
        return CapabilityProfile(
            adapter=adapter_name,
            adapter_version=version,
            supported_scripts=self.supported_scripts if status != "unavailable" else (),
            supported_directions=("ltr", "rtl"),
            grapheme_coverage=("whole-run",) if status != "unavailable" else (),
            runtime_versions={self.backend: version},
            license="Apache-2.0" if self.backend == "easyocr" else "GPL-3.0",
            offline=True,
            runtime_network=False,
            unsupported_cases=("emoji_zwj", "visual_unicode_collision", "unverified_script_pack"),
            status=status,
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        profile = self.capability_profile(environment_lock)
        reason = "recognizer_unavailable" if profile.status == "unavailable" else "model_not_pinned"
        return _unsupported_proposal(profile.adapter, profile.adapter_version, source, environment_lock, reason)


def _emoji_sequences(path: str | os.PathLike[str]) -> tuple[str, ...]:
    """Read only fully-qualified RGI sequences from pinned UTS #51 data."""

    values: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "; fully-qualified" not in line or "#" not in line:
            continue
        codepoints = line.split(";", 1)[0].strip().split()
        try:
            sequence = "".join(chr(int(codepoint, 16)) for codepoint in codepoints)
        except ValueError:
            continue
        if len(regex.findall(r"\X", sequence)) == 1:
            values.append(sequence)
    return tuple(dict.fromkeys(values))


def _mask_from_pixels(pixels: Any) -> tuple[tuple[bool, ...], ...] | None:
    if not isinstance(pixels, (list, tuple)) or not pixels:
        return None
    rows: list[tuple[bool, ...]] = []
    width: int | None = None
    for row in pixels:
        if isinstance(row, str):
            values = tuple(char not in {"0", ".", " "} for char in row)
        elif isinstance(row, (list, tuple)):
            values = tuple(bool(value) for value in row)
        else:
            return None
        if width is None:
            width = len(values)
        if len(values) != width:
            return None
        rows.append(values)
    return tuple(rows) if rows and width else None


def _run_mask(geometry: Mapping[str, Any]) -> tuple[tuple[bool, ...], ...] | None:
    """Accept only an explicitly geometry-owned run mask, never a sequence hint."""

    evidence = geometry.get("run_mask")
    if not isinstance(evidence, Mapping):
        return None
    if evidence.get("authority") not in {"geometry_proven_run", "geometry_hypothesis_run"}:
        return None
    if evidence.get("grapheme_complete") is False:
        return None
    return _mask_from_pixels(evidence.get("pixels"))


def _run_rgba(geometry: Mapping[str, Any]) -> tuple[tuple[tuple[int, int, int, int], ...], ...] | None:
    evidence = geometry.get("run_mask")
    if not isinstance(evidence, Mapping) or evidence.get("authority") != "geometry_proven_run":
        return None
    pixels = evidence.get("rgba")
    if not isinstance(pixels, (list, tuple)) or not pixels:
        return None
    rows: list[tuple[tuple[int, int, int, int], ...]] = []
    width: int | None = None
    for row in pixels:
        if not isinstance(row, (list, tuple)):
            return None
        values: list[tuple[int, int, int, int]] = []
        for value in row:
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                return None
            try:
                values.append(tuple(max(0, min(255, int(channel))) for channel in value))
            except (TypeError, ValueError):
                return None
        if width is None:
            width = len(values)
        if len(values) != width:
            return None
        rows.append(tuple(values))
    return tuple(rows) if rows and width else None


def _mask_hash(mask: tuple[tuple[bool, ...], ...]) -> str:
    return sha256_bytes(canonical_bytes([[int(value) for value in row] for row in mask]))


def _rgba_hash(pixels: tuple[tuple[tuple[int, int, int, int], ...], ...]) -> str:
    return sha256_bytes(canonical_bytes(pixels))


def _render_emoji_mask(font: ImageFont.FreeTypeFont, sequence: str) -> tuple[tuple[bool, ...], ...] | None:
    """Shape one complete cluster through the pinned color-font GSUB/CBDT path."""

    try:
        glyph_mask = font.getmask(sequence)
        advance = max(1, int(round(font.getlength(sequence))))
    except (OSError, ValueError):
        return None
    # FreeType's shaped color-font mask is already deterministic and avoids a
    # second compositor/rasterizer in the recognition path.
    alpha = Image.frombytes("L", glyph_mask.size, bytes(glyph_mask))
    bounds = alpha.getbbox()
    if bounds is None:
        return None
    alpha = alpha.crop(bounds)
    raw = alpha.tobytes()
    return tuple(
        tuple(value > 8 for value in raw[row * alpha.width : (row + 1) * alpha.width])
        for row in range(alpha.height)
    )


def _render_emoji_image(font: ImageFont.FreeTypeFont, sequence: str) -> Image.Image | None:
    try:
        bbox = font.getbbox(sequence)
        width = max(160, bbox[2] - bbox[0] + 24)
        height = max(160, bbox[3] - bbox[1] + 24)
    except (OSError, ValueError):
        return None
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(image).text((12 - bbox[0], 12 - bbox[1]), sequence, font=font, embedded_color=True)
    bounds = image.getchannel("A").getbbox()
    return image.crop(bounds) if bounds else None


@lru_cache(maxsize=4)
def _emoji_rendered_catalog(
    sequence_data_path: str,
    font_path: str,
    max_sequences: int,
) -> tuple[tuple[str, tuple[tuple[bool, ...], ...], float], ...]:
    """Render the pinned atlas once per process, then reuse immutable masks.

    The previous implementation rendered every configured sequence again for
    the deterministic repeat call and for every fixture.  That made a correct
    offline benchmark appear hung and encouraged callers to lower the atlas
    coverage.  The cache key is the pinned data/font path plus the explicit
    sequence bound, so it cannot cross model versions silently.
    """

    font = ImageFont.truetype(font_path, 109)
    values = _emoji_sequences(sequence_data_path)[:max_sequences]
    rendered: list[tuple[str, tuple[tuple[bool, ...], ...], float]] = []
    for sequence in values:
        mask = _render_emoji_mask(font, sequence)
        if mask is not None:
            rendered.append((sequence, mask, max(1.0, float(font.getlength(sequence)))))
    return tuple(rendered)


@lru_cache(maxsize=8192)
def _resize_mask_array(mask: tuple[tuple[bool, ...], ...], width: int, height: int) -> np.ndarray:
    image = Image.frombytes(
        "L",
        (len(mask[0]), len(mask)),
        b"".join(bytes(255 if value else 0 for value in row) for row in mask),
    )
    # Bilinear resampling is sufficient for the binary atlas comparison and is
    # materially cheaper than Lanczos when thousands of pinned sequences are
    # evaluated for each run.
    image = image.resize((max(1, width), max(1, height)), Image.Resampling.BILINEAR)
    # ``getpixel`` per cell made the full pinned atlas benchmark quadratic in
    # Python overhead.  A contiguous byte view preserves the exact threshold
    # while keeping the deterministic mask representation.
    return np.asarray(image, dtype=np.uint8) > 32


def _resize_mask(mask: tuple[tuple[bool, ...], ...], width: int, height: int) -> tuple[tuple[bool, ...], ...]:
    resized = _resize_mask_array(mask, max(1, width), max(1, height))
    return tuple(
        tuple(bool(value) for value in resized[row])
        for row in range(resized.shape[0])
    )


def _mask_residual(source: tuple[tuple[bool, ...], ...], candidate: tuple[tuple[bool, ...], ...]) -> tuple[int, int, float]:
    height = max(len(source), len(candidate))
    width = max(len(source[0]), len(candidate[0]))
    left = np.zeros((height, width), dtype=bool)
    right = np.zeros((height, width), dtype=bool)
    left[: len(source), : len(source[0])] = np.asarray(source, dtype=bool)
    right[: len(candidate), : len(candidate[0])] = np.asarray(candidate, dtype=bool)
    residual = int(np.count_nonzero(np.logical_xor(left, right)))
    union = int(np.count_nonzero(np.logical_or(left, right)))
    return residual, union, residual / max(1, union)


def _mask_residual_array(source: np.ndarray, candidate: np.ndarray) -> tuple[int, int, float]:
    height = max(source.shape[0], candidate.shape[0])
    width = max(source.shape[1], candidate.shape[1])
    left = np.zeros((height, width), dtype=bool)
    right = np.zeros((height, width), dtype=bool)
    left[: source.shape[0], : source.shape[1]] = source
    right[: candidate.shape[0], : candidate.shape[1]] = candidate
    residual = int(np.count_nonzero(np.logical_xor(left, right)))
    union = int(np.count_nonzero(np.logical_or(left, right)))
    return residual, union, residual / max(1, union)


def _rgba_residual(source: tuple[tuple[tuple[int, int, int, int], ...], ...], candidate: Image.Image) -> tuple[int, int, float]:
    height = max(len(source), candidate.height)
    width = max(len(source[0]), candidate.width)
    source_image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    source_bytes = b"".join(bytes(channel for pixel in row for channel in pixel) for row in source)
    source_image.paste(Image.frombytes("RGBA", (len(source[0]), len(source)), source_bytes), (0, 0))
    candidate_image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    candidate_image.paste(candidate, (0, 0))
    from PIL import ImageChops

    difference = ImageChops.difference(source_image, candidate_image).convert("L")
    source_alpha = source_image.getchannel("A")
    candidate_alpha = candidate_image.getchannel("A")
    union = ImageChops.lighter(source_alpha, candidate_alpha).convert("L")
    residual = sum(difference.histogram()[1:])
    union_pixels = sum(union.histogram()[1:])
    return residual, union_pixels, residual / max(1, union_pixels * 255)


@dataclass(frozen=True)
class EmojiAtlasAdapter:
    """Offline atlas matcher driven only by a geometry-owned run mask.

    ``sequence_data_path`` is the pinned Unicode RGI data file.  The adapter
    enumerates that file itself; no fixture transcript, caller-selected emoji,
    or ``emoji_sequence_proposals`` value is read as recognition evidence.
    """

    sequence_data_path: str | None = None
    font_path: str | None = None
    font_hashes: Mapping[str, str] = field(default_factory=dict)
    name: str = "emoji-grapheme-atlas"
    version: str = "unicode-emoji-17.0"
    max_sequences: int = 10000
    tie_margin: float = 0.00001

    @classmethod
    def from_cache(cls, cache_root: str | os.PathLike[str]) -> "EmojiAtlasAdapter":
        root = Path(cache_root).resolve()
        sequence_path = root / "emoji-test.txt"
        font_path = root / "NotoColorEmoji.ttf"
        hashes: dict[str, str] = {}
        if sequence_path.exists():
            hashes["unicode_emoji_test"] = sha256_file(sequence_path)
        if font_path.exists():
            hashes["noto_color_emoji"] = sha256_file(font_path)
        return cls(sequence_data_path=str(sequence_path), font_path=str(font_path), font_hashes=hashes)

    def _configured(self) -> tuple[str, ...]:
        if not self.sequence_data_path or not self.font_path:
            return ()
        if not Path(self.sequence_data_path).exists() or not Path(self.font_path).exists():
            return ()
        values = _emoji_sequences(self.sequence_data_path)
        return values[: self.max_sequences]

    def capability_profile(self, environment_lock: EnvironmentLock) -> CapabilityProfile:
        values = self._configured()
        font_hashes = dict(self.font_hashes)
        if self.font_path and Path(self.font_path).exists() and "noto_color_emoji" not in font_hashes:
            font_hashes["noto_color_emoji"] = sha256_file(self.font_path)
        if self.sequence_data_path and Path(self.sequence_data_path).exists() and "unicode_emoji_test" not in font_hashes:
            font_hashes["unicode_emoji_test"] = sha256_file(self.sequence_data_path)
        return CapabilityProfile(
            adapter=self.name,
            adapter_version=self.version,
            supported_scripts=("emoji",) if values else (),
            supported_directions=("ltr",),
            grapheme_coverage=("extended-grapheme-cluster",) if values else (),
            emoji_coverage=("RGI fully-qualified", f"count:{len(values)}") if values else (),
            model_hashes=font_hashes,
            runtime_versions={"unicodedata": unicodedata.unidata_version, "regex": regex.__version__, "pillow": PIL.__version__},
            license="OFL-1.1+Unicode-Terms-of-Use",
            offline=True,
            runtime_network=False,
            tested_fixture_families=("emoji_zwj", "emoji_variation_selector"),
            unsupported_cases=("unconfigured_sequence", "visual_unicode_collision", "partial_cluster", "font_strike_unavailable"),
            status="available" if values and font_hashes.get("noto_color_emoji") and font_hashes.get("unicode_emoji_test") else "unavailable",
        )

    def propose(self, source: Mapping[str, Any], geometry: Mapping[str, Any], components: Mapping[str, Any], environment_lock: EnvironmentLock) -> ProposalSet:
        profile = self.capability_profile(environment_lock)
        if profile.status == "unavailable":
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "emoji_atlas_unavailable")
        evidence = geometry.get("run_mask")
        if not isinstance(evidence, Mapping) or evidence.get("authority") != "geometry_proven_run":
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_run_mask_missing")
        if evidence.get("grapheme_complete") is False:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "partial_cluster")
        target = _run_mask(geometry)
        if target is None:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_run_mask_invalid")
        # Atlas matching is still invoked for every geometry-owned run, but a
        # source-derived modality screen avoids rendering thousands of emoji
        # candidates for ordinary monochrome text rows.  It is deliberately
        # based only on run pixels and dimensions; no transcript or sequence
        # hint is consulted.  Tall monochrome runs remain eligible so a
        # grayscale emoji screenshot is not excluded by this fast path.
        color_stats = source.get("run_color_stats")
        if isinstance(color_stats, Mapping):
            strongly_colored = int(color_stats.get("strongly_colored_pixels", 0))
            if strongly_colored == 0 and len(target) < 48:
                return _unsupported_proposal(self.name, self.version, source, environment_lock, "emoji_modality_not_evidenced")
        target_rgba = _run_rgba(geometry)
        if target_rgba is not None and (len(target_rgba) != len(target) or len(target_rgba[0]) != len(target[0])):
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_run_mask_invalid")
        advances = evidence.get("measured_advances")
        if not isinstance(advances, (list, tuple)) or not advances:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "measured_advance_missing")
        try:
            advance_values = tuple(sorted({max(1.0, min(512.0, float(value))) for value in advances}))
        except (TypeError, ValueError):
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "measured_advance_invalid")
        try:
            font = ImageFont.truetype(str(self.font_path), 109)
        except (OSError, TypeError):
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "font_strike_unavailable")
        configured = self._configured()
        source_hash, geometry_hash, components_hash = _source_hashes(source)
        run_hash = _mask_hash(target)
        rgba_hash = _rgba_hash(target_rgba) if target_rgba is not None else ""
        cache_key = (
            "emoji-atlas",
            self.name,
            self.version,
            str(self.max_sequences),
            source_hash,
            geometry_hash,
            components_hash,
            environment_lock.output_hash,
            run_hash,
            rgba_hash,
            ",".join(str(value) for value in advance_values),
        )
        cached = _PROPOSAL_CACHE.get(cache_key)
        if cached is not None:
            return cached
        try:
            rendered_catalog = _emoji_rendered_catalog(
                str(self.sequence_data_path),
                str(self.font_path),
                int(self.max_sequences),
            )
        except (OSError, TypeError, ValueError):
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "font_strike_unavailable")
        target_height = len(target_rgba) if target_rgba is not None else len(target)
        target_array = np.asarray(target, dtype=bool)
        scored: list[dict[str, Any]] = []
        for sequence, rendered, native_advance in rendered_catalog:
            native_width = len(rendered[0])
            for advance in advance_values:
                scale = max(0.75, min(1.25, advance / native_advance))
                scaled = _resize_mask_array(rendered, round(native_width * scale), target_height)
                residual, union, residual_fraction = _mask_residual_array(target_array, scaled)
                score = residual_fraction + abs(native_advance - advance) / max(1.0, advance) * 0.05
                scored.append({
                    "sequence": sequence,
                    "advance": advance,
                    "font_size": 109,
                    "native_width": native_width,
                    "scale": scale,
                    "residual_pixels": residual,
                    "union_pixels": union,
                    "residual_fraction": residual_fraction,
                    "score": score,
                })
        scored.sort(key=lambda item: (item["score"], item["sequence"], item["advance"]))

        def ensure_mask_hash(item: MutableMapping[str, Any]) -> str:
            existing = item.get("mask_hash")
            if isinstance(existing, str) and is_sha256(existing):
                return existing
            sequence = str(item["sequence"])
            rendered = next(mask for candidate, mask, _advance in rendered_catalog if candidate == sequence)
            native_width = int(item.get("native_width", len(rendered[0])))
            scale = float(item.get("scale", 1.0))
            scaled = _resize_mask(rendered, round(native_width * scale), target_height)
            item["mask_hash"] = _mask_hash(scaled)
            return str(item["mask_hash"])

        for item in scored[: min(128, len(scored))]:
            ensure_mask_hash(item)
        if target_rgba is not None:
            # Alpha gets us to a bounded candidate set; color residuals then
            # distinguish skin tones and other sequences with identical masks.
            for item in scored[: min(64, len(scored))]:
                image = _render_emoji_image(font, item["sequence"])
                if image is None:
                    item["color_score"] = 1.0
                    continue
                native_advance = max(1.0, float(font.getlength(item["sequence"])))
                scale = max(0.75, min(1.25, item["advance"] / native_advance))
                image = image.resize((max(1, round(image.width * scale)), target_height), Image.Resampling.LANCZOS)
                color_residual, color_union, color_fraction = _rgba_residual(target_rgba, image)
                item.update(
                    {
                        "color_residual_pixels": color_residual,
                        "color_union_pixels": color_union,
                        "color_residual_fraction": color_fraction,
                        "color_score": color_fraction,
                        "color_mask_hash": sha256_bytes(image.tobytes()),
                    }
                )
                item["score"] = color_fraction + abs(native_advance - item["advance"]) / max(1.0, item["advance"]) * 0.05
            scored.sort(key=lambda item: (item["score"], item["sequence"], item["advance"]))
        if not scored:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "emoji_sequence_unresolved")
        best = scored[0]
        ties = [item for item in scored[1:] if abs(item["score"] - best["score"]) <= self.tie_margin]
        best_residual = best.get("color_score", best["residual_fraction"])
        if best_residual > 0.25:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "candidate_margin_insufficient")
        best_visual_hash = best.get("color_mask_hash", ensure_mask_hash(best))
        if ties and any(item.get("color_mask_hash", ensure_mask_hash(item)) == best_visual_hash for item in ties):
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "unicode_visual_collision")
        if ties:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "candidate_margin_insufficient")
        top = scored[:5]
        candidates = tuple(
            _candidate(
                text=item["sequence"],
                source_hash=source_hash,
                geometry_hash=geometry_hash,
                components_hash=components_hash,
            environment_hash=environment_lock.output_hash,
            confidence=max(0.0, min(1.0, 1.0 - item["score"])),
            component_ids=tuple(
                str(value)
                for value in (
                    evidence.get("component_ids", ())
                    if isinstance(evidence, Mapping)
                    else source.get("component_ids", ())
                )
            ),
            alternatives=tuple(other["sequence"] for other in top if other["sequence"] != item["sequence"]),
                extra_input_hashes={"run_mask": run_hash, **dict(self.font_hashes)},
            )
            for item in top
        )
        proposal = RecognitionProposal(
            proposal_id=f"{self.name}-run",
            adapter=self.name,
            adapter_version=self.version,
            model_hashes={**dict(environment_lock.model_hashes), **dict(self.font_hashes)},
            candidates=candidates,
            run_id=str(evidence.get("run_id", source.get("run_id", "run-0"))),
            input_hashes={"source": source_hash, "geometry": geometry_hash, "components": components_hash, "environment": environment_lock.output_hash, "run_mask": run_hash},
            configuration={"advance_values": list(advance_values), "font_size": 109, "candidate_count": len(configured)},
            provenance={"run_mask_hash": run_hash, "residual_evidence": top, "external_sequence_input_ignored": "emoji_sequence_proposals" in source},
            status="proposal",
        )
        proposal_set = ProposalSet(
            adapter=self.name,
            adapter_version=self.version,
            environment_lock_hash=environment_lock.output_hash,
            proposals=(proposal,),
            supported_scripts=("emoji",),
            status="proposal_only",
        )
        if len(_PROPOSAL_CACHE) >= _PROPOSAL_CACHE_LIMIT:
            _PROPOSAL_CACHE.pop(next(iter(_PROPOSAL_CACHE)))
        _PROPOSAL_CACHE[cache_key] = proposal_set
        return proposal_set


def inventory_adapters() -> dict[str, Any]:
    executable = shutil.which("tesseract")
    executable_hash = sha256_file(executable) if executable else None
    languages: list[str] = []
    version = "unavailable"
    if executable:
        version_output = subprocess.run([executable, "--version"], capture_output=True, text=True, check=False)
        version = version_output.stdout.splitlines()[0] if version_output.stdout else "unknown"
        language_output = subprocess.run([executable, "--list-langs"], capture_output=True, text=True, check=False)
        languages = [line.strip() for line in language_output.stdout.splitlines()[1:] if line.strip()]
    template_font = _unicode_template_font_path()
    model_paths = (
        {
            "unicode-template-latin.font": template_font,
            "unicode-template-combining.font": template_font,
            "unicode-template-kana.font": template_font,
            "unicode-template-arabic.font": template_font,
            "unicode-template-cjk.font": template_font,
        }
        if template_font
        else {}
    )
    lock = build_environment_lock(script_packs=tuple(languages), model_paths=model_paths)
    adapters = (
        TesseractOfflineAdapter(executable=executable, version=version.split(" ", 1)[-1] if version != "unavailable" else version),
        FixedLatticeStructuralAdapter(),
        StructuralUnicodeRowAdapter(),
        UnicodeTemplateRunAdapter(repertoire_name="latin", name="unicode-template-latin"),
        UnicodeTemplateRunAdapter(repertoire_name="combining", name="unicode-template-combining"),
        UnicodeTemplateRunAdapter(repertoire_name="kana", name="unicode-template-kana"),
        UnicodeTemplateRunAdapter(repertoire_name="arabic", name="unicode-template-arabic"),
        UnicodeTemplateRunAdapter(repertoire_name="cjk", name="unicode-template-cjk"),
        PaddleOCROfflineAdapter(),
        IndependentOfflineAdapter(backend="easyocr", name="independent-offline-easyocr"),
        IndependentOfflineAdapter(backend="surya", name="independent-offline-surya"),
        EmojiAtlasAdapter(),
    )
    profiles = [adapter.capability_profile(lock).to_dict() for adapter in adapters]
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "tesseract": {"path": executable, "binary_sha256": executable_hash, "version": version, "languages": languages},
        "adapters": profiles,
        "offline": True,
        "network_required": False,
    }


def benchmark_release_coverage(fixture_ids: list[str], adapters: tuple[Recognizer, ...]) -> dict[str, Any]:
    """Compatibility report for callers that only have fixture IDs.

    This intentionally remains conservative: an ID-only benchmark cannot prove
    exact logical top-k coverage, so it can never return a passing release gate.
    Use :func:`benchmark_offline_ensemble` with fixture artifacts for the real
    proposal benchmark.
    """
    results = []
    for adapter in adapters:
        unsupported = [fixture for fixture in fixture_ids if any(token in fixture for token in ("kana", "kanji", "arabic", "combining", "width", "emoji", "mixed"))]
        profile = adapter.capability_profile(build_environment_lock()) if hasattr(adapter, "capability_profile") else None
        results.append({
            "adapter": adapter.name,
            "version": adapter.version,
            "supported_scripts": list(adapter.supported_scripts),
            "release_fixture_count": len(fixture_ids),
            "unsupported_release_fixtures": unsupported,
            "status": "blocked_release_coverage" if unsupported else "proposal_only",
            "acceptance_oracle": False,
            "capability_profile": profile.to_dict() if profile else None,
        })
    return {"status": "blocked_release_coverage", "results": results, "reason": "no pinned offline whole-run Unicode recognizer covers the release scripts"}


def _fixture_source(fixture: Mapping[str, Any], root: Path | None) -> dict[str, Any]:
    source_path = Path(str(fixture.get("source_png", fixture.get("path", ""))))
    if root is not None and not source_path.is_absolute():
        source_path = root / source_path
    source = dict(fixture.get("source", {}))
    source.update(
        {
            "path": str(source_path),
            "source_sha256": str(fixture.get("source_sha256", source.get("source_sha256", ""))),
            "geometry_hash": str(fixture.get("geometry_hash", source.get("geometry_hash", "0" * 64))),
            "components_hash": str(fixture.get("components_hash", source.get("components_hash", "0" * 64))),
        }
    )
    return source


def _proposal_texts(result: ProposalSet, *, top_k: int | None) -> tuple[str, ...]:
    ranked: list[tuple[float, int, str]] = []

    def priority(text: str) -> int:
        compact = text.strip()
        return -1 if (
            len(compact) >= 2
            and len(set(compact.replace(" ", ""))) == 1
            and compact in {"___", "---", "===", "￣￣￣", "＿ ＿"}
        ) else 0

    for proposal in result.proposals:
        for candidate in proposal.candidates:
            if candidate.text != "?":
                ranked.append((float(candidate.confidence), priority(candidate.normalized_text), candidate.normalized_text))
            # A recognizer may keep its row beam in the candidate's
            # alternatives field.  Those strings are evidence with lower
            # deterministic priority, not hidden output; dropping them here
            # made the joint decoder effectively greedy again.
            for alternative_index, alternative in enumerate(candidate.alternatives, start=1):
                normalized = unicodedata.normalize("NFC", str(alternative))
                if normalized and normalized != "?":
                    ranked.append(
                        (
                            max(0.0, float(candidate.confidence) - 0.02 * alternative_index),
                            alternative_index + priority(normalized),
                            normalized,
                        )
                    )
    ordered = sorted(ranked, key=lambda item: (-item[0], item[1], item[2]))
    if top_k is not None:
        ordered = ordered[: max(1, int(top_k))]
    return tuple(dict.fromkeys(text for _confidence, _rank, text in ordered))


def _compose_run_texts(
    run_candidates: list[tuple[int, tuple[str, ...]]],
    *,
    top_k: int,
) -> tuple[str, ...]:
    """Compose per-run proposals into complete logical fixture sequences.

    A benchmark that merely unions text from each run can never match a
    multi-row transcript (or a row containing multiple shaped runs).  Geometry
    supplies the row index, so candidates are concatenated within a row and
    rows are joined with a literal newline.  The bounded Cartesian product is
    deterministic and keeps proposal coverage measurement finite.
    """

    grouped: dict[int, list[tuple[str, ...]]] = {}
    for row_index, candidates in run_candidates:
        if candidates:
            grouped.setdefault(int(row_index), []).append(candidates)
    if not grouped:
        return ()
    row_options: list[tuple[str, ...]] = []
    for row_index in sorted(grouped):
        options = ("",)
        for candidates in grouped[row_index]:
            options = tuple(
                dict.fromkeys(prefix + candidate for prefix in options for candidate in candidates)
            )[: max(top_k, 1) * 4]
        row_options.append(options)
    complete = ("",)
    for options in row_options:
        complete = tuple(
            dict.fromkeys(
                prefix + ("\n" if prefix else "") + row
                for prefix in complete
                for row in options
            )
        )[: max(top_k, 1) * 8]
    return complete[:top_k]


def _coverage_rank_matrix(
    target: str,
    adapter_records: list[Mapping[str, Any]],
    *,
    fixture_id: str,
    source_hash: str,
    geometry_status: str,
    geometry_rejection_codes: list[str],
    top_k: int,
) -> dict[str, Any]:
    """Classify target rows against retained adapter/run evidence.

    This is a measurement surface, not a decoder. It runs after proposals
    exist and therefore cannot influence recognition. A missing target is
    represented explicitly; rejected operator guesses must never be supplied
    here as a substitute for truth.
    """

    if not target:
        return {
            "status": "evaluation_truth_unavailable",
            "fixture": fixture_id,
            "source_sha256": source_hash,
            "geometry_status": geometry_status,
            "geometry_rejection_codes": list(geometry_rejection_codes),
            "rows": [],
            "reason": "no_authoritative_transcript",
        }

    def row_options(run_entries: list[Mapping[str, Any]]) -> tuple[str, ...]:
        options = ("",)
        for run in run_entries:
            proposals = tuple(str(item) for item in run.get("proposals", ()))
            if not proposals:
                return ()
            options = tuple(
                dict.fromkeys(prefix + proposal for prefix in options for proposal in proposals)
            )[: max(256, int(top_k) * 16)]
        # The empty prefix is consumed by the first expansion; after that
        # step every option is a real proposal.  Dropping options[0] here
        # would erase the adapter's top-ranked row candidate from the matrix.
        return options

    # Keep each adapter's evidence independent.  An unavailable adapter may
    # have an empty run while another adapter has valid proposals for the
    # same geometry hypothesis; merging them would erase the valid row.
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for record in adapter_records:
        adapter_name = str(record.get("adapter", ""))
        for variant in record.get("row_proposals", ()):
            variant_id = str(variant.get("hypothesis_id", ""))
            for row in variant.get("rows", ()):
                row_index = int(row.get("row_index", 0))
                run_entries = row.get("runs")
                if not isinstance(run_entries, (list, tuple)) or not run_entries:
                    run_entries = ({
                        "run_id": row.get("run_id", ""),
                        "proposals": row.get("proposals", ()),
                        "run_input_hash": row.get("run_input_hash"),
                    },)
                key = (adapter_name, variant_id, row_index)
                for run in run_entries:
                    grouped.setdefault(key, []).append(
                        {
                            "adapter": adapter_name,
                            "variant_id": variant_id,
                            "run_id": str(run.get("run_id", "")),
                            "proposals": tuple(str(item) for item in run.get("proposals", ())),
                            "run_input_hash": run.get("run_input_hash"),
                            "repeat_run_hash": record.get("repeat_run_hash"),
                        }
                    )

    rows = target.split("\n")
    matrix_rows: list[dict[str, Any]] = []
    for row_index, expected in enumerate(rows):
        normalized_expected = unicodedata.normalize("NFC", expected)
        observations: list[dict[str, Any]] = []
        for (adapter_name, variant_id, candidate_row), run_entries in sorted(grouped.items()):
            if candidate_row != row_index:
                continue
            for rank, proposed in enumerate(row_options(run_entries), start=1):
                observations.append(
                    {
                        "adapter": adapter_name,
                        "hypothesis_id": variant_id,
                        "rank": rank,
                        "text": unicodedata.normalize("NFC", proposed),
                        "run_input_hashes": sorted(
                            str(entry["run_input_hash"])
                            for entry in run_entries
                            if entry.get("run_input_hash")
                        ),
                        "proposal_hashes": sorted(
                            str(entry["repeat_run_hash"])
                            for entry in run_entries
                            if entry.get("repeat_run_hash")
                        ),
                    }
                )
        observations.sort(
            key=lambda item: (
                int(item["rank"]),
                str(item["adapter"]),
                str(item["hypothesis_id"]),
                str(item["text"]),
            )
        )
        exact = [item for item in observations if item["text"] == normalized_expected]
        unsupported = any(
            any("unsupported" in str(code) or "unavailable" in str(code) for code in record.get("unsupported_status", ()))
            for record in adapter_records
        )
        if exact:
            best_rank = min(int(item["rank"]) for item in exact)
            collision = any(
                "collision" in str(code)
                for record in adapter_records
                for code in record.get("unsupported_status", ())
            )
            classification = "visual_collision" if collision else "present_and_winning" if best_rank == 1 else "present_but_losing"
        elif not observations and unsupported:
            best_rank = None
            classification = "unsupported"
        else:
            best_rank = None
            classification = "absent"
        matrix_rows.append(
            {
                "row_index": row_index,
                "expected_logical_sequence": normalized_expected,
                "classification": classification,
                "proposal_rank": best_rank,
                "proposed_by": sorted({item["adapter"] for item in exact}),
                "selected_wrong_result": [
                    {
                        "adapter": item["adapter"],
                        "hypothesis_id": item["hypothesis_id"],
                        "text": item["text"],
                    }
                    for item in observations
                    if int(item["rank"]) == 1 and item["text"] != normalized_expected
                ],
                "observations": observations,
            }
        )
    return {
        "status": "measured",
        "fixture": fixture_id,
        "source_sha256": source_hash,
        "geometry_status": geometry_status,
        "geometry_rejection_codes": list(geometry_rejection_codes),
        "rows": matrix_rows,
        "reason": "source-derived proposal coverage measured after adapter execution",
    }


def _template_run_residual(
    text: str,
    run: Mapping[str, Any],
    geometry: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Compare a proposal's shaped glyph templates with the source run mask.

    This is deliberately a diagnostic fit, not pixel-parity authority: the
    source font may differ from the pinned template font.  It nevertheless
    preserves whole-run placement, Unicode display widths, and leading
    columns, so a candidate that drops a slash or invents a bar cannot tie a
    structurally consistent proposal merely because both have the same width.
    """

    font_path = _structural_font_path()
    if not font_path:
        return None
    source_values = _mask_from_pixels(run.get("binary_run_mask"))
    if source_values is None:
        return None
    source = np.asarray(source_values, dtype=bool)
    mixed = geometry.get("mixed_width_display") or {}
    anchor = run.get("anchor_evidence") if isinstance(run.get("anchor_evidence"), Mapping) else {}
    base = float(anchor.get("base_advance_px", mixed.get("base_advance_px", 0.0)))
    origin = float(anchor.get("origin_px", mixed.get("origin_px", 0.0)))
    if base <= 0.0:
        return None
    height, width = source.shape
    rendered = np.zeros_like(source, dtype=bool)
    cursor = 0
    for grapheme in regex.findall(r"\X", unicodedata.normalize("NFC", text)):
        units = wcwidth.wcswidth(grapheme)
        if units < 0:
            return None
        if units == 0:
            continue
        # Spaces are represented by their measured advance and have no ink.
        if grapheme.isspace():
            cursor += units
            continue
        template = _structural_template(
            font_path,
            grapheme,
            units,
            max(1, round(base)),
            height,
        )
        if template is None:
            return None
        normalized = (np.asarray(template, dtype=np.uint8) * 255)
        target_width = max(1, int(round(base * units)))
        image = Image.fromarray(normalized, mode="L").resize(
            (target_width, height), Image.Resampling.BILINEAR
        )
        glyph_mask = np.asarray(image, dtype=np.uint8) > 80
        raw_x0 = int(round(origin + cursor * base))
        raw_x1 = raw_x0 + target_width
        dst_x0 = max(0, raw_x0)
        dst_x1 = min(width, raw_x1)
        if dst_x1 > dst_x0:
            src_x0 = dst_x0 - raw_x0
            src_x1 = src_x0 + (dst_x1 - dst_x0)
            rendered[:, dst_x0:dst_x1] |= glyph_mask[:, src_x0:src_x1]
        cursor += units

    # Permit only a tiny rasterization translation while scoring; larger
    # placement errors belong to geometry/alignment and must remain visible.
    best_fraction = 1.0
    best_shift = (0, 0)
    source_pixels = int(source.sum())
    vertical_search = range(-max(1, height // 3), max(1, height // 3) + 1)
    for dy in vertical_search:
        for dx in (-1, 0, 1):
            shifted = np.zeros_like(rendered)
            y0 = max(0, dy)
            y1 = min(height, height + dy)
            x0 = max(0, dx)
            x1 = min(width, width + dx)
            sy0 = max(0, -dy)
            sy1 = sy0 + (y1 - y0)
            sx0 = max(0, -dx)
            sx1 = sx0 + (x1 - x0)
            if y1 > y0 and x1 > x0:
                shifted[y0:y1, x0:x1] = rendered[sy0:sy1, sx0:sx1]
            union = int(np.logical_or(source, shifted).sum())
            residual = int(np.logical_xor(source, shifted).sum())
            fraction = residual / max(1, union)
            if fraction < best_fraction:
                best_fraction = fraction
                best_shift = (dx, dy)
    return {
        "residual_fraction": float(best_fraction),
        "source_ink_pixels": source_pixels,
        "template_ink_pixels": int(rendered.sum()),
        "template_font_sha256": _structural_font_hash(font_path),
        "best_translation_px": [int(best_shift[0]), int(best_shift[1])],
    }


def _anchor_interval_residual(
    text: str,
    run: Mapping[str, Any],
    geometry: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Compare logical ink intervals with source-painted intervals.

    This deliberately ignores glyph shape.  It is a source-only placement
    diagnostic that catches a proposal which drops a substantive run or
    paints ink into a measured gap.  The result is advisory: Unicode width
    and component ownership still decide whether a proposal can be accepted.
    """

    evidence = run.get("anchor_evidence")
    if not isinstance(evidence, Mapping):
        return None
    painted = evidence.get("painted_runs")
    if not isinstance(painted, (list, tuple)):
        return None
    width = int(run.get("run_strip_width_px") or 0)
    if width <= 0:
        bounds = evidence.get("source_bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            width = max(0, int(bounds[2]) - int(bounds[0]))
    if width <= 0:
        return None
    mixed = geometry.get("mixed_width_display") or {}
    base = float(evidence.get("base_advance_px") or mixed.get("base_advance_px") or 0.0)
    origin = float(evidence.get("origin_px") or mixed.get("origin_px") or 0.0)
    if base <= 0.0:
        return None
    observed = np.zeros(width, dtype=bool)
    for item in painted:
        bounds = item.get("local_bounds") if isinstance(item, Mapping) else None
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
            continue
        x0 = max(0, min(width, int(bounds[0])))
        x1 = max(x0, min(width, int(bounds[2])))
        if x1 > x0:
            observed[x0:x1] = True
    graphemes = tuple(regex.findall(r"\X", unicodedata.normalize("NFC", text)))
    width_paths: list[tuple[int, ...]] = [()]
    for grapheme in graphemes:
        units = wcwidth.wcswidth(grapheme)
        if units < 0:
            return None
        if units == 0:
            choices = (0,)
        elif any(unicodedata.east_asian_width(char) in {"W", "F", "A"} for char in grapheme):
            # The geometry owner has not yet selected whether this source
            # treats a wide/ambiguous grapheme as one narrow advance or two.
            # Keep both bounded hypotheses in the advisory source score.
            choices = (1, 2)
        else:
            choices = (units,)
        width_paths = [prefix + (choice,) for prefix in width_paths for choice in choices]
        if len(width_paths) > 4096:
            width_paths = width_paths[:4096]

    source_mask_height = int(run.get("run_strip_height_px") or 0)
    source_mask = _mask_from_pixels(run.get("binary_run_mask"))
    if source_mask_height <= 0:
        source_mask_height = int(np.asarray(source_mask, dtype=bool).shape[0]) if source_mask is not None else 0
    tiny_limit = max(3, int(source_mask_height * 0.15))
    substantive_items = [
        item
        for item in painted
        if isinstance(item, Mapping)
        and item.get("unit_start") is not None
        and int(item.get("ink_pixels", tiny_limit + 1)) > tiny_limit
    ]
    observed_component_starts = [int(item["unit_start"]) for item in substantive_items]
    # A connected source interval may occupy multiple logical units.  Keep
    # each occupied unit as an anchor slot while retaining raw component
    # count separately for diagnostics.
    observed_starts: list[float] = []
    for item in substantive_items:
        if not isinstance(item, Mapping) or item.get("unit_start") is None:
            continue
        start = int(item["unit_start"])
        end = int(item.get("unit_end", start + 1))
        observed_starts.extend(float(value) for value in range(start, max(start + 1, end)))

    source_mask = _mask_from_pixels(run.get("binary_run_mask"))
    observed_shapes: list[str] = []
    observed_component_details: list[dict[str, Any]] = []
    if source_mask is not None:
        source_mask = np.asarray(source_mask, dtype=bool)
        for item in substantive_items:
            bounds = item.get("local_bounds") if isinstance(item, Mapping) else None
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
                continue
            x0, y0, x1, y1 = (int(value) for value in bounds)
            crop = source_mask[max(0, y0):min(source_mask.shape[0], y1), max(0, x0):min(source_mask.shape[1], x1)]
            ys, xs = np.where(crop)
            if not len(xs):
                continue
            bbox_width = int(xs.max() - xs.min() + 1)
            bbox_height = int(ys.max() - ys.min() + 1)
            row_peak = int(crop.sum(axis=1).max())
            col_peak = int(crop.sum(axis=0).max())
            horizontal = bbox_height <= max(5, int(round(base * 0.45))) and bbox_width >= max(2, int(round(base * 1.25)))
            vertical = bbox_width <= max(5, int(round(base * 0.45))) and bbox_height >= max(2, int(round(base * 1.25)))
            if horizontal and not vertical:
                observed_shapes.append("horizontal")
            elif vertical and not horizontal:
                observed_shapes.append("vertical")
            elif horizontal and vertical:
                observed_shapes.append("orthogonal")
            elif row_peak >= col_peak and bbox_width >= bbox_height:
                observed_shapes.append("diagonal_or_horizontal")
            else:
                observed_shapes.append("diagonal_or_vertical")
            observed_component_details.append(
                {
                    "unit_start": int(item.get("unit_start", 0)),
                    "unit_end": int(item.get("unit_end", item.get("unit_start", 0) + 1)),
                    "bbox_width": bbox_width,
                    "bbox_height": bbox_height,
                    "y_center": float(ys.mean()) / max(1.0, float(source_mask.shape[0] - 1)),
                    "crossing": bool(_has_crossing_diagonals(crop)),
                    "area": int(crop.sum()),
                }
            )

    def score_width_path(path: tuple[int, ...]) -> tuple[float, np.ndarray, list[float], float, float, float, int, float]:
        predicted = np.zeros(width, dtype=bool)
        cursor = 0
        predicted_starts: list[float] = []
        predicted_graphemes: list[tuple[str, float]] = []
        for grapheme, units in zip(graphemes, path):
            if units <= 0:
                continue
            if not grapheme.isspace():
                x0 = max(0, min(width, int(round(origin + cursor * base))))
                x1 = max(x0, min(width, int(round(origin + (cursor + units) * base))))
                if x1 > x0:
                    predicted[x0:x1] = True
                predicted_starts.append(float(cursor))
                predicted_graphemes.append((grapheme, float(cursor)))
            cursor += units
        residual_pixels = int(np.count_nonzero(np.logical_xor(observed, predicted)))
        union_pixels = int(np.count_nonzero(np.logical_or(observed, predicted)))
        interval = residual_pixels / max(1, union_pixels)
        observed_origin = min(observed_starts) if observed_starts else 0.0
        predicted_origin = min(predicted_starts) if predicted_starts else 0.0
        if observed_starts and predicted_starts:
            start_residual = sum(
                min(abs((value - predicted_origin) - (other - observed_origin)) for other in observed_starts)
                for value in predicted_starts
            ) / max(1, len(predicted_starts))
            start_residual /= max(1.0, float(len(observed_starts)))
        else:
            start_residual = 1.0 if observed_starts != predicted_starts else 0.0
        predicted_count = len(predicted_starts)
        component_count = len(observed_component_starts)
        occupied_unit_count = len(observed_starts)
        horizontal_only = bool(observed_shapes) and all(shape == "horizontal" for shape in observed_shapes)
        expected_count = occupied_unit_count if horizontal_only else component_count
        count_residual = abs(predicted_count - expected_count) / max(1, expected_count)
        visible = [grapheme for grapheme, units in zip(graphemes, path) if units > 0 and not grapheme.isspace()]
        horizontal_chars = {"_", "-", "=", "＿", "￣", "~"}
        vertical_chars = {"|", "│", "l", "I", "ｌ"}
        if observed_shapes and all(shape == "horizontal" for shape in observed_shapes):
            morphology = sum(char not in horizontal_chars for grapheme in visible for char in grapheme) / max(1, len(visible))
        elif observed_shapes and all(shape == "vertical" for shape in observed_shapes):
            morphology = sum(char not in vertical_chars for grapheme in visible for char in grapheme) / max(1, len(visible))
        else:
            morphology = 0.0
        # Component topology is source evidence independent of the fallback
        # font.  Use it to reject punctuation labels that would require a
        # tiny isolated mark where the source has a substantive crossing, and
        # to distinguish middle-band dashes from bottom-band underscores.
        shape_penalty = 0.0
        punctuation = {".", ",", "'", "`", "丶", "、"}
        horizontal_middle = {"-", "=", "~", "￣"}
        horizontal_bottom = {"_", "＿"}
        for grapheme, start in predicted_graphemes:
            nearest = min(
                observed_component_details,
                key=lambda detail: (
                    min(abs(start - float(detail["unit_start"])), abs(start - float(detail["unit_end"] - 1))),
                    int(detail["unit_start"]),
                ),
                default=None,
            )
            if nearest is None:
                continue
            if any(char in punctuation for char in grapheme):
                if nearest["crossing"] and nearest["area"] > tiny_limit:
                    # A crossing component is a connected structural mark,
                    # not proof of a comma/period.  Keep the punctuation as a
                    # proposal, but make it lose to a structural alternative.
                    shape_penalty += 0.30
            if grapheme in horizontal_middle or grapheme in horizontal_bottom:
                y_center = float(nearest["y_center"])
                if grapheme in horizontal_bottom and y_center < 0.68:
                    shape_penalty += 0.28
                if grapheme in horizontal_middle and y_center > 0.68:
                    shape_penalty += 0.28
        shape_penalty /= max(1, len(predicted_graphemes))
        ranking = interval + 0.20 * count_residual + 0.10 * start_residual + 0.20 * morphology + 0.25 * shape_penalty
        return ranking, predicted, predicted_starts, interval, start_residual, float(morphology), predicted_count, float(shape_penalty)

    best_path = min(width_paths or [()], key=lambda path: score_width_path(path)[0])
    _ranking, predicted, predicted_starts, residual_fraction, start_residual, morphology_residual, predicted_count, shape_penalty = score_width_path(best_path)
    residual = int(np.count_nonzero(np.logical_xor(observed, predicted)))
    union = int(np.count_nonzero(np.logical_or(observed, predicted)))
    # Component cardinality and unit starts are independent of fallback-font
    # shape.  Normalize both sequences to their first painted unit so a
    # cropped run or negative global origin cannot manufacture a placement
    # penalty.  This catches proposals that preserve a broad union while
    # inventing punctuation or swallowing two source components into one.
    observed_count = len(observed_starts)
    horizontal_only = bool(observed_shapes) and all(shape == "horizontal" for shape in observed_shapes)
    expected_count = observed_count if horizontal_only else len(observed_component_starts)
    count_residual = abs(predicted_count - expected_count) / max(1, expected_count)
    return {
        "residual_fraction": float(residual_fraction),
        "residual_pixels": residual,
        "union_pixels": union,
        "observed_run_count": len(painted),
        "observed_component_count": len(observed_component_starts),
        "observed_occupied_unit_count": observed_count,
        "cardinality_reference": "occupied_units" if horizontal_only else "substantive_components",
        "cardinality_reference_count": expected_count,
        "predicted_component_count": predicted_count,
        "component_count_residual": float(count_residual),
        "anchor_start_residual": float(start_residual),
        "morphology_residual": float(morphology_residual),
        "shape_compatibility_penalty": float(shape_penalty),
        "observed_shape_classes": sorted(set(observed_shapes)),
        "selected_widths": list(best_path),
        "observed_ink_columns": int(observed.sum()),
        "predicted_ink_columns": int(predicted.sum()),
        "anchor_evidence_hash": str(evidence.get("evidence_hash", "")),
    }


def _proposal_fit_residual(candidate: Mapping[str, Any]) -> float:
    """Return one deterministic advisory residual for proposal ranking."""

    raster = candidate.get("source_raster_fit") or {}
    value = float(raster.get("residual_fraction", 1.0)) if isinstance(raster, Mapping) else 1.0
    anchor = candidate.get("source_anchor_fit") or {}
    if isinstance(anchor, Mapping) and anchor:
        # TXT acceptance is font-independent.  Source-measured interval
        # placement therefore dominates the fallback-font raster residual;
        # the latter remains a bounded diagnostic tie-breaker only.  Cardinality
        # and unit-start evidence are separate terms: a broad interval union
        # must not hide an invented punctuation mark or a swallowed anchor.
        interval = float(anchor.get("residual_fraction", 1.0))
        cardinality = float(anchor.get("component_count_residual", 1.0))
        starts = float(anchor.get("anchor_start_residual", 1.0))
        morphology = float(anchor.get("morphology_residual", 0.0))
        shape_compatibility = float(anchor.get("shape_compatibility_penalty", 0.0))
        value = (
            0.15 * value
            + 0.40 * interval
            + 0.20 * morphology
            + 0.20 * cardinality
            + 0.05 * starts
            + 0.25 * shape_compatibility
        )
    return value


def align_logical_text_to_run(
    text: str,
    run: Mapping[str, Any],
    geometry: Mapping[str, Any],
) -> dict[str, Any]:
    """Score a logical proposal against measured mixed-width anchors.

    This is alignment evidence, not candidate selection.  It keeps logical
    grapheme order separate from visual shaping and rejects width collisions or
    incomplete runs before any proposal can become a TXT candidate.
    """

    graphemes = tuple(regex.findall(r"\X", unicodedata.normalize("NFC", text)))
    widths: list[int | None] = []
    width_options: set[int] = {0}
    for grapheme in graphemes:
        width = wcwidth.wcswidth(grapheme)
        widths.append(width if width >= 0 else None)
        if width < 0:
            width_options = set()
            continue
        # The raster has not established whether this renderer treats a
        # fullwidth/ambiguous grapheme as one measured advance or two narrow
        # advances.  Keep both display-width hypotheses as evidence.  This is
        # deliberately not a Unicode-width decision: the final gate still
        # requires an explicit width profile before acceptance.
        east_asian = any(
            unicodedata.east_asian_width(char) in {"W", "F", "A"}
            for char in grapheme
        )
        choices = (1, 2) if east_asian and width > 0 else (width,)
        width_options = {
            prior + choice
            for prior in width_options
            for choice in choices
        }
    display_units = sum(width for width in widths if width is not None)
    mixed = geometry.get("mixed_width_display") or {}
    anchor = run.get("anchor_evidence") if isinstance(run.get("anchor_evidence"), Mapping) else {}
    base = float(anchor.get("base_advance_px", mixed.get("base_advance_px", 0.0)))
    origin = float(anchor.get("origin_px", mixed.get("origin_px", 0.0)))
    source_bounds = run.get("source_bounds", [0, 0, 0, 0])
    # Alignment consumes a content-cropped run strip.  Global source bounds
    # remain provenance only; using their width here reintroduces blank canvas
    # columns after mixed-display geometry has been rebased.
    strip_width = run.get("run_strip_width_px") or run.get("strip_width_px")
    if strip_width is None and isinstance(run.get("binary_run_mask"), (list, tuple)):
        first_row = run.get("binary_run_mask")[0] if run.get("binary_run_mask") else ()
        strip_width = len(first_row)
    source_width = max(
        0.0,
        float(strip_width)
        if strip_width is not None
        else float(source_bounds[2]) - float(source_bounds[0]),
    )
    if base > 0:
        # The measured run may start/end inside a display unit.  Rounding its
        # pixel width loses the phase/origin that produced the run strip and
        # rejects otherwise width-consistent proposals.  Recover the same
        # clipped unit interval used by the hypothesis builder.
        logical_start = run.get("logical_start_column")
        logical_end = run.get("logical_end_column")
        if logical_start is not None and logical_end is not None:
            target_units = max(0, int(logical_end) - int(logical_start))
        else:
            x0 = 0.0
            x1 = source_width
            first_unit = math.ceil((x0 - origin) / base)
            last_unit = math.ceil((x1 - origin) / base)
            target_units = max(0, int(last_unit - first_unit))
    else:
        target_units = None
    unknown_width = any(width is None for width in widths)
    width_ambiguous = bool(target_units is not None and target_units in width_options and target_units != display_units)
    width_error = (
        None
        if target_units is not None and (target_units == display_units or width_ambiguous)
        else abs(display_units - target_units) if target_units is not None and not unknown_width else None
    )
    status = "aligned"
    reasons: list[str] = []
    if unknown_width:
        status = "rejected"
        reasons.append("width_profile_missing")
    elif target_units is None:
        status = "rejected"
        reasons.append("mixed_width_anchor_missing")
    elif width_error:
        status = "rejected"
        reasons.append("logical_visual_contradiction")
    elif width_ambiguous:
        # Keep the proposal available to the joint decoder, but make the
        # unresolved width profile explicit so this can never become an
        # acceptance result by accident.
        status = "aligned_ambiguous"
        reasons.append("width_profile_ambiguous")
    residual = _template_run_residual(text, run, geometry)
    anchor_residual = _anchor_interval_residual(text, run, geometry)
    return {
        "text": text,
        "normalized_text": unicodedata.normalize("NFC", text),
        "graphemes": list(graphemes),
        "grapheme_widths": widths,
        "display_units": display_units,
        "display_width_options": sorted(width_options),
        "width_ambiguous": width_ambiguous,
        "target_units": target_units,
        "base_advance_px": base,
        "source_bounds": list(source_bounds),
        "alignment_width_px": source_width,
        "width_error_units": width_error,
        "status": status,
        "rejection_reasons": reasons,
        "source_raster_fit": residual,
        "source_anchor_fit": anchor_residual,
    }


def jointly_score_geometry_hypotheses(
    hypotheses: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    row_proposals: Mapping[str, Mapping[int, tuple[str, ...]]],
    *,
    top_k: int = 5,
    diagnostic_margin: float = 0.10,
) -> dict[str, Any]:
    """Jointly score geometry hypotheses and row proposals without selecting TXT.

    ``row_proposals`` contains adapter-produced logical alternatives keyed by
    hypothesis id and row index.  The score rewards complete width alignment
    and proposal confidence supplied by the adapter, while preserving all
    tied hypotheses.  A result is accepted only when the winner has a pinned
    margin and every row aligns; otherwise it remains unresolved evidence.
    """

    scored: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        provenance = dict(hypothesis.get("provenance", {}))
        h = dict(provenance.get("hypothesis", {}))
        origin = h.get("origin_px", "unknown")
        base_advance = h.get("base_advance_px", "unknown")
        hypothesis_id = f"{h.get('pitch', 'unknown')}:{h.get('phase', 'unknown')}:{base_advance}:{origin}"
        rows = tuple(hypothesis.get("runs", ()))
        alternatives = dict(row_proposals.get(hypothesis_id, {}))
        if not alternatives and "origin_px" not in h:
            # Historical unit seams omitted the horizontal-origin field;
            # retain their proposal-only compatibility without collapsing
            # origin-aware hypotheses in the production path.
            legacy_id = f"{h.get('pitch', 'unknown')}:{h.get('phase', 'unknown')}"
            alternatives = dict(row_proposals.get(legacy_id, {}))
        ownership = dict(h.get("ownership", {}))
        owned_pixels = ownership.get("owned_pixel_count")
        substantive_pixels = ownership.get("substantive_pixel_count")
        unowned_pixels = ownership.get("unowned_pixel_count", 0)
        multiply_owned_pixels = ownership.get("multiply_owned_pixel_count", 0)
        ownership_complete = bool(
            owned_pixels is not None
            and substantive_pixels is not None
            and int(owned_pixels) == int(substantive_pixels)
            and int(unowned_pixels) == 0
            and int(multiply_owned_pixels) == 0
        )
        alignments: list[dict[str, Any]] = []
        confidences: list[float] = []
        for row_index, run in enumerate(rows):
            texts = tuple(alternatives.get(int(run.get("row_index", row_index)), ()))
            if not texts:
                alignments.append({"row_index": row_index, "status": "rejected", "rejection_reasons": ["grapheme_unknown"]})
                continue
            candidates = [
                align_logical_text_to_run(
                    text,
                    run,
                    {"mixed_width_display": hypothesis.get("mixed_width_display", {})},
                )
                for text in texts
            ]
            aligned_candidates = [
                item for item in candidates
                if item["status"] in {"aligned", "aligned_ambiguous"}
            ]
            best = min(
                aligned_candidates or candidates,
                key=lambda item: (
                    _proposal_fit_residual(item),
                    int(item.get("width_error_units") or 0),
                    str(item.get("normalized_text", item.get("text", ""))),
                ),
            )
            if best.get("status") in {"aligned", "aligned_ambiguous"}:
                best = {**best, "proposal_fit_residual": _proposal_fit_residual(best)}
            alignments.append({"row_index": row_index, "candidates": candidates, "selected_diagnostic": best})
            if best["status"] in {"aligned", "aligned_ambiguous"}:
                fit = _proposal_fit_residual(best)
                confidences.append(max(0.0, 1.0 - fit))
        aligned_rows = sum(
            1
            for item in alignments
            if item.get("selected_diagnostic", {}).get("status") in {"aligned", "aligned_ambiguous"}
        )
        width_ambiguity_rows = sum(
            1
            for item in alignments
            if item.get("selected_diagnostic", {}).get("status") == "aligned_ambiguous"
        )
        row_count = len(rows)
        completeness = aligned_rows / max(1, row_count)
        # Compose complete row sequences with a lazy k-best additive search.
        # Rows remain in measured order and every option stays tied to its
        # alignment evidence, but the decoder never materializes the full
        # Cartesian product or truncates a row to the public report `top_k`.
        sequence_states: list[tuple[float, tuple[dict[str, Any], ...]]] = []
        row_option_lists: list[list[dict[str, Any]]] = []
        for alignment in alignments:
            row_options = [
                candidate
                for candidate in alignment.get("candidates", ())
                if candidate.get("status") in {"aligned", "aligned_ambiguous"}
            ]
            # Duplicate normalized strings do not provide independent
            # evidence and only waste the bounded sequence beam.
            unique_options: dict[str, dict[str, Any]] = {}
            for candidate in row_options:
                key = str(candidate.get("normalized_text", candidate.get("text", "")))
                prior = unique_options.get(key)
                if prior is None or (
                    _proposal_fit_residual(candidate),
                    key,
                ) < (
                    _proposal_fit_residual(prior),
                    key,
                ):
                    unique_options[key] = candidate
            ordered_options = sorted(
                unique_options.values(),
                key=lambda candidate: (
                    _proposal_fit_residual(candidate),
                    str(candidate.get("normalized_text", candidate.get("text", ""))),
                ),
            )
            if not ordered_options:
                row_option_lists = []
                break
            row_option_lists.append(ordered_options)
        if row_option_lists and len(row_option_lists) == row_count:
            import heapq

            row_costs = [
                [float(_proposal_fit_residual(candidate)) for candidate in options]
                for options in row_option_lists
            ]
            initial_indices = tuple(0 for _ in row_option_lists)
            initial_cost = sum(costs[0] for costs in row_costs)
            heap: list[tuple[float, tuple[int, ...]]] = [(initial_cost, initial_indices)]
            visited: set[tuple[int, ...]] = {initial_indices}
            while heap and len(sequence_states) < 64:
                cost, indices = heapq.heappop(heap)
                selected = tuple(
                    row_option_lists[row_index][option_index]
                    for row_index, option_index in enumerate(indices)
                )
                sequence_states.append((float(cost), selected))
                for row_index, option_index in enumerate(indices):
                    next_index = option_index + 1
                    if next_index >= len(row_option_lists[row_index]):
                        continue
                    next_indices = list(indices)
                    next_indices[row_index] = next_index
                    next_key = tuple(next_indices)
                    if next_key in visited:
                        continue
                    visited.add(next_key)
                    next_cost = cost - row_costs[row_index][option_index] + row_costs[row_index][next_index]
                    heapq.heappush(heap, (float(next_cost), next_key))
        sequence_proposals: list[dict[str, Any]] = []
        for cost, selected_rows in sequence_states:
            if len(selected_rows) != row_count:
                continue
            normalized_rows = [str(candidate.get("normalized_text", candidate.get("text", ""))) for candidate in selected_rows]
            residuals = [
                _proposal_fit_residual(candidate)
                for candidate in selected_rows
            ]
            sequence_text = "\n".join(normalized_rows)
            sequence_proposals.append(
                {
                    "text": sequence_text,
                    "normalized_text": sequence_text,
                    "row_count": row_count,
                    "row_residuals": residuals,
                    "score": max(0.0, 1.0 - float(cost) / max(1, row_count)),
                    "evidence_hash": sha256_bytes(
                        canonical_bytes(
                            {
                                "hypothesis_id": hypothesis_id,
                                "rows": normalized_rows,
                                "residuals": residuals,
                            }
                        )
                    ),
                }
            )
        sequence_proposals.sort(
            key=lambda item: (-float(item["score"]), str(item["normalized_text"]), str(item["evidence_hash"]))
        )
        sequence_proposals = sequence_proposals[:64]
        best_sequence = sequence_proposals[0] if sequence_proposals else None
        text_score = (
            float(best_sequence["score"])
            if best_sequence is not None
            else completeness * (sum(confidences) / max(1, len(confidences)))
        )
        # Recognition fit is only one term in a joint hypothesis.  When the
        # geometry evidence is available, retain the source-derived seam and
        # gutter measurements so a phase with more permissive OCR proposals
        # cannot outrank a materially cleaner raster lattice.  Missing fields
        # are tolerated for historical synthetic seams and fall back to the
        # text-only diagnostic score; they never create authority.
        seam_energy = h.get("normalized_seam_energy")
        seam_contrast = h.get("seam_to_interior_contrast")
        if isinstance(seam_energy, (int, float)) and isinstance(seam_contrast, (int, float)):
            geometry_score = 0.5 * (1.0 - max(0.0, min(1.0, float(seam_energy)))) + 0.5 * max(
                0.0, min(1.0, float(seam_contrast))
            )
            score = 0.65 * geometry_score + 0.35 * text_score
        else:
            geometry_score = None
            score = text_score
        scored.append(
            {
                "hypothesis_id": hypothesis_id,
                "pitch": h.get("pitch"),
                "phase": h.get("phase"),
                "score": score,
                "text_score": text_score,
                "geometry_score": geometry_score,
                "aligned_rows": aligned_rows,
                "row_count": row_count,
                "alignments": alignments,
                "logical_sequence_proposals": sequence_proposals,
                "best_logical_sequence": best_sequence,
                "ownership_complete": ownership_complete,
                "width_profile_ambiguous_rows": width_ambiguity_rows,
                "ownership_evidence": {
                    "owned_pixel_count": owned_pixels,
                    "substantive_pixel_count": substantive_pixels,
                    "unowned_pixel_count": unowned_pixels,
                    "multiply_owned_pixel_count": multiply_owned_pixels,
                },
                "status": (
                    "aligned"
                    if completeness == 1.0 and ownership_complete and width_ambiguity_rows == 0
                    else "rejected"
                ),
            }
        )
    scored.sort(key=lambda item: (-float(item["score"]), int(item.get("pitch") or 0), int(item.get("phase") or 0)))
    winner = scored[0] if scored else None
    runner = scored[1] if len(scored) > 1 else None
    margin = float(winner["score"] - runner["score"]) if winner and runner else 1.0 if winner else 0.0
    # A row-width alignment is useful evidence, but it is not transcript
    # authority.  Expose a diagnostic winner only when every row and every
    # source pixel is accounted for and the pinned margin clears; candidate
    # text remains null until the independent geometry/Unicode gates pass.
    diagnostic_ranked = bool(winner and winner["status"] == "aligned")
    diagnostic_status = (
        "accepted_diagnostic"
        if diagnostic_ranked and margin >= float(diagnostic_margin)
        else "unresolved"
    )
    return {
        "status": diagnostic_status,
        "candidate_txt": None,
        "winner": winner,
        "runner_up": runner,
        "margin": margin,
        "diagnostic_ranked": diagnostic_ranked,
        "authority": "proposal_alignment_only",
        "ownership_gate": "diagnostic_only; candidate ownership is not promoted",
        "diagnostic_margin_threshold": float(diagnostic_margin),
        "hypotheses": scored,
    }


def jointly_decode_geometry_text(
    hypotheses: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    row_proposals: Mapping[str, Mapping[int, tuple[str, ...]]],
    *,
    top_k: int = 16,
    diagnostic_margin: float = 0.10,
    scored_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the joint geometry/text stage and expose a review-only candidate.

    Geometry is allowed to remain unresolved while measured hypotheses are
    compared with complete row proposals.  This removes the old deadlock in
    which geometry had to be uniquely proved before recognition could supply
    useful evidence.  The returned text is *not* a canonical candidate: it is
    a hash-bound review surface only.  ``candidate_txt`` stays ``None`` here;
    the canonical writer still requires a passing gate report and operator
    receipt.
    """

    report = dict(scored_report or jointly_score_geometry_hypotheses(
        hypotheses,
        row_proposals,
        top_k=top_k,
        diagnostic_margin=diagnostic_margin,
    ))
    winner = report.get("winner")
    runner = report.get("runner_up")
    reasons: list[str] = []
    review_text: str | None = None
    if not isinstance(winner, Mapping):
        reasons.append("joint_hypothesis_missing")
    else:
        aligned_rows = int(winner.get("aligned_rows", 0))
        row_count = int(winner.get("row_count", 0))
        if aligned_rows != row_count:
            reasons.append("joint_row_alignment_incomplete")
        if not bool(winner.get("ownership_complete")):
            reasons.append("joint_ownership_incomplete")
        if int(winner.get("width_profile_ambiguous_rows", 0)):
            reasons.append("width_profile_ambiguous")
        margin = float(report.get("margin", 0.0))
        if margin < float(diagnostic_margin):
            reasons.append("joint_hypothesis_margin_insufficient")
        best = winner.get("best_logical_sequence")
        if isinstance(best, Mapping) and best.get("normalized_text"):
            review_text = str(best["normalized_text"])
        else:
            reasons.append("joint_logical_sequence_missing")
    # A review candidate may be displayed when all rows and source pixel
    # ownership are accounted for, even if a separate width/margin gate blocks
    # acceptance.  The blocker remains explicit and the canonical field stays
    # null; this lets an operator inspect the actual inferred text instead of
    # mistaking a gate failure for missing row evidence.
    review_surface = review_text is not None and not any(
        reason in {"joint_hypothesis_missing", "joint_row_alignment_incomplete", "joint_ownership_incomplete", "joint_logical_sequence_missing"}
        for reason in reasons
    )
    review_ready = review_surface and not reasons
    status = "review_pending" if review_ready else "review_blocked" if review_surface else "unresolved"
    candidate_hash = sha256_bytes(review_text.encode("utf-8")) if review_text is not None else None
    selected_id = winner.get("hypothesis_id") if isinstance(winner, Mapping) else None
    best_sequence = winner.get("best_logical_sequence") if isinstance(winner, Mapping) else None
    binding_hash = (
        sha256_bytes(
            canonical_bytes(
                {
                    "hypothesis_id": selected_id,
                    "sequence_evidence_hash": best_sequence.get("evidence_hash") if isinstance(best_sequence, Mapping) else None,
                    "logical_text": review_text,
                }
            )
        )
        if review_surface
        else None
    )
    return {
        "status": status,
        "candidate_txt": None,
        "review_candidate_txt": review_text if review_surface else None,
        "review_candidate_sha256": candidate_hash if review_surface else None,
        "review_binding_sha256": binding_hash,
        "operator_review_required": True,
        "authority": "joint_review_candidate_only",
        "rejection_reasons": sorted(set(reasons)),
        "selected_hypothesis": selected_id if isinstance(winner, Mapping) and review_surface else None,
        "winner": winner,
        "runner_up": runner,
        "margin": float(report.get("margin", 0.0)),
        "source_report": report,
    }


def benchmark_offline_ensemble(
    fixtures: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    adapters: tuple[Recognizer, ...],
    environment_lock: EnvironmentLock,
    *,
    root: str | os.PathLike[str] | None = None,
    top_k: int = 5,
    max_geometry_hypotheses: int = 16,
    deterministic_replay: bool = True,
    adapter_budgets_seconds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Measure deterministic proposal coverage; never selects an answer.

    Ground truth is read only after every adapter has produced its proposals.
    It is used to score the benchmark, never passed into an adapter.
    """

    root_path = Path(root).resolve() if root else None
    results: list[dict[str, Any]] = []
    coverage_matrices: list[dict[str, Any]] = []
    positive_missing: list[str] = []
    false_unique: list[str] = []
    repeated_failures: list[str] = []
    budget_failures: list[str] = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", ""))
        source = _fixture_source(fixture, root_path)
        # Geometry is recovered from the source raster at benchmark time.  A
        # fixture's expected mode or visual-layout sidecar is never promoted to
        # recognizer input.  The fallback exists only for the existing unit
        # seam tests whose source path is intentionally missing, and remains a
        # rejected/diagnostic path.
        geometry: dict[str, Any]
        components: dict[str, Any]
        geometry_status = "unavailable"
        geometry_rejection_codes: list[str] = []
        recognition_input_hash = None
        source_path = Path(str(source.get("path", "")))
        if source_path.exists():
            try:
                from .geometry import (
                    build_recognition_hypothesis_inputs,
                    build_recognition_inputs,
                    route_raster_geometry,
                )

                geometry_bundle, geometry_decision = route_raster_geometry(source_path)
                geometry_status = geometry_decision.status
                geometry_rejection_codes = list(geometry_decision.rejection_reasons)
                if geometry_decision.mode == "unresolved":
                    geometry = {
                        "mode": "fixed_lattice",
                        "geometry_proven": False,
                        "source_sha256": source.get("source_sha256") or geometry_bundle.source_sha256,
                        "geometry_evidence_hash": geometry_bundle.output_hash,
                        "mixed_width_display": dict(geometry_bundle.projection_evidence.get("mixed_width_display", {})),
                        "hypothesis_only": True,
                    }
                    components = dict(geometry_bundle.component_evidence)
                    hypothesis_inputs = build_recognition_hypothesis_inputs(
                        source_path,
                        geometry_bundle,
                        max_hypotheses=max(1, int(max_geometry_hypotheses)),
                    )
                else:
                    geometry = dict(geometry_decision.provenance["selected_geometry"])
                    recognition_inputs = build_recognition_inputs(source_path, geometry_bundle, mode=geometry_decision.mode)
                    recognition_input_hash = recognition_inputs["input_hash"]
                    # Every geometry-owned run is retained.  The adapter loop
                    # below materializes each strip and never collapses a
                    # source to runs[0].
                    components = dict(geometry_bundle.component_evidence)
                    hypothesis_inputs = ()
            except (OSError, ValueError) as exc:
                geometry_status = "rejected"
                geometry_rejection_codes = [f"geometry_recovery:{type(exc).__name__}"]
                geometry = {"mode": "unresolved", "geometry_proven": False, "source_sha256": source.get("source_sha256", "")}
                components = {}
                hypothesis_inputs = ()
        else:
            geometry = dict(fixture.get("geometry", {"mode": fixture.get("expected_geometry_mode", "unresolved")}))
            components = dict(fixture.get("components", {}))
            hypothesis_inputs = ()
        adapter_records: list[dict[str, Any]] = []
        union: list[str] = []
        if source_path.exists() and geometry_status == "proved":
            input_variants = (("authoritative", recognition_inputs),)
        else:
            input_variants = tuple(
                (
                    str(item.get("provenance", {}).get("hypothesis", {}).get("pitch", "hypothesis"))
                    + ":"
                    + str(item.get("provenance", {}).get("hypothesis", {}).get("phase", ""))
                    + ":"
                    + str(item.get("provenance", {}).get("hypothesis", {}).get("base_advance_px", ""))
                    + ":"
                    + str(item.get("provenance", {}).get("hypothesis", {}).get("origin_px", "")),
                    item,
                )
                for item in hypothesis_inputs
            )
        for adapter in adapters:
            # Tesseract is evaluated as independent PSM/language proposals;
            # other adapters receive the same complete run set once.
            if isinstance(adapter, TesseractOfflineAdapter):
                profiles = (
                    ("psm7-eng", 7, ("eng",)),
                    ("psm13-eng", 13, ("eng",)),
                    ("psm7-jpn-cjk", 7, ("jpn", "chi_sim")),
                    ("psm7-ara", 7, ("ara",)),
                )
            else:
                profiles = ((adapter.name, None, None),)
            for profile_name, psm, languages in profiles:
                start = time.perf_counter()
                first_payloads: list[bytes] = []
                second_payloads: list[bytes] = []
                texts: list[str] = []
                hypothesis_sequences: list[str] = []
                hypothesis_ids: list[str] = []
                run_spans: list[str] = []
                unsupported: list[str] = []
                statuses: list[str] = []
                run_input_hashes: list[str] = []
                # Preserve row-level proposal alternatives keyed by the
                # measured geometry hypothesis.  Flattened logical strings
                # are useful for coverage reporting, but cannot explain why
                # one pitch/phase owns the source better than another.
                joint_row_proposals: dict[str, dict[int, tuple[str, ...]]] = {}
                row_proposal_evidence: list[dict[str, Any]] = []
                try:
                    with tempfile.TemporaryDirectory(prefix="lateletter-run-input-") as run_root:
                        variants = input_variants or (("unresolved", {"runs": ({"run_id": "unresolved", "binary_run_mask": [], "run_strip_png_base64": ""},)}),)
                        profile_budget_seconds = None
                        if adapter_budgets_seconds:
                            for budget_name in (profile_name, adapter.name):
                                if budget_name in adapter_budgets_seconds:
                                    profile_budget_seconds = float(adapter_budgets_seconds[budget_name])
                                    break
                        total_profile_runs = sum(
                            len(tuple(item.get("runs", ()))) or 1
                            for _variant_id, item in variants
                        )
                        tesseract_timeout_seconds = None
                        if psm is not None and profile_budget_seconds is not None:
                            tesseract_timeout_seconds = max(
                                0.05,
                                min(
                                    1.0,
                                    profile_budget_seconds / max(1, total_profile_runs * len(profiles)) * 0.20,
                                ),
                            )
                        for variant_id, variant_input in variants:
                            hypothesis_ids.append(str(variant_id))
                            variant_geometry = dict(geometry)
                            if variant_input.get("mixed_width_display"):
                                variant_geometry["mixed_width_display"] = dict(variant_input["mixed_width_display"])
                            variant_geometry["hypothesis_id"] = variant_id
                            variant_geometry["hypothesis"] = dict(variant_input.get("provenance", {}).get("hypothesis", {}))
                            variant_candidates: list[tuple[int, tuple[str, ...]]] = []
                            variant_rows: dict[int, tuple[str, ...]] = {}
                            variant_row_proposals: dict[int, list[dict[str, Any]]] = {}
                            for run_index, run in enumerate(variant_input.get("runs", ())):
                                run_source = dict(source)
                                run_geometry = dict(variant_geometry)
                                if run.get("run_strip_png_base64"):
                                    run_bytes = base64.b64decode(run["run_strip_png_base64"])
                                    run_path = Path(run_root) / f"{variant_id}-run-{run_index:04d}.png"
                                    run_path.write_bytes(run_bytes)
                                    run_source.update(
                                        {
                                            "path": str(run_path),
                                            "source_sha256": sha256_bytes(run_bytes),
                                            "run_id": run["run_id"],
                                            "run_source_bounds": run["source_bounds"],
                                            "component_ids": list(run.get("component_ids", ())),
                                            "run_color_stats": dict(run.get("run_color_stats") or {}),
                                            "anchor_evidence": dict(run.get("anchor_evidence") or {}),
                                        }
                                    )
                                    run_input_hashes.append(sha256_bytes(canonical_bytes(run)))
                                    run_geometry["run_mask"] = {
                                        "authority": "geometry_hypothesis_run" if variant_id != "authoritative" else "geometry_proven_run",
                                        "grapheme_complete": True,
                                        "pixels": run["binary_run_mask"],
                                        "run_id": run["run_id"],
                                        "source_bounds": run["source_bounds"],
                                        "mask_sha256": run["binary_run_mask_sha256"],
                                        "component_ids": list(run.get("component_ids", ())),
                                        "measured_advances": run.get("measured_advances", []),
                                        "anchor_evidence": dict(run.get("anchor_evidence") or {}),
                                    }
                                    run_geometry["geometry_hash"] = sha256_bytes(canonical_bytes({"base": variant_geometry, "run_id": run["run_id"]}))
                                    run_source["geometry_hash"] = run_geometry["geometry_hash"]
                                else:
                                    run_source["run_id"] = "unresolved"
                                if psm is not None:
                                    run_source["tesseract_psm"] = psm
                                    run_source["tesseract_languages"] = list(languages or ())
                                    if tesseract_timeout_seconds is not None:
                                        run_source["tesseract_timeout_seconds"] = tesseract_timeout_seconds
                                if isinstance(adapter, StructuralUnicodeRowAdapter) and profile_budget_seconds is not None:
                                    run_source["structural_run_budget_seconds"] = max(
                                        0.05,
                                        profile_budget_seconds / max(1, total_profile_runs) * 0.45,
                                    )
                                first = adapter.propose(run_source, run_geometry, components, environment_lock)
                                second = (
                                    adapter.propose(run_source, run_geometry, components, environment_lock)
                                    if deterministic_replay
                                    else first
                                )
                                first_payloads.append(canonical_bytes(first.to_dict()))
                                second_payloads.append(canonical_bytes(second.to_dict()))
                                # ``top_k`` controls benchmark reporting, not
                                # the evidence available to joint alignment.
                                # Preserve the adapter's bounded beam so a
                                # valid split-cell sequence cannot disappear
                                # before geometry/text scoring.
                                adapter_beam = int(getattr(adapter, "beam_width", 8))
                                # Keep the public report cap separate from
                                # inference evidence.  Structural mixed-width
                                # rows intentionally emit a larger bounded
                                # diversity surface; truncating it to 32 made
                                # Unicode/ASCII lookalikes disappear before
                                # joint alignment could compare them.
                                inference_cap = 1024 if isinstance(adapter, StructuralUnicodeRowAdapter) else 32
                                # Structural adapters already emit a bounded,
                                # deterministic proposal surface.  Preserve
                                # that complete surface for joint decoding;
                                # the public benchmark `top_k` is reporting
                                # only and must not erase row alternatives.
                                proposal_limit = (
                                    None
                                    if isinstance(adapter, StructuralUnicodeRowAdapter)
                                    else max(top_k, min(inference_cap, adapter_beam * 4))
                                )
                                run_texts = _proposal_texts(first, top_k=proposal_limit)
                                row_index = int(run.get("row_index", run_index))
                                variant_candidates.append((row_index, run_texts))
                                variant_rows[row_index] = run_texts
                                variant_row_proposals.setdefault(row_index, []).append(
                                    {
                                        "run_id": str(run.get("run_id", f"run-{run_index:04d}")),
                                        "proposals": list(run_texts),
                                        "run_input_hash": run_input_hashes[-1] if run_input_hashes else None,
                                    }
                                )
                                run_spans.extend(proposal.run_id for proposal in first.proposals if proposal.run_id)
                                unsupported.extend(first.rejection_codes)
                                statuses.append(first.status)
                            joint_row_proposals[str(variant_id)] = variant_rows
                            row_proposal_evidence.append(
                                {
                                    "hypothesis_id": str(variant_id),
                                    "rows": [
                                        {
                                            "row_index": int(row_index),
                                            "runs": list(run_items),
                                            "run_id": str(run_items[0].get("run_id", "")) if run_items else "",
                                            "proposals": list(variant_rows.get(row_index, ())),
                                        }
                                        for row_index, run_items in sorted(variant_row_proposals.items())
                                    ],
                                }
                            )
                            hypothesis_sequences.extend(_compose_run_texts(variant_candidates, top_k=top_k))
                    deterministic = first_payloads == second_payloads
                    # ``canonical_bytes`` intentionally rejects raw bytes.  Hash
                    # the ordered payload byte stream directly so the repeat
                    # receipt remains deterministic without serializing binary
                    # proposal artifacts as JSON.
                    repeat_hash = sha256_bytes(b"".join(first_payloads))
                    if not deterministic:
                        repeated_failures.append(f"{fixture_id}:{profile_name}")
                    # Compose each geometry hypothesis independently.  Mixing
                    # rows from different pitch/phase hypotheses would create
                    # synthetic logical strings and would turn the proposal
                    # benchmark into a false joint-decoder result.
                    texts = list(dict.fromkeys(hypothesis_sequences))[: max(top_k, 1)]
                    union.extend(texts)
                    joint_alignment = None
                    joint_decoder = None
                    if hypothesis_inputs and joint_row_proposals:
                        # This is deliberately diagnostic.  The alignment
                        # report can rank evidence, but it cannot authorize a
                        # geometry decision or create candidate TXT.
                        joint_alignment = jointly_score_geometry_hypotheses(
                            hypothesis_inputs,
                            joint_row_proposals,
                            # ``top_k`` is the public benchmark/reporting
                            # cap.  Joint inference must see the complete
                            # bounded adapter beam retained above, otherwise
                            # a top-1 fallback silently becomes the only
                            # evidence available for geometry/text scoring.
                            top_k=max(
                                top_k,
                                min(
                                    1024 if isinstance(adapter, StructuralUnicodeRowAdapter) else 32,
                                    int(getattr(adapter, "beam_width", 8))
                                    * (16 if isinstance(adapter, StructuralUnicodeRowAdapter) else 4),
                                ),
                            ),
                        )
                        # The scorer remains a diagnostic compatibility
                        # surface.  The joint decoder consumes the same
                        # measured evidence and may expose only a review
                        # candidate; it still cannot write candidate.txt.
                        joint_decoder = jointly_decode_geometry_text(
                            hypothesis_inputs,
                            joint_row_proposals,
                            top_k=max(
                                top_k,
                                min(
                                    1024 if isinstance(adapter, StructuralUnicodeRowAdapter) else 32,
                                    int(getattr(adapter, "beam_width", 8))
                                    * (16 if isinstance(adapter, StructuralUnicodeRowAdapter) else 4),
                                ),
                            ),
                            scored_report=joint_alignment,
                        )
                    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
                    budget_seconds = None
                    if adapter_budgets_seconds:
                        for budget_name in (profile_name, adapter.name):
                            if budget_name in adapter_budgets_seconds:
                                budget_seconds = float(adapter_budgets_seconds[budget_name])
                                break
                    budget_exceeded = budget_seconds is not None and elapsed_ms > budget_seconds * 1000.0
                    if budget_exceeded:
                        budget_failures.append(f"{fixture_id}:{profile_name}")
                    retained_state_count = sum(
                        len(run_item.get("proposals", ()))
                        for row_item in row_proposal_evidence
                        for row in row_item.get("rows", ())
                        for run_item in row.get("runs", ())
                    )
                    adapter_records.append(
                        {
                            "adapter": profile_name,
                            "version": adapter.version,
                            "top_k_logical_sequences": texts[:top_k],
                            "proposed_logical_order": texts[:top_k],
                            "run_spans": sorted(set(run_spans)),
                            "run_count": sum(len(item.get("runs", ())) for _, item in input_variants),
                            "run_input_hashes": run_input_hashes,
                            "repeat_run_hash": repeat_hash,
                            "deterministic": deterministic,
                            "runtime_ms": elapsed_ms,
                            "budget_seconds": budget_seconds,
                            "budget_exceeded": budget_exceeded,
                            "retained_proposal_state_count": retained_state_count,
                            "determinism_replay_performed": deterministic_replay,
                            "memory_max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            "unsupported_status": sorted(set(unsupported)),
                            "status": "proposal_only" if any(item == "proposal_only" for item in statuses) else "rejected",
                            "geometry_status": geometry_status,
                            "geometry_rejection_codes": geometry_rejection_codes,
                            "recognition_input_hash": recognition_input_hash,
                            "proposal_hypothesis_count": len(input_variants) if geometry_status != "proved" else 0,
                            "proposal_hypothesis_ids": hypothesis_ids if geometry_status != "proved" else [],
                            "row_proposals": row_proposal_evidence,
                            "joint_alignment": joint_alignment,
                            "joint_decoder": joint_decoder,
                        }
                    )
                except Exception as exc:  # a proposal adapter must fail closed
                    adapter_records.append(
                        {
                            "adapter": profile_name,
                            "version": adapter.version,
                            "top_k_logical_sequences": [],
                            "proposed_logical_order": [],
                            "run_spans": [],
                            "run_count": sum(len(item.get("runs", ())) for _, item in input_variants),
                            "run_input_hashes": [],
                            "repeat_run_hash": None,
                            "deterministic": True,
                            "runtime_ms": round((time.perf_counter() - start) * 1000, 3),
                            "budget_seconds": None,
                            "budget_exceeded": False,
                            "retained_proposal_state_count": 0,
                            "determinism_replay_performed": deterministic_replay,
                            "memory_max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            "unsupported_status": [f"adapter_exception:{type(exc).__name__}"],
                            "error": f"{type(exc).__name__}: {exc}",
                            "status": "rejected",
                            "geometry_status": geometry_status,
                            "geometry_rejection_codes": geometry_rejection_codes,
                            "recognition_input_hash": recognition_input_hash,
                            "row_proposals": [],
                            "joint_alignment": None,
                            "joint_decoder": None,
                        }
                    )
        logical_sequences = list(dict.fromkeys(union))
        target = ""
        transcript_path = fixture.get("transcript")
        if transcript_path:
            target_path = Path(str(transcript_path))
            if root_path is not None and not target_path.is_absolute():
                target_path = root_path / target_path
            if target_path.exists():
                target = unicodedata.normalize("NFC", target_path.read_text(encoding="utf-8").rstrip("\n"))
        exact_top_k = bool(target and target in logical_sequences[:top_k])
        expected_outcome = str(fixture.get("expected_outcome", "positive"))
        unique_resolution = len(logical_sequences) == 1 and bool(logical_sequences)
        if expected_outcome == "positive" and not exact_top_k:
            positive_missing.append(fixture_id)
        if expected_outcome == "rejected" and unique_resolution:
            false_unique.append(fixture_id)
        matrix_source_hash = str(source.get("source_sha256", ""))
        if not is_sha256(matrix_source_hash) and source_path.exists():
            matrix_source_hash = sha256_file(source_path)
        coverage_matrix = _coverage_rank_matrix(
            target,
            adapter_records,
            fixture_id=fixture_id,
            source_hash=matrix_source_hash,
            geometry_status=geometry_status,
            geometry_rejection_codes=geometry_rejection_codes,
            top_k=top_k,
        )
        coverage_matrices.append(coverage_matrix)
        results.append(
            {
                "fixture": fixture_id,
                "expected_outcome": expected_outcome,
                "target_evaluated_after_proposals": bool(target),
                "exact_nfc_target_in_top_k": exact_top_k,
                "proposed_logical_order": logical_sequences,
                "boxes_or_run_spans": [span for item in adapter_records for span in item["run_spans"]],
                "adapters": adapter_records,
                "unsupported": not logical_sequences,
                "false_unique_resolution": expected_outcome == "rejected" and unique_resolution,
                "geometry_status": geometry_status,
                "geometry_rejection_codes": geometry_rejection_codes,
                "recognition_input_hash": recognition_input_hash,
                "coverage_rank_matrix": coverage_matrix,
            }
        )
    passed = not positive_missing and not false_unique and not repeated_failures and not budget_failures and all(
        item["exact_nfc_target_in_top_k"] for item in results if item["expected_outcome"] == "positive"
    )
    return {
        "status": "passed" if passed else "blocked_release_coverage",
        "top_k": top_k,
        "fixture_count": len(results),
        "results": results,
        "coverage_rank_matrix": coverage_matrices,
        "positive_missing": positive_missing,
        "false_unique_negative_fixtures": false_unique,
        "nondeterministic_adapters": repeated_failures,
        "budget_failures": budget_failures,
        "determinism_replay_performed": deterministic_replay,
        "adapter_budgets_seconds": dict(adapter_budgets_seconds or {}),
        "remote_proposals_allowed": False,
        "ground_truth_passed_to_adapters": False,
        "reason": "proposal coverage only; no candidate selection performed" if passed else "offline ensemble does not cover the release gate",
    }
