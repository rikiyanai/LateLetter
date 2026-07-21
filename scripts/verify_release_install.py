#!/usr/bin/env python3
"""Verify installed package resources and the tracked public demo bundle."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from lateletter.bundle import read_bundle, verify_checksum
from lateletter.garden.astronomy import load_bright_star_catalog
from lateletter.garden.atlas import load_atlas
from lateletter.garden.program import parse_program
from lateletter.question_selector import QuestionSelector
from lateletter.sealed import open_garden_program, verify_bundle_hmac


PUBLIC_DEMO_PASSPHRASE = "garden-biscuit-2026"


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    root_bundle = repository_root / "sealed_demo.lateletter"
    public_bundle = repository_root / "public_letters" / "to-a-friend.lateletter"
    if root_bundle.read_bytes() != public_bundle.read_bytes():
        raise RuntimeError("tracked public demo differs from the canonical sealed demo")

    package = files("lateletter")
    question_data = package.joinpath("data")
    QuestionSelector.load(
        Path(str(question_data.joinpath("question_bank_seed.v0.json"))),
        Path(str(question_data.joinpath("question_bank_domain_pools.v0.json"))),
    )
    load_atlas()
    stars = load_bright_star_catalog()
    if len(stars.get("stars", ())) != 24:
        raise RuntimeError("installed bright-star catalog is incomplete")
    provenance = files("lateletter.garden").joinpath(
        "data/astronomy-provenance.v1.json"
    )
    if not provenance.is_file():
        raise RuntimeError("installed astronomy provenance is missing")

    bundle = read_bundle(public_bundle)
    if not verify_checksum(bundle):
        raise RuntimeError("public demo checksum failed")
    if not verify_bundle_hmac(bundle, PUBLIC_DEMO_PASSPHRASE):
        raise RuntimeError("public demo HMAC failed")
    if bundle.garden_program is None:
        raise RuntimeError("public demo has no encrypted Garden program")
    program = parse_program(open_garden_program(
        PUBLIC_DEMO_PASSPHRASE, bundle.garden_program,
    ), known_letter_ids={message.id for message in bundle.messages})
    if (len(program.entities), len(program.animals), len(program.events)) != (4, 1, 5):
        raise RuntimeError("public demo Garden program shape changed unexpectedly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
