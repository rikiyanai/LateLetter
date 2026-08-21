from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from lateletter.garden.world.rng import DeterministicRNG, derive_seed


def test_xorshift32_known_vector():
    rng = DeterministicRNG(0x12345678)
    assert [rng.next_u32() for _ in range(5)] == [
        2274908837,
        358294691,
        1210119364,
        2176035992,
        1882851208,
    ]


def test_domain_streams_are_repeatable_and_distinct():
    plant = derive_seed("root", "plant", "rose")
    animal = derive_seed("root", "animal", "rabbit")
    assert plant == derive_seed("root", "plant", "rose")
    assert plant != animal
    assert DeterministicRNG(plant).randint(1, 10) == DeterministicRNG(plant).randint(1, 10)


def test_rng_and_stable_id_ignore_python_hash_randomization():
    root = Path(__file__).parents[2]
    script = """
import json
from lateletter.garden.world.model import stable_id
from lateletter.garden.world.rng import DeterministicRNG, derive_seed
rng = DeterministicRNG(derive_seed('root', 'animal', 'rabbit'))
print(json.dumps([stable_id('object', 'rabbit'), [rng.next_u32() for _ in range(4)]]))
"""
    outputs = []
    for hash_seed in ("1", "2", "random"):
        environment = os.environ.copy()
        environment.update({
            "PYTHONHASHSEED": hash_seed,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(root / "src"),
        })
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1] == outputs[2]


def test_randbelow_rejects_invalid_bounds():
    rng = DeterministicRNG(1)
    try:
        rng.randbelow(0)
        assert False, "expected ValueError"
    except ValueError:
        pass
