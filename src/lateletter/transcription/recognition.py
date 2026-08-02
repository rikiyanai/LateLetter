"""Pinned offline recognizer seam and fail-closed adapter inventory."""

from __future__ import annotations

import hashlib
import base64
import json
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
from typing import Any, Mapping, Protocol

import PIL
import numpy as np
import regex
import wcwidth
from PIL import Image, ImageFont

from .hashing import is_sha256, safe_relative_path, sha256_bytes, sha256_file
from .model import GraphemeCandidate, RecognitionProposal
from .schema import canonical_bytes


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
        component_ids=(),
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
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30, env={**os.environ, "TESSDATA_PREFIX": str(tessdata_dir)})
        except (OSError, subprocess.SubprocessError) as exc:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, f"recognizer_execution:{type(exc).__name__}")
        if completed.returncode != 0:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "recognizer_execution_failed")
        text = completed.stdout.rstrip("\n")
        if not text:
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "empty_proposal")
        candidate = _candidate(
            text=text,
            source_hash=source_hash,
            geometry_hash=geometry_hash,
            components_hash=components_hash,
            environment_hash=environment_lock.output_hash,
            confidence=0.25,
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


@dataclass(frozen=True)
class FixedLatticeStructuralAdapter:
    name: str = "fixed-lattice-structural"
    version: str = "1"
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
        if geometry.get("mode") != "fixed_lattice":
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "geometry_mode_mismatch")
        return _unsupported_proposal(self.name, self.version, source, environment_lock, "whole_run_proposal_unavailable")


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
        return CapabilityProfile(
            adapter=f"{self.name}-{self.backend}",
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
    if evidence.get("authority") != "geometry_proven_run":
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
    return tuple(
        tuple(alpha.getpixel((x, y)) > 8 for x in range(alpha.width)) for y in range(alpha.height)
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


def _resize_mask(mask: tuple[tuple[bool, ...], ...], width: int, height: int) -> tuple[tuple[bool, ...], ...]:
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
    raw = image.tobytes()
    return tuple(
        tuple(value > 32 for value in raw[row * image.width : (row + 1) * image.width])
        for row in range(image.height)
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
        try:
            rendered_catalog = _emoji_rendered_catalog(
                str(self.sequence_data_path),
                str(self.font_path),
                int(self.max_sequences),
            )
        except (OSError, TypeError, ValueError):
            return _unsupported_proposal(self.name, self.version, source, environment_lock, "font_strike_unavailable")
        target_height = len(target_rgba) if target_rgba is not None else len(target)
        source_hash, geometry_hash, components_hash = _source_hashes(source)
        run_hash = _mask_hash(target)
        scored: list[dict[str, Any]] = []
        for sequence, rendered, native_advance in rendered_catalog:
            native_width = len(rendered[0])
            for advance in advance_values:
                scale = max(0.75, min(1.25, advance / native_advance))
                scaled = _resize_mask(rendered, round(native_width * scale), target_height)
                residual, union, residual_fraction = _mask_residual(target, scaled)
                score = residual_fraction + abs(native_advance - advance) / max(1.0, advance) * 0.05
                scored.append({
                    "sequence": sequence,
                    "advance": advance,
                    "font_size": 109,
                    "residual_pixels": residual,
                    "union_pixels": union,
                    "residual_fraction": residual_fraction,
                    "score": score,
                    "mask_hash": _mask_hash(scaled),
                })
        scored.sort(key=lambda item: (item["score"], item["sequence"], item["advance"]))
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
        best_visual_hash = best.get("color_mask_hash", best["mask_hash"])
        if ties and any(item.get("color_mask_hash", item["mask_hash"]) == best_visual_hash for item in ties):
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
        return ProposalSet(
            adapter=self.name,
            adapter_version=self.version,
            environment_lock_hash=environment_lock.output_hash,
            proposals=(proposal,),
            supported_scripts=("emoji",),
            status="proposal_only",
        )


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
    lock = build_environment_lock(script_packs=tuple(languages))
    adapters = (
        TesseractOfflineAdapter(executable=executable, version=version.split(" ", 1)[-1] if version != "unavailable" else version),
        FixedLatticeStructuralAdapter(),
        PaddleOCROfflineAdapter(),
        IndependentOfflineAdapter(backend="easyocr"),
        IndependentOfflineAdapter(backend="surya"),
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


def _proposal_texts(result: ProposalSet, *, top_k: int) -> tuple[str, ...]:
    candidates: list[GraphemeCandidate] = []
    for proposal in result.proposals:
        candidates.extend(candidate for candidate in proposal.candidates if candidate.text != "?")
    ordered = sorted(candidates, key=lambda item: (-item.confidence, item.normalized_text, item.text))
    return tuple(dict.fromkeys(candidate.normalized_text for candidate in ordered[:top_k]))


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


def benchmark_offline_ensemble(
    fixtures: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    adapters: tuple[Recognizer, ...],
    environment_lock: EnvironmentLock,
    *,
    root: str | os.PathLike[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Measure deterministic proposal coverage; never selects an answer.

    Ground truth is read only after every adapter has produced its proposals.
    It is used to score the benchmark, never passed into an adapter.
    """

    root_path = Path(root).resolve() if root else None
    results: list[dict[str, Any]] = []
    positive_missing: list[str] = []
    false_unique: list[str] = []
    repeated_failures: list[str] = []
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
                from .geometry import build_recognition_inputs, route_raster_geometry

                geometry_bundle, geometry_decision = route_raster_geometry(source_path)
                geometry_status = geometry_decision.status
                geometry_rejection_codes = list(geometry_decision.rejection_reasons)
                if geometry_decision.mode == "unresolved":
                    geometry = {"mode": "unresolved", "geometry_proven": False, "source_sha256": source.get("source_sha256", "")}
                    components = {}
                else:
                    geometry = dict(geometry_decision.provenance["selected_geometry"])
                    recognition_inputs = build_recognition_inputs(source_path, geometry_bundle, mode=geometry_decision.mode)
                    recognition_input_hash = recognition_inputs["input_hash"]
                    # Every geometry-owned run is retained.  The adapter loop
                    # below materializes each strip and never collapses a
                    # source to runs[0].
                    components = dict(geometry_bundle.component_evidence)
            except (OSError, ValueError) as exc:
                geometry_status = "rejected"
                geometry_rejection_codes = [f"geometry_recovery:{type(exc).__name__}"]
                geometry = {"mode": "unresolved", "geometry_proven": False, "source_sha256": source.get("source_sha256", "")}
                components = {}
        else:
            geometry = dict(fixture.get("geometry", {"mode": fixture.get("expected_geometry_mode", "unresolved")}))
            components = dict(fixture.get("components", {}))
        adapter_records: list[dict[str, Any]] = []
        union: list[str] = []
        run_records = recognition_inputs["runs"] if source_path.exists() and geometry_status == "proved" else []
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
                run_candidates: list[tuple[int, tuple[str, ...]]] = []
                run_spans: list[str] = []
                unsupported: list[str] = []
                statuses: list[str] = []
                run_input_hashes: list[str] = []
                try:
                    with tempfile.TemporaryDirectory(prefix="lateletter-run-input-") as run_root:
                        iterable = run_records or ({"run_id": "unresolved", "binary_run_mask": [], "run_strip_png_base64": ""},)
                        for run_index, run in enumerate(iterable):
                            run_source = dict(source)
                            run_geometry = dict(geometry)
                            if run.get("run_strip_png_base64"):
                                run_bytes = base64.b64decode(run["run_strip_png_base64"])
                                run_path = Path(run_root) / f"run-{run_index:04d}.png"
                                run_path.write_bytes(run_bytes)
                                run_source.update(
                                    {
                                        "path": str(run_path),
                                        "source_sha256": sha256_bytes(run_bytes),
                                        "run_id": run["run_id"],
                                        "run_source_bounds": run["source_bounds"],
                                        "run_color_stats": dict(run.get("run_color_stats") or {}),
                                    }
                                )
                                run_input_hashes.append(sha256_bytes(canonical_bytes(run)))
                                run_geometry["run_mask"] = {
                                    "authority": "geometry_proven_run",
                                    "grapheme_complete": True,
                                    "pixels": run["binary_run_mask"],
                                    "run_id": run["run_id"],
                                    "source_bounds": run["source_bounds"],
                                    "mask_sha256": run["binary_run_mask_sha256"],
                                    "measured_advances": run.get("measured_advances", []),
                                }
                                run_geometry["geometry_hash"] = sha256_bytes(canonical_bytes({"base": geometry, "run_id": run["run_id"]}))
                                run_source["geometry_hash"] = run_geometry["geometry_hash"]
                            else:
                                run_source["run_id"] = "unresolved"
                            if psm is not None:
                                run_source["tesseract_psm"] = psm
                                run_source["tesseract_languages"] = list(languages or ())
                            first = adapter.propose(run_source, run_geometry, components, environment_lock)
                            second = adapter.propose(run_source, run_geometry, components, environment_lock)
                            first_payloads.append(canonical_bytes(first.to_dict()))
                            second_payloads.append(canonical_bytes(second.to_dict()))
                            run_texts = _proposal_texts(first, top_k=top_k)
                            run_candidates.append((int(run.get("row_index", run_index)), run_texts))
                            run_spans.extend(proposal.run_id for proposal in first.proposals if proposal.run_id)
                            unsupported.extend(first.rejection_codes)
                            statuses.append(first.status)
                    deterministic = first_payloads == second_payloads
                    # ``canonical_bytes`` intentionally rejects raw bytes.  Hash
                    # the ordered payload byte stream directly so the repeat
                    # receipt remains deterministic without serializing binary
                    # proposal artifacts as JSON.
                    repeat_hash = sha256_bytes(b"".join(first_payloads))
                    if not deterministic:
                        repeated_failures.append(f"{fixture_id}:{profile_name}")
                    texts = list(_compose_run_texts(run_candidates, top_k=top_k))
                    union.extend(texts)
                    adapter_records.append(
                        {
                            "adapter": profile_name,
                            "version": adapter.version,
                            "top_k_logical_sequences": texts[:top_k],
                            "proposed_logical_order": texts[:top_k],
                            "run_spans": sorted(set(run_spans)),
                            "run_count": len(run_records),
                            "run_input_hashes": run_input_hashes,
                            "repeat_run_hash": repeat_hash,
                            "deterministic": deterministic,
                            "runtime_ms": round((time.perf_counter() - start) * 1000, 3),
                            "memory_max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            "unsupported_status": sorted(set(unsupported)),
                            "status": "proposal_only" if any(item == "proposal_only" for item in statuses) else "rejected",
                            "geometry_status": geometry_status,
                            "geometry_rejection_codes": geometry_rejection_codes,
                            "recognition_input_hash": recognition_input_hash,
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
                            "run_count": len(run_records),
                            "run_input_hashes": [],
                            "repeat_run_hash": None,
                            "deterministic": True,
                            "runtime_ms": round((time.perf_counter() - start) * 1000, 3),
                            "memory_max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            "unsupported_status": [f"adapter_exception:{type(exc).__name__}"],
                            "error": f"{type(exc).__name__}: {exc}",
                            "status": "rejected",
                            "geometry_status": geometry_status,
                            "geometry_rejection_codes": geometry_rejection_codes,
                            "recognition_input_hash": recognition_input_hash,
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
            }
        )
    passed = not positive_missing and not false_unique and not repeated_failures and all(
        item["exact_nfc_target_in_top_k"] for item in results if item["expected_outcome"] == "positive"
    )
    return {
        "status": "passed" if passed else "blocked_release_coverage",
        "top_k": top_k,
        "fixture_count": len(results),
        "results": results,
        "positive_missing": positive_missing,
        "false_unique_negative_fixtures": false_unique,
        "nondeterministic_adapters": repeated_failures,
        "remote_proposals_allowed": False,
        "ground_truth_passed_to_adapters": False,
        "reason": "proposal coverage only; no candidate selection performed" if passed else "offline ensemble does not cover the release gate",
    }
