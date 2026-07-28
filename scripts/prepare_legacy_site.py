#!/usr/bin/env python3
"""Build the public GitHub Pages artifact from the frozen `legacy/` clone.

WHY THIS EXISTS
---------------
The repository root holds active development: a modular viewer that pulls its
garden from `web/garden-*.mjs`, and a v2 bundle format. That work is not ready
to face the public. The `legacy/` directory holds a self-contained, known-good
snapshot of the July-19 codebase, and it is what the public endpoint serves
until the root work is correct.

This script exists separately from `scripts/prepare_pages_site.py` on purpose.
That script builds the ROOT viewer and is itself under active edit; pointing it
at `legacy/` would entangle two independent concerns and make either one harder
to change. Publishing is a one-way door, so the thing that publishes should be
small, obvious, and stable.

WHAT THE LEGACY SNAPSHOT NEEDS
------------------------------
The legacy viewer is a single self-contained HTML file. Its only external
dependency is a dynamic `import()` of PreText from a CDN, which is wrapped in
try/catch and degrades to browser text layout when unavailable -- so it needs
no bundling and no local JavaScript assets at all.

What it does read at runtime, all same-origin:

  * `test_fixture.lateletter`   -- the unsealed demo letter ([get demo letter])
  * `sealed_demo.lateletter`    -- the passcode demo ([get passcode-locked demo])
  * `public_letters/<name>.lateletter` -- the `?l=<name>` shareable-letter route

The published layout mirrors that exactly:

  _site/index.html                          <- legacy/viewer-bnw.html
  _site/test_fixture.lateletter
  _site/sealed_demo.lateletter
  _site/public_letters/<name>.lateletter
  _site/<name>/index.html                   <- redirect to ../?l=<name>

Nothing else from `legacy/` is published. The snapshot also contains Python
sources, tests and documentation, which are useful for reproducing the build but
have no business being served to browsers -- copying them would widen the public
surface for no benefit.
"""

from __future__ import annotations

import argparse
import shutil
from html import escape
from pathlib import Path
from urllib.parse import quote


# The repository root, derived from this file's own location so the script
# behaves the same no matter which directory the caller invokes it from.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# The frozen snapshot that serves production. Everything published comes from
# inside this directory and nowhere else.
LEGACY_ROOT = REPOSITORY_ROOT / "legacy"

# The viewer that becomes the site's index page.
ENTRYPOINT = LEGACY_ROOT / "viewer-bnw.html"

# Same-origin bundles the viewer fetches by literal name from the site root.
# These back demo buttons on the landing page; if one is missing the button
# fails at runtime with a fetch error, so their presence is verified rather
# than assumed.
ROOT_BUNDLES = ("test_fixture.lateletter", "sealed_demo.lateletter")


def _write_letter_route(output: Path, name: str) -> None:
    """Emit `/<name>/index.html`, a redirect into the viewer's `?l=` route.

    The viewer loads a shareable letter from a query parameter, but a bare
    directory URL reads better in a link than a query string. This writes a
    minimal meta-refresh page that bounces to `../?l=<name>`, with a plain
    anchor as the fallback for anything that ignores the refresh.

    `quote` escapes the name for use inside a URL; `escape` then escapes that
    result for use inside HTML attributes. Both are needed -- they solve
    different problems, and skipping either allows a crafted letter name to
    break out of the attribute.
    """
    target = f"../?l={quote(name)}"
    safe_target = escape(target, quote=True)

    redirect = output / name / "index.html"
    redirect.parent.mkdir(parents=True, exist_ok=True)
    redirect.write_text(
        '<!doctype html><meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0;url={safe_target}">\n'
        "<title>a letter</title>\n"
        f'<a href="{safe_target}">open your letter</a>\n',
        encoding="utf-8",
    )


def prepare_legacy_site(output: Path) -> None:
    """Assemble the publishable site tree at `output`.

    Refuses to write into an existing directory. A Pages artifact is built fresh
    every run; reusing a directory risks publishing a stale file that no longer
    corresponds to anything in the repository.
    """
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing Pages directory: {output}")

    if not ENTRYPOINT.is_file():
        raise FileNotFoundError(f"legacy viewer is missing: {ENTRYPOINT}")

    output.mkdir(parents=True)

    # The viewer becomes the site index, so visiting the domain root opens it.
    shutil.copy2(ENTRYPOINT, output / "index.html")

    # Demo bundles sit at the site root because the viewer fetches them by bare
    # filename, relative to wherever the page itself was served from.
    for bundle_name in ROOT_BUNDLES:
        source = LEGACY_ROOT / bundle_name
        if not source.is_file():
            raise FileNotFoundError(f"legacy demo bundle is missing: {source}")
        shutil.copy2(source, output / bundle_name)

    # Shareable letters, plus one pretty-URL redirect directory each.
    public_letters = LEGACY_ROOT / "public_letters"
    letters = sorted(public_letters.glob("*.lateletter")) if public_letters.is_dir() else []
    for source in letters:
        destination = output / "public_letters" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        _write_letter_route(output, source.stem)

    # State plainly what became public. A letter dropped into
    # `legacy/public_letters` is published automatically, so the operator should
    # be able to read the full list straight from the build log rather than
    # having to go and inspect the artifact.
    print(f"published {len(letters)} shareable letter(s):")
    for source in letters:
        print(f"  /{source.stem}/  ->  public_letters/{source.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_root", type=Path)
    args = parser.parse_args()
    prepare_legacy_site(args.site_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
