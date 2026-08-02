#!/usr/bin/env python3
"""Generate the bundled Garden font resource from its upstream source.

What this produces
------------------
One product-owned font file, `web/fonts/lateletter-garden.woff`, plus the SIL
Open Font License text that must travel with it. The output is Literata with
every variable axis PINNED to the runtime contract -- weight 400, optical size
15 -- and subset to printable ASCII, which is the entire repertoire the
`ascii-safe` art profile can contain.

Why pin and subset rather than ship the variable font
-----------------------------------------------------
Two separate reasons, and only the second is about bytes.

The first is correctness. The runtime contract names one exact weight and one
exact size. A variable font can render any weight, so shipping one leaves the
door open for some later stylesheet to ask for 700 and get a face whose glyph
advances differ from the ones the art was measured against. Pinning makes the
contract physically true of the file rather than merely stated in CSS.

The second is size: 955 KB of variable TTF becomes about 25 KB of subset WOFF,
a 97% reduction, on a page a recipient may open on a phone.

Why WOFF rather than WOFF2
--------------------------
WOFF2 needs Brotli, which is not installed in this environment. WOFF uses zlib,
is supported by every browser that supports WOFF2, and costs roughly 10 KB more
here. If Brotli becomes available this script should switch, and the runtime
contract's recorded hash will change with it.

Reproducibility
---------------
The output hash is part of the runtime contract and is asserted by tests, so
this script must stay deterministic. It records the source file's own SHA-256
alongside the output's, because a changed input silently producing a changed
output is exactly the drift the contract exists to catch.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import io

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Upstream source. Kept outside the product tree because it is a ~1 MB review
# input, not a deliverable; only the generated subset is bundled.
DEFAULT_SOURCE = (
    REPOSITORY_ROOT / "docs/visual-review/font-decision/fonts/Literata-var.ttf"
)
DEFAULT_LICENSE_SOURCE = (
    REPOSITORY_ROOT / "docs/visual-review/font-decision/fonts/OFL-literata.txt"
)

OUTPUT_DIR = REPOSITORY_ROOT / "web/fonts"
OUTPUT_FONT = OUTPUT_DIR / "lateletter-garden.woff"
OUTPUT_LICENSE = OUTPUT_DIR / "LICENSE-Literata.txt"

# --- The runtime contract, in one place ------------------------------------
#
# These values are the single source of truth for the bundled resource. The
# atlas declares the same values, the stylesheet paints with them, and tests
# assert all three agree. Changing one here means changing all of them.
CONTRACT_FAMILY = "LateLetter Garden"   # product-owned; cannot collide with a system face
CONTRACT_WEIGHT = 400                   # pinned into the file, not merely requested
CONTRACT_OPTICAL_SIZE = 15              # matches the 15px paint size
CONTRACT_SIZE_PX = 15                   # operator-approved 2026-07-31
CONTRACT_LINE_HEIGHT_PX = 17            # row pitch used by measured placement
CONTRACT_STYLE = "normal"
CONTRACT_LETTER_SPACING = "normal"      # explicit: any tracking would shift advances

# Printable ASCII. The ascii-safe profile is drawn from `|`, `_`, `'`, `/`,
# `\`, `-`, `=`, `~`, `*`, `[` and `]`, all inside this range; the rest of the
# range is admitted so labels and debug text cannot fall back mid-string.
ADMITTED_CODEPOINTS = tuple(range(0x20, 0x7F))


def sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path = DEFAULT_SOURCE) -> dict[str, str]:
    """Generate the bundled font and licence, returning the provenance record.

    :param source: The upstream variable TTF to pin and subset.
    :returns: Mapping of contract fields and hashes, for logging and tests.
    """
    if not source.is_file():
        raise FileNotFoundError(f"upstream font source missing: {source}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Pin every variable axis to the contract values. `inplace=False` keeps
    #    the loaded source untouched so a caller could instance it twice.
    font = TTFont(source)
    axes = {"wght": CONTRACT_WEIGHT}
    available = {axis.axisTag for axis in font["fvar"].axes} if "fvar" in font else set()
    if "opsz" in available:
        axes["opsz"] = CONTRACT_OPTICAL_SIZE
    pinned = instancer.instantiateVariableFont(font, axes, inplace=False)

    # 2. Round-trip through a buffer so the subsetter sees a finished font
    #    rather than a partially instanced one.
    buffer = io.BytesIO()
    pinned.save(buffer)
    buffer.seek(0)

    # 3. Subset to the admitted repertoire.
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]      # keep name records so licence metadata survives
    options.notdef_outline = True  # a visible .notdef beats an invisible failure
    subsetter = subset.Subsetter(options=options)
    # `recalcTimestamp=False` stops fontTools rewriting `head.modified` to the
    # current time during save, which is what makes the output reproducible.
    trimmed = TTFont(buffer, recalcTimestamp=False)
    subsetter.populate(unicodes=ADMITTED_CODEPOINTS)
    subsetter.subset(trimmed)

    # 4. Pin the timestamps before saving.
    #
    #    fontTools stamps `head.modified` with the current time on every save,
    #    which makes the output bytes -- and therefore its SHA-256 -- different
    #    on every run. The hash is part of the runtime contract and is asserted
    #    by tests, so a build that changes it every time would fail constantly
    #    while nothing had actually changed. Carrying the SOURCE font's own
    #    timestamps across makes the output a pure function of its input, which
    #    is the property the contract needs.
    trimmed["head"].created = font["head"].created
    trimmed["head"].modified = font["head"].modified

    # 5. Emit as WOFF. The flavour must be set before saving.
    trimmed.flavor = "woff"
    trimmed.save(OUTPUT_FONT)

    # 6. The OFL requires the licence to travel with the font.
    if DEFAULT_LICENSE_SOURCE.is_file():
        OUTPUT_LICENSE.write_text(
            DEFAULT_LICENSE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8"
        )

    return {
        "family": CONTRACT_FAMILY,
        "weight": str(CONTRACT_WEIGHT),
        "style": CONTRACT_STYLE,
        "size_px": str(CONTRACT_SIZE_PX),
        "line_height_px": str(CONTRACT_LINE_HEIGHT_PX),
        "letter_spacing": CONTRACT_LETTER_SPACING,
        "source_file": source.name,
        "source_sha256": sha256(source),
        "output_file": str(OUTPUT_FONT.relative_to(REPOSITORY_ROOT)),
        "output_sha256": sha256(OUTPUT_FONT),
        "output_bytes": str(OUTPUT_FONT.stat().st_size),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=DEFAULT_SOURCE,
        help="upstream variable TTF to pin and subset",
    )
    arguments = parser.parse_args()
    record = build(arguments.source)
    width = max(len(key) for key in record)
    for key, value in record.items():
        print(f"{key.rjust(width)} : {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
