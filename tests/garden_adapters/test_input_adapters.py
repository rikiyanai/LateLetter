from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lateletter.garden.input_adapters import (
    InputEnvelope,
    InputModality,
    InputNormalizationError,
    normalize_input,
    semantic_bytes,
)
from lateletter.garden.world.commands import CommandKind


ROOT = Path(__file__).parents[2]
VECTORS_PATH = ROOT / "tests" / "fixtures" / "garden_adapter_vectors.json"
NODE_TEST = ROOT / "tests" / "garden_adapters" / "test_garden_input.mjs"


def _vectors() -> dict:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _normalize(vector: dict, modality: str, *, metadata: dict | None = None):
    source = vector["inputs"][modality]
    intent = {key: value for key, value in source.items() if key != "metadata"}
    intent["target_id"] = vector["target_id"]
    intent["args"] = vector["args"]
    return normalize_input(InputEnvelope(
        modality=modality,
        world_id=_vectors()["world_id"],
        sequence=vector["sequence"],
        raw=intent,
        metadata=source.get("metadata", {}) if metadata is None else metadata,
    ))


def test_vectors_cover_the_complete_canonical_action_vocabulary():
    actions = {vector["action"] for vector in _vectors()["vectors"]}
    assert actions == {kind.value for kind in CommandKind}
    assert len(actions) == 15


@pytest.mark.parametrize("vector", _vectors()["vectors"], ids=lambda item: item["action"])
def test_all_modalities_normalize_to_byte_identical_commands(vector):
    commands = [_normalize(vector, modality.value) for modality in InputModality]
    payloads = {semantic_bytes(value) for value in commands}

    assert len(payloads) == 1
    assert commands[0].kind.value == vector["action"]
    assert commands[0].target_id == vector["target_id"]
    assert dict(commands[0].args) == vector["args"]


def test_modality_metadata_does_not_affect_semantic_bytes():
    vector = next(item for item in _vectors()["vectors"] if item["action"] == "place")
    baseline = _normalize(vector, "touch", metadata={"pointer_id": 1, "screen_x": 20})
    changed = _normalize(vector, "touch", metadata={
        "pointer_id": 999,
        "screen_x": 9000,
        "device": "unrelated diagnostic value",
    })
    assert semantic_bytes(baseline) == semantic_bytes(changed)


@pytest.mark.parametrize(
    ("modality", "raw", "message"),
    [
        ("gamepad", {"control": "back"}, "unsupported input modality"),
        ("touch", {}, "touch intent requires control"),
        ("mouse", {"control": "teleport"}, "unknown garden action"),
        ("terminal", {"command": "pan", "args": {}}, "pan requires dx and/or dy"),
        ("browser_keyboard", {"binding": "feed", "args": []}, "args must be a mapping"),
    ],
)
def test_invalid_raw_intents_fail_closed(modality, raw, message):
    with pytest.raises(InputNormalizationError, match=message):
        normalize_input(InputEnvelope(
            modality=modality,
            world_id="invalid-vector-world",
            sequence=1,
            raw=raw,
        ))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_python_and_browser_modules_emit_identical_canonical_bytes():
    result = subprocess.run(
        [shutil.which("node") or "node", str(NODE_TEST), "--emit"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    browser_payloads = json.loads(result.stdout)
    python_payloads = [
        semantic_bytes(_normalize(vector, "touch")).decode("utf-8")
        for vector in _vectors()["vectors"]
    ]
    assert browser_payloads == python_payloads
