#!/usr/bin/env python3
"""Build and verify the self-contained GitHub Pages artifact."""

from __future__ import annotations

import argparse
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit
import re
import shutil


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = Path("viewer-bnw.html")
_IMPORT_RE = re.compile(
    r"(?:\bfrom\s+|\bimport\s*\(\s*|\bimport\s+)['\"]([^'\"]+)['\"]"
)
_RUNTIME_ASSET_RE = re.compile(
    r"(?:\bfetch\s*\(|\bnew\s+URL\s*\(|\.(?:src|href)\s*=)\s*['\"]([^'\"]+)['\"]"
)
_CSS_ASSET_RE = re.compile(r"\burl\(\s*['\"]?([^)'\"\s]+)", re.IGNORECASE)
_SCANNED_SUFFIXES = frozenset({".html", ".htm", ".mjs", ".js", ".css"})


class _HTMLAssetCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        self.values.extend(
            value for key, value in attrs if key.lower() in {"src", "href"} and value
        )


def _local_specifiers(path: Path) -> tuple[str, ...]:
    if path.suffix.lower() not in _SCANNED_SUFFIXES:
        return ()
    source = path.read_text(encoding="utf-8")
    values = list(_IMPORT_RE.findall(source))
    if path.suffix.lower() in {".html", ".htm", ".mjs", ".js"}:
        values.extend(_RUNTIME_ASSET_RE.findall(source))
    if path.suffix.lower() in {".html", ".htm"}:
        collector = _HTMLAssetCollector()
        collector.feed(source)
        values.extend(collector.values)
    if path.suffix.lower() == ".css":
        values.extend(_CSS_ASSET_RE.findall(source))
    return tuple(values)


def _resolve_local_dependency(specifier: str, owner: Path, root: Path) -> Path | None:
    parts = urlsplit(specifier)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("data:"):
        return None
    if parts.path.startswith("/"):
        target = root / parts.path.lstrip("/")
    else:
        target = owner.parent / parts.path
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"browser dependency escapes site root: {owner}: {specifier}") from exc
    return target


def browser_dependency_closure(entrypoint: Path, root: Path) -> tuple[set[Path], list[str]]:
    """Return every local transitive browser dependency and any missing-edge errors."""
    root = root.resolve()
    pending = [entrypoint.resolve()]
    visited: set[Path] = set()
    errors: list[str] = []
    while pending:
        owner = pending.pop()
        if owner in visited:
            continue
        visited.add(owner)
        if not owner.is_file():
            errors.append(f"missing browser asset: {owner.relative_to(root)}")
            continue
        for specifier in _local_specifiers(owner):
            try:
                dependency = _resolve_local_dependency(specifier, owner, root)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if dependency is not None and dependency not in visited:
                pending.append(dependency)
    return visited, errors


def verify_pages_site(site_root: Path) -> None:
    site_root = site_root.resolve()
    _, errors = browser_dependency_closure(site_root / "index.html", site_root)
    if errors:
        raise RuntimeError("Pages artifact is not closed:\n" + "\n".join(sorted(errors)))


def _write_letter_route(output: Path, route: str, bundle_name: str) -> None:
    redirect = output / route / "index.html"
    redirect.parent.mkdir(parents=True, exist_ok=True)
    target = f"../?l={quote(bundle_name)}"
    redirect.write_text(
        '<!doctype html><meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0;url={escape(target, quote=True)}">\n'
        '<title>a letter</title>\n'
        f'<a href="{escape(target, quote=True)}">open your letter</a>\n',
        encoding="utf-8",
    )


def prepare_pages_site(output: Path) -> None:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing Pages directory: {output}")
    output.mkdir(parents=True)

    closure, errors = browser_dependency_closure(
        REPOSITORY_ROOT / ENTRYPOINT, REPOSITORY_ROOT,
    )
    if errors:
        raise RuntimeError("Source browser graph is not closed:\n" + "\n".join(sorted(errors)))
    for source in sorted(closure):
        relative = source.relative_to(REPOSITORY_ROOT)
        destination = output / (Path("index.html") if relative == ENTRYPOINT else relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    public_letters = REPOSITORY_ROOT / "public_letters"
    if public_letters.is_dir():
        for source in sorted(public_letters.glob("*.lateletter")):
            destination = output / "public_letters" / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            name = source.stem
            _write_letter_route(output, name, name)

    verify_pages_site(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_root", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_pages_site(args.site_root)
    else:
        prepare_pages_site(args.site_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
