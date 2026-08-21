"""Cross-process deterministic PRNG and domain-separated seed derivation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TypeVar

from .model import canonical_json_bytes


_MASK32 = 0xFFFF_FFFF
_ZERO_REPLACEMENT = 0x6D2B_79F5
T = TypeVar("T")


def derive_seed(root_seed: int | str | bytes, *domain: object) -> int:
    """Derive one non-zero uint32 seed from a stable root and domain path."""
    root = root_seed.hex() if isinstance(root_seed, bytes) else str(root_seed)
    digest = hashlib.sha256(
        canonical_json_bytes(["lateletter-garden-rng-v1", root, *domain])
    ).digest()
    value = int.from_bytes(digest[:4], "big") & _MASK32
    return value or _ZERO_REPLACEMENT


class DeterministicRNG:
    """Specified xorshift32 stream using unsigned 32-bit operations."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        value = int(seed) & _MASK32
        self._state = value or _ZERO_REPLACEMENT

    @property
    def state(self) -> int:
        return self._state

    def next_u32(self) -> int:
        x = self._state
        x ^= (x << 13) & _MASK32
        x ^= x >> 17
        x ^= (x << 5) & _MASK32
        self._state = x & _MASK32
        return self._state

    def randbelow(self, stop: int) -> int:
        """Return an unbiased integer in ``range(stop)``."""
        if stop <= 0:
            raise ValueError("stop must be positive")
        limit = (1 << 32) - ((1 << 32) % stop)
        while True:
            value = self.next_u32()
            if value < limit:
                return value % stop

    def randint(self, start: int, stop: int) -> int:
        if stop < start:
            raise ValueError("stop must be >= start")
        return start + self.randbelow(stop - start + 1)

    def choice(self, values: Sequence[T]) -> T:
        if not values:
            raise IndexError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]

    def split(self, *domain: object) -> DeterministicRNG:
        return DeterministicRNG(derive_seed(self._state, *domain))
