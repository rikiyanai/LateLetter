#!/usr/bin/env python3
"""Place a fresh Garden candidate beside the deployed legacy, in one image.

WHY THIS EXISTS
---------------
The destination spec's acceptance package (goal file section 13) requires a
"fresh nonpersistent canonical candidate" AND the "deployed legacy beside it".
``scripts/capture_html_garden_review.py`` produces each side on its own, but a
reviewer comparing two files by flipping between tabs is comparing memories,
not pictures -- and the whole question being asked is a visual one: does the
candidate preserve the approved deployed visual language?

So this tool does exactly one thing: it composes already-captured stills into a
single labelled sheet, at their original pixel sizes, with no scaling, cropping,
enhancement or colour management of any kind. It adds nothing to either image.
If the candidate looks sparse beside the legacy, that is the finding, and
nothing here is allowed to soften it.

WHAT IT IS NOT
--------------
It is not an acceptance oracle and produces no verdict. It reads PNGs that a
capture run already wrote and stacks them. The operator still has to look.

USAGE
-----
    python3 scripts/build_garden_comparison_sheet.py \
      --candidate docs/visual-review/2026-08-03/garden/04-...-desktop-1600x1000.png \
      --legacy    docs/visual-review/2026-08-03/garden/03-...-desktop-1600x1000.png \
      --output    docs/visual-review/2026-08-03/garden/05-candidate-beside-legacy-desktop.png
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


# The strip above each panel that carries its label. Tall enough for the label
# plus the source filename, because a sheet whose panels cannot be traced back
# to the captures they came from is an unciteable picture.
BANNER_HEIGHT = 64

# A gap between panels so the eye does not read two gardens as one continuous
# scene -- which, given both are wide horizontal bands, it otherwise will.
GUTTER = 24

# Neutral surround. Deliberately mid-grey rather than white or black: both
# viewers render on pale paper, and a white surround would make the candidate's
# empty sky look like part of the mount.
SURROUND = (58, 58, 58)
LABEL_COLOUR = (245, 245, 245)
SUBLABEL_COLOUR = (170, 170, 170)

# macOS ships this; the sheet is a review artifact, not a product surface, so a
# plain system sans is right and no bundled font question arises.
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A readable label font, or Pillow's bitmap default if none is installed.

    :param size: point size to request
    :returns: a font object that ``ImageDraw.text`` accepts
    """
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:  # pragma: no cover - a broken system font
                continue
    return ImageFont.load_default()


def _sha256(path: Path) -> str:
    """Digest of the exact bytes composed, so the sheet can cite its sources."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fitted_font(draw: ImageDraw.ImageDraw, text: str, limit: int, largest: int):
    """The largest font size at which `text` still fits inside `limit` pixels.

    A mobile panel is 390px wide, and the default banner text is far wider than
    that at 28pt. The first version of this tool drew both banners at one size,
    so on the mobile sheet the candidate's label ran straight through the
    legacy's and neither was readable -- a comparison sheet whose own captions
    are illegible fails at the one job it has. Sizes step down rather than the
    text being cut short, because the label says which side is which and half a
    label cannot.

    :param draw: the drawing context, used only to measure
    :param text: the label to fit
    :param limit: available width in pixels
    :param largest: the size to try first
    :returns: a font object at the largest size that fits, floored at 11pt
    """
    for size in range(largest, 10, -1):
        font = _load_font(size)
        if draw.textlength(text, font=font) <= limit:
            return font
    return _load_font(11)


def _elided(draw: ImageDraw.ImageDraw, text: str, font, limit: int) -> str:
    """`text` shortened from the left until it fits, or unchanged if it already does.

    Used only for the source line, never the label. Shrinking type has a floor,
    and below it the candidate's filename still ran into the legacy's on the
    390px mobile panel -- so at that point the text itself has to give. It is
    trimmed from the LEFT because the informative end is the right one: the
    capture's distinguishing suffix and its digest.

    :param draw: the drawing context, used only to measure
    :param text: the source line
    :param font: the font it will be drawn in
    :param limit: available width in pixels
    :returns: the original text, or an ellipsis followed by its tail
    """
    if draw.textlength(text, font=font) <= limit:
        return text
    for cut in range(1, len(text)):
        candidate = "…" + text[cut:]
        if draw.textlength(candidate, font=font) <= limit:
            return candidate
    return "…"


def compose(
    panels: list[tuple[str, Path]],
    output: Path,
) -> dict[str, object]:
    """Stack labelled panels left to right at their native size.

    :param panels: ``(label, png path)`` in the order they should appear
    :param output: where to write the composed sheet
    :returns: a small record of what went in, for the caller to print or store
    """
    images = [(label, path, Image.open(path).convert("RGB")) for label, path in panels]

    # The sheet is as tall as the tallest panel plus one banner, and as wide as
    # every panel plus the gutters between them. Panels are never resized: a
    # comparison that rescales one side is comparing two different pictures.
    width = sum(image.width for _, _, image in images) + GUTTER * (len(images) + 1)
    height = max(image.height for _, _, image in images) + BANNER_HEIGHT + GUTTER

    sheet = Image.new("RGB", (width, height), SURROUND)
    draw = ImageDraw.Draw(sheet)

    record: list[dict[str, object]] = []
    x = GUTTER
    for label, path, image in images:
        # Each banner is measured against ITS OWN panel width, so a narrow
        # mobile panel gets small type and a wide desktop panel gets large type
        # on the same sheet. Neither can spill into its neighbour.
        source = f"{path.name}  sha256:{_sha256(path)[:16]}"
        source_font = _fitted_font(draw, source, image.width, 15)
        draw.text(
            (x, 12), label,
            font=_fitted_font(draw, label, image.width, 28), fill=LABEL_COLOUR,
        )
        draw.text(
            (x, 44), _elided(draw, source, source_font, image.width),
            font=source_font, fill=SUBLABEL_COLOUR,
        )
        sheet.paste(image, (x, BANNER_HEIGHT))
        record.append(
            {
                "label": label,
                "source": str(path),
                "sha256": _sha256(path),
                "size": [image.width, image.height],
            }
        )
        x += image.width + GUTTER

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return {"output": str(output), "size": [width, height], "panels": record}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_garden_comparison_sheet",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--candidate", type=Path, required=True, help="fresh candidate still (PNG)"
    )
    parser.add_argument(
        "--legacy", type=Path, required=True, help="deployed legacy still (PNG)"
    )
    parser.add_argument("--output", type=Path, required=True, help="sheet to write")
    parser.add_argument(
        "--candidate-label",
        default="FRESH CANDIDATE — canonical world, this commit",
        help="banner text over the candidate panel",
    )
    parser.add_argument(
        "--legacy-label",
        default="DEPLOYED LEGACY — the accepted visual baseline",
        help="banner text over the legacy panel",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in (args.candidate, args.legacy):
        if not path.is_file():
            print(f"missing still: {path}", file=sys.stderr)
            return 2
    if args.output.exists():
        # Same rule the capture tool follows: review artifacts are evidence, and
        # evidence that can be silently replaced is not evidence.
        print(f"refusing to overwrite {args.output}", file=sys.stderr)
        return 2

    record = compose(
        [
            (args.candidate_label, args.candidate),
            (args.legacy_label, args.legacy),
        ],
        args.output,
    )
    print(f"sheet: {record['output']} {record['size'][0]}x{record['size'][1]}")
    for panel in record["panels"]:  # type: ignore[index]
        print(f"  {panel['label']}  <- {Path(panel['source']).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
