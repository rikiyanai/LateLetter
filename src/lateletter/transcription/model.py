"""Immutable, hash-addressed intermediate records for transcription."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

from .hashing import require_sha256, safe_relative_path, sha256_bytes
from .schema import canonical_bytes, record_to_dict
from .versions import MODULE_VERSION, SCHEMA_VERSION


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-shaped values so ``frozen=True`` is deep."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return _freeze(value or {})


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    return tuple(value)


@dataclass(frozen=True)
class EvidenceRecord:
    """Common envelope.  Subclasses add only evidence owned by their phase."""

    schema_version: str = SCHEMA_VERSION
    producer: str = MODULE_VERSION
    input_hashes: Mapping[str, str] = field(default_factory=dict)
    configuration: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    output_hash: str = ""

    RECORD_TYPE: ClassVar[str] = "evidence"

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version!r}")
        if not self.producer:
            raise ValueError("producer is required")
        normalized_hashes = _mapping(self.input_hashes)
        if not normalized_hashes:
            raise ValueError("input_hashes must bind at least one upstream artifact")
        for name, value in normalized_hashes.items():
            require_sha256(value, field=f"input_hashes.{name}")
        object.__setattr__(self, "input_hashes", normalized_hashes)
        object.__setattr__(self, "configuration", _mapping(self.configuration))
        object.__setattr__(self, "provenance", _mapping(self.provenance))
        object.__setattr__(self, "rejection_reasons", tuple(_freeze(item) for item in self.rejection_reasons))
        digest = sha256_bytes(canonical_bytes(record_to_dict(self, include_output_hash=False)))
        if self.output_hash and self.output_hash != digest:
            raise ValueError("output_hash does not match canonical record content")
        object.__setattr__(self, "output_hash", digest)

    def to_dict(self) -> dict[str, Any]:
        return record_to_dict(self)

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceRecord":
        from .schema import record_from_dict

        return record_from_dict(cls, payload)


@dataclass(frozen=True)
class SourceReceipt(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "source_receipt"
    source_path: str = ""
    source_sha256: str = ""
    media_type: str = "image/png"
    width: int = 0
    height: int = 0
    source_kind: str = "rendered_text_art"

    def __post_init__(self) -> None:
        safe_relative_path(self.source_path, field="source_path")
        require_sha256(self.source_sha256, field="source_sha256")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("source dimensions must be positive")
        super().__post_init__()


@dataclass(frozen=True)
class NormalizationReceipt(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "normalization_receipt"
    source_sha256: str = ""
    normalized_sha256: str = ""
    method: str = "identity"
    foreground: tuple[int, int, int, int] | None = None
    background: tuple[int, int, int, int] | None = None
    guide_removal: str = "none"
    operations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_sha256(self.source_sha256, field="source_sha256")
        require_sha256(self.normalized_sha256, field="normalized_sha256")
        object.__setattr__(self, "operations", _tuple(self.operations))
        super().__post_init__()


@dataclass(frozen=True)
class GeometryDecision(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "geometry_decision"
    mode: str = "unresolved"
    confidence: float = 0.0
    alternatives: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    evidence_hash: str = ""
    geometry_hash: str = ""
    rejection_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.mode not in {"fixed_lattice", "shaped_runs", "unresolved"}:
            raise ValueError("geometry mode must be fixed_lattice, shaped_runs, or unresolved")
        if not 0 <= self.confidence <= 1:
            raise ValueError("geometry confidence must be between 0 and 1")
        for name, value in (("evidence_hash", self.evidence_hash), ("geometry_hash", self.geometry_hash)):
            if value:
                require_sha256(value, field=name)
        object.__setattr__(self, "alternatives", tuple(_freeze(item) for item in self.alternatives))
        object.__setattr__(self, "rejection_codes", _tuple(self.rejection_codes))
        super().__post_init__()


@dataclass(frozen=True)
class RowBand(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "row_band"
    row_index: int = 0
    y0: float = 0.0
    y1: float = 0.0
    baseline: float = 0.0
    confidence: float = 0.0


@dataclass(frozen=True)
class CellLattice(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "cell_lattice"
    rows: int = 0
    columns: int = 0
    origin_x: float = 0.0
    origin_y: float = 0.0
    advance_x: float = 0.0
    line_height: float = 0.0
    phase: tuple[float, float] = (0.0, 0.0)
    boundary_intersections: int = 0
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.columns <= 0 or self.advance_x <= 0 or self.line_height <= 0:
            raise ValueError("lattice dimensions and advances must be positive")
        if not 0 <= self.confidence <= 1:
            raise ValueError("lattice confidence must be between 0 and 1")
        super().__post_init__()


@dataclass(frozen=True)
class RunAnchor(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "run_anchor"
    row_index: int = 0
    start_x: float = 0.0
    end_x: float = 0.0
    baseline: float = 0.0
    direction: str = "ltr"
    advance: float = 0.0
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.end_x < self.start_x or self.advance < 0:
            raise ValueError("run anchor bounds are invalid")
        if self.direction not in {"ltr", "rtl", "ttb"}:
            raise ValueError("run direction must be ltr, rtl, or ttb")
        super().__post_init__()


@dataclass(frozen=True)
class InkComponent(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "ink_component"
    component_id: str = ""
    x0: int = 0
    y0: int = 0
    x1: int = 0
    y1: int = 0
    mask_sha256: str = ""
    edge_contacts: tuple[str, ...] = field(default_factory=tuple)
    parent_component_id: str | None = None
    row_indices: tuple[int, ...] = field(default_factory=tuple)
    candidate_row_indices: tuple[int, ...] = field(default_factory=tuple)
    candidate_run_ids: tuple[str, ...] = field(default_factory=tuple)
    ignored_pixel_evidence: Mapping[str, Any] = field(default_factory=dict)
    clipped: bool = False
    substantive: bool = True

    def __post_init__(self) -> None:
        if not self.component_id or self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("invalid ink component bounds or id")
        require_sha256(self.mask_sha256, field="mask_sha256")
        object.__setattr__(self, "edge_contacts", _tuple(self.edge_contacts))
        object.__setattr__(self, "row_indices", tuple(int(item) for item in self.row_indices))
        object.__setattr__(self, "candidate_row_indices", tuple(int(item) for item in self.candidate_row_indices))
        object.__setattr__(self, "candidate_run_ids", _tuple(self.candidate_run_ids))
        object.__setattr__(self, "ignored_pixel_evidence", _mapping(self.ignored_pixel_evidence))
        super().__post_init__()


@dataclass(frozen=True)
class GraphemeCandidate(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "grapheme_candidate"
    text: str = ""
    normalized_text: str = ""
    codepoints: tuple[str, ...] = field(default_factory=tuple)
    display_width: int | None = None
    confidence: float = 0.0
    component_ids: tuple[str, ...] = field(default_factory=tuple)
    alternatives: tuple[str, ...] = field(default_factory=tuple)
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.text and not self.rejection_reasons:
            raise ValueError("a grapheme candidate needs text or a rejection reason")
        if not 0 <= self.confidence <= 1:
            raise ValueError("candidate confidence must be between 0 and 1")
        object.__setattr__(self, "codepoints", _tuple(self.codepoints))
        object.__setattr__(self, "component_ids", _tuple(self.component_ids))
        object.__setattr__(self, "alternatives", _tuple(self.alternatives))
        super().__post_init__()


@dataclass(frozen=True)
class RecognitionProposal(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "recognition_proposal"
    proposal_id: str = ""
    adapter: str = ""
    adapter_version: str = ""
    model_hashes: Mapping[str, str] = field(default_factory=dict)
    candidates: tuple[GraphemeCandidate, ...] = field(default_factory=tuple)
    run_id: str | None = None
    quarantined_remote: bool = False

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.adapter:
            raise ValueError("proposal id and adapter are required")
        for name, value in self.model_hashes.items():
            require_sha256(value, field=f"model_hashes.{name}")
        object.__setattr__(self, "model_hashes", _mapping(self.model_hashes))
        object.__setattr__(
            self,
            "candidates",
            tuple(
                item if isinstance(item, GraphemeCandidate) else GraphemeCandidate.from_dict(item)
                for item in self.candidates
            ),
        )
        super().__post_init__()


@dataclass(frozen=True)
class VisualRun(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "visual_run"
    run_id: str = ""
    logical_start: int = 0
    logical_end: int = 0
    text: str = ""
    direction: str = "ltr"
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    advances: tuple[float, ...] = field(default_factory=tuple)
    visual_order: tuple[int, ...] = field(default_factory=tuple)
    grapheme_spans: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    font_fallback: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.logical_end < self.logical_start:
            raise ValueError("visual run logical bounds are invalid")
        if self.direction not in {"ltr", "rtl", "ttb"}:
            raise ValueError("visual run direction must be ltr, rtl, or ttb")
        object.__setattr__(self, "advances", tuple(float(item) for item in self.advances))
        object.__setattr__(self, "visual_order", tuple(int(item) for item in self.visual_order))
        object.__setattr__(self, "grapheme_spans", tuple(_freeze(item) for item in self.grapheme_spans))
        object.__setattr__(self, "font_fallback", _tuple(self.font_fallback))
        super().__post_init__()


@dataclass(frozen=True)
class OwnershipAssignment(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "ownership_assignment"
    component_id: str = ""
    owner_kind: str = "unresolved"
    owner_id: str | None = None
    confidence: float = 0.0
    rationale: str = ""
    alternatives: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.owner_kind not in {"grapheme", "run", "ignored", "unresolved"}:
            raise ValueError("invalid ownership kind")
        if self.owner_kind in {"grapheme", "run"} and not self.owner_id:
            raise ValueError("owned component requires owner_id")
        object.__setattr__(self, "alternatives", _tuple(self.alternatives))
        super().__post_init__()


@dataclass(frozen=True)
class CandidateBundle(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "candidate_bundle"
    source_hash: str = ""
    normalized_source_hash: str = ""
    geometry_hash: str = ""
    component_hash: str = ""
    proposal_hash: str = ""
    logical_txt_hash: str = ""
    visual_layout_hash: str = ""
    ownership_hash: str = ""
    environment_lock_hash: str = ""
    gate_report_hash: str = ""
    candidate_txt_path: str = ""
    visual_layout_path: str = ""

    def __post_init__(self) -> None:
        for name in (
            "source_hash", "normalized_source_hash", "geometry_hash", "component_hash",
            "proposal_hash", "logical_txt_hash", "visual_layout_hash", "ownership_hash",
            "environment_lock_hash", "gate_report_hash",
        ):
            require_sha256(getattr(self, name), field=name)
        safe_relative_path(self.candidate_txt_path, field="candidate_txt_path")
        safe_relative_path(self.visual_layout_path, field="visual_layout_path")
        super().__post_init__()

    @property
    def bound_hashes(self) -> dict[str, str]:
        return {
            name: getattr(self, name)
            for name in (
                "source_hash", "normalized_source_hash", "geometry_hash", "component_hash",
                "proposal_hash", "logical_txt_hash", "visual_layout_hash", "ownership_hash",
                "environment_lock_hash", "gate_report_hash",
            )
        }


@dataclass(frozen=True)
class GateReport(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "gate_report"
    passed: bool = False
    checks: Mapping[str, bool] = field(default_factory=dict)
    counts: Mapping[str, int] = field(default_factory=dict)
    rejection_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", _mapping({str(key): bool(value) for key, value in self.checks.items()}))
        object.__setattr__(self, "counts", _mapping({str(key): int(value) for key, value in self.counts.items()}))
        object.__setattr__(self, "rejection_codes", _tuple(self.rejection_codes))
        super().__post_init__()


@dataclass(frozen=True)
class ComparisonReceipt(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "comparison_receipt"
    source_hash: str = ""
    candidate_bundle_hash: str = ""
    artifacts: Mapping[str, str] = field(default_factory=dict)
    raster_diff_pixels: int | None = None
    structural_passed: bool = False
    source_pixels_used_in_candidate: bool = False
    rejection_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_sha256(self.source_hash, field="source_hash")
        require_sha256(self.candidate_bundle_hash, field="candidate_bundle_hash")
        for name, value in self.artifacts.items():
            require_sha256(value, field=f"artifacts.{name}")
        object.__setattr__(self, "artifacts", _mapping(self.artifacts))
        object.__setattr__(self, "rejection_codes", _tuple(self.rejection_codes))
        super().__post_init__()


@dataclass(frozen=True)
class OperatorReviewReceipt(EvidenceRecord):
    RECORD_TYPE: ClassVar[str] = "operator_review_receipt"
    candidate_bundle_hash: str = ""
    operator_verdict: str = "pending"
    layout_parity: str = "pending"
    human_visual_parity: str = "pending"
    raster_parity: str = "not_run"
    reviewed_artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        require_sha256(self.candidate_bundle_hash, field="candidate_bundle_hash")
        if self.operator_verdict not in {"pending", "approved", "rejected"}:
            raise ValueError("operator_verdict must be pending, approved, or rejected")
        for name, value in self.reviewed_artifact_hashes.items():
            require_sha256(value, field=f"reviewed_artifact_hashes.{name}")
        object.__setattr__(self, "reviewed_artifact_hashes", _mapping(self.reviewed_artifact_hashes))
        super().__post_init__()
