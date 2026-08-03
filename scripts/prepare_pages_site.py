#!/usr/bin/env python3
"""Build and verify the self-contained GitHub Pages artifact."""

from __future__ import annotations

import argparse
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit
import hashlib
import json
import re
import shutil
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = Path("viewer-bnw.html")
THIRD_PARTY_NOTICES = (Path("web/vendor/pretext/LICENSE"),)

# ---------------------------------------------------------------------------
# Release paint authority
# ---------------------------------------------------------------------------
#
# The two verdict registers the paint manifest is derived from. They live in
# the repository, not in the artifact: the artifact carries the DERIVED
# manifest, and verification recomputes it from these sources so that editing
# either register after a build makes the built artifact fail verification
# rather than silently keep its stale authority.
ASSET_REGISTER = Path("docs/garden-asset-acceptance.json")
RECIPE_REGISTER = Path("docs/garden-presentation-recipes.json")

# The files whose bytes define the profile/font/geometry identity: the
# versioned atlas (which owns measured art, profiles and connected tiles) and
# the bundled Garden font (which decides what every glyph physically looks
# like). A paint acceptance is only meaningful against the exact art and the
# exact font the reviewer saw, so both are pinned by content hash.
PAINT_IDENTITY_SOURCES = (
    Path("src/lateletter/garden/data/atlas.v2.json"),
    Path("web/fonts/lateletter-garden.woff"),
)

# Where the manifest lands inside the built site. It is excluded from its own
# artifact hash map, because a file cannot contain its own digest.
PAINT_MANIFEST_NAME = "garden-release-manifest.json"

# The verdict vocabulary shared by both registers. Only the two accepted
# verdicts grant release paint permission; `rejected` and `not_reviewed` are
# excluded from the manifest BY CONSTRUCTION, which is what makes the manifest
# usable as a release authority. Any verdict outside this vocabulary is a
# register corruption and fails the build loudly instead of being guessed at.
_ACCEPTED_VERDICTS = frozenset({"accepted", "accepted_as_deployed"})
_KNOWN_VERDICTS = _ACCEPTED_VERDICTS | {"not_reviewed", "rejected"}
_CSS_ASSET_RE = re.compile(r"\burl\(\s*['\"]?([^)'\"\s]+)", re.IGNORECASE)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SCANNED_SUFFIXES = frozenset({".html", ".htm", ".mjs", ".js", ".css"})


# ---------------------------------------------------------------------------
# JavaScript token scanning
# ---------------------------------------------------------------------------
#
# Why this replaced a regular expression
# --------------------------------------
# Import specifiers used to be found by running a regular expression over the
# raw text of a module. A regular expression cannot tell code apart from the
# things that merely LOOK like code:
#
#     // import './not-real.mjs'           <- inside a comment
#     const doc = "import './fake.mjs'"    <- prose inside a string literal
#     const t = `import './fake.mjs'`      <- text inside a template literal
#
# Every one of those made the old scanner invent a dependency on a file that
# does not exist, and an invented dependency fails the build. Failing loudly
# beats silently omitting a real asset, so the old behaviour erred in the safe
# direction -- but it is still wrong, and it meant no file could discuss an
# import in prose without breaking the deploy.
#
# What this is, stated precisely
# ------------------------------
# This is a TOKENIZER plus a small scanner over the resulting tokens. It is not
# a full ECMAScript parser: it builds no syntax tree and does not validate the
# program. That is deliberate, because deciding "which string literals are
# import specifiers" needs only the token stream -- `import`, `export` and
# `from` are keywords at known positions -- and a real parser would be far more
# machinery than the question requires. The distinction matters enough to name
# here so nobody later assumes guarantees this does not provide.

# Characters that may begin or continue a JavaScript identifier. `$` and `_`
# are legal identifier characters; this deliberately ignores the exotic
# Unicode identifier ranges, because every keyword this scanner cares about is
# plain ASCII.
_IDENTIFIER_START = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$"
)
_IDENTIFIER_PART = _IDENTIFIER_START | frozenset("0123456789")

# After these keywords a `/` opens a regular expression rather than dividing,
# because a keyword cannot be the left operand of a division.
_REGEX_FOLLOWS_KEYWORD = frozenset(
    {
        "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
        "throw", "case", "do", "else", "yield", "await",
    }
)

# Punctuation that CAN end an expression, so a following `/` is division.
# `}` is genuinely ambiguous -- it closes both a block (regex may follow) and
# an object literal (division may follow) -- and is treated as expression-
# ending here. Guessing wrong only mis-tokenizes a regex literal, which at
# worst hides an import that no real module would place inside one.
_EXPRESSION_ENDING_PUNCT = frozenset({")", "]", "}"})


def _tokenize_javascript(source: str) -> list[tuple[str, str]]:
    """The `(kind, value)` view of the token stream, for callers ignoring position.

    This is a projection of :func:`tokenize_javascript`, not a second tokenizer.
    Keeping one implementation matters more than it looks: the whole reason this
    module has a tokenizer is that a regular expression cannot tell code from
    text that resembles code, and a SECOND scanner would reintroduce exactly
    that bug somewhere else in the repository while this one stayed correct.

    :param source: The full text of a `.js` or `.mjs` module.
    :returns: The token stream in source order, without byte offsets.
    """
    return [(kind, value) for kind, value, _offset in tokenize_javascript(source)]


def tokenize_javascript(source: str) -> list[tuple[str, str, int]]:
    """Split JavaScript source into `(kind, value, start)` tokens, dropping comments.

    `kind` is one of ``name``, ``string``, ``template``, ``punct``, ``number``
    or ``regex``. For ``string`` tokens the value is the literal's body with
    simple escapes unwrapped, which is what an import specifier needs.

    `start` is the 0-indexed offset in `source` where the token begins. It is
    carried so a caller that needs to report a finding to a human -- "line 412
    paints without naming a source" -- can turn a token back into a location.
    Without it the only way to get a line number is to search the raw text
    again, which puts the comment-blind matching straight back in.

    Template literals emit their literal text as ``template`` rather than
    ``string``, and that distinction carries real weight: a template argument
    is interpolated at runtime, so its first text chunk is a PREFIX, not a
    path. Reading ``fetch(`${base}public_letters/`)`` as a static reference
    invents a dependency on a directory that was never an asset. Only genuine
    quoted literals are accepted as specifiers.

    The code inside each ``${ ... }`` substitution is tokenized normally, so a
    dynamic ``import()`` written inside a template expression is still seen.

    :param source: The full text of a `.js` or `.mjs` module.
    :returns: The token stream in source order.
    """
    tokens: list[tuple[str, str, int]] = []
    index = 0
    length = len(source)

    # Tracks how many `${` substitutions are currently open, and the brace
    # depth at which each one started. When a `}` brings the depth back to a
    # recorded value, that `}` closes the substitution and template text
    # resumes rather than the `}` being ordinary punctuation.
    template_returns: list[int] = []
    brace_depth = 0

    def regex_can_start_here() -> bool:
        """Decide whether a `/` at the cursor opens a regular expression."""
        if not tokens:
            # A `/` as the very first token can only be a regex.
            return True
        kind, value, _offset = tokens[-1]
        if kind in {"number", "string", "template", "regex"}:
            return False  # a value precedes it, so this is division
        if kind == "name":
            # Identifiers divide; keywords cannot, so they open a regex.
            return value in _REGEX_FOLLOWS_KEYWORD
        return value not in _EXPRESSION_ENDING_PUNCT

    def read_template_text(start: int) -> int:
        """Consume template text from `start` until `${`, a backtick, or EOF."""
        nonlocal brace_depth
        cursor = start
        chunk: list[str] = []
        while cursor < length:
            char = source[cursor]
            if char == "\\":
                # A backslash escapes the next character, including a backtick
                # or a `$`, so neither can end the chunk here.
                chunk.append(source[cursor + 1: cursor + 2])
                cursor += 2
                continue
            if char == "`":
                tokens.append(("template", "".join(chunk), start))
                return cursor + 1  # step past the closing backtick
            if char == "$" and source[cursor + 1: cursor + 2] == "{":
                tokens.append(("template", "".join(chunk), start))
                # Record the depth to return to, then OPEN a brace level for the
                # substitution before handing control back to the main loop.
                #
                # The increment is essential and easy to omit: without it the
                # matching `}` decrements to one BELOW the recorded depth, never
                # compares equal, and the template never terminates. Everything
                # after it is then tokenized as code until the next backtick,
                # which starts a bogus template that swallows the rest of the
                # file -- silently losing every import that follows.
                template_returns.append(brace_depth)
                brace_depth += 1
                tokens.append(("punct", "{", cursor))
                return cursor + 2
            chunk.append(char)
            cursor += 1
        tokens.append(("template", "".join(chunk), start))
        return cursor

    while index < length:
        char = source[index]

        # --- whitespace -------------------------------------------------
        if char in " \t\r\n\f\v":
            index += 1
            continue

        # --- comments (dropped entirely) --------------------------------
        if char == "/" and source[index + 1: index + 2] == "/":
            newline = source.find("\n", index)
            index = length if newline == -1 else newline
            continue
        if char == "/" and source[index + 1: index + 2] == "*":
            close = source.find("*/", index + 2)
            index = length if close == -1 else close + 2
            continue

        # --- string literals --------------------------------------------
        if char in "'\"":
            quote_char = char
            cursor = index + 1
            body: list[str] = []
            while cursor < length:
                current = source[cursor]
                if current == "\\":
                    # Keep the escaped character itself and drop the
                    # backslash. Specifiers essentially never need more than
                    # this, and a wrong unescape here would only ever produce
                    # a path that fails to resolve -- loudly, not silently.
                    body.append(source[cursor + 1: cursor + 2])
                    cursor += 2
                    continue
                if current == quote_char:
                    cursor += 1
                    break
                if current == "\n":
                    break  # unterminated; stop rather than run to EOF
                body.append(current)
                cursor += 1
            tokens.append(("string", "".join(body), index))
            index = cursor
            continue

        # --- template literals ------------------------------------------
        if char == "`":
            index = read_template_text(index + 1)
            continue

        # --- regular expression literals --------------------------------
        if char == "/" and regex_can_start_here():
            cursor = index + 1
            in_class = False  # inside `[...]`, where `/` is not the delimiter
            while cursor < length:
                current = source[cursor]
                if current == "\\":
                    cursor += 2
                    continue
                if current == "[":
                    in_class = True
                elif current == "]":
                    in_class = False
                elif current == "/" and not in_class:
                    cursor += 1
                    break
                elif current == "\n":
                    break  # unterminated; treat the line as the end
                cursor += 1
            # Consume trailing flags (g, i, m, s, u, y, d) so they are not
            # mistaken for an identifier token.
            while cursor < length and source[cursor] in _IDENTIFIER_PART:
                cursor += 1
            tokens.append(("regex", source[index:cursor], index))
            index = cursor
            continue

        # --- identifiers and keywords -----------------------------------
        if char in _IDENTIFIER_START:
            cursor = index
            while cursor < length and source[cursor] in _IDENTIFIER_PART:
                cursor += 1
            tokens.append(("name", source[index:cursor], index))
            index = cursor
            continue

        # --- numbers ------------------------------------------------------
        if char.isdigit():
            cursor = index
            while cursor < length and (
                source[cursor].isdigit() or source[cursor] in "._eExXaAbBcCdDfFoOn"
            ):
                cursor += 1
            tokens.append(("number", source[index:cursor], index))
            index = cursor
            continue

        # --- punctuation ---------------------------------------------------
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            # If this `}` closes a template substitution, template text resumes
            # immediately after it rather than ordinary code.
            if template_returns and brace_depth == template_returns[-1]:
                template_returns.pop()
                tokens.append(("punct", "}", index))
                index = read_template_text(index + 1)
                continue
        tokens.append(("punct", char, index))
        index += 1

    return tokens


def _javascript_specifiers(source: str) -> list[str]:
    """Extract every local-asset specifier from JavaScript source.

    Recognised forms, all decided from the token stream rather than raw text:

    * ``import './a.mjs'``                     -- side-effect import
    * ``import x from './a.mjs'``              -- static import, any clause
    * ``export { x } from './a.mjs'``          -- re-export
    * ``import('./a.mjs')``                    -- dynamic import
    * ``new URL('./a.png', import.meta.url)``  -- runtime asset reference
    * ``fetch('./a.json')``                    -- runtime fetch
    * ``el.src = './a.png'`` / ``el.href =``   -- runtime assignment

    :param source: The full text of a `.js` or `.mjs` module.
    :returns: Specifier strings in source order, unresolved and unfiltered.
    """
    tokens = _tokenize_javascript(source)
    total = len(tokens)
    found: list[str] = []

    def token(position: int) -> tuple[str, str] | None:
        """The token at `position`, or None when that falls outside the stream."""
        return tokens[position] if 0 <= position < total else None

    for position, (kind, value) in enumerate(tokens):
        if kind == "name" and value in {"import", "export"}:
            following = token(position + 1)
            if following is None:
                continue
            # `import './side-effect.mjs'` -- the string follows immediately.
            if value == "import" and following[0] == "string":
                found.append(following[1])
                continue
            # `import('./dynamic.mjs')` -- a dynamic import call.
            if value == "import" and following == ("punct", "("):
                argument = token(position + 2)
                if argument is not None and argument[0] == "string":
                    found.append(argument[1])
                continue
            # `import ... from './static.mjs'` / `export ... from './x.mjs'`.
            # Scan forward for the `from` keyword that binds this statement,
            # stopping at a `;` or at the next import/export so a malformed
            # clause cannot swallow an unrelated specifier.
            for lookahead in range(position + 1, total):
                ahead = tokens[lookahead]
                if ahead == ("punct", ";"):
                    break
                if ahead[0] == "name" and ahead[1] in {"import", "export"}:
                    break
                if ahead == ("name", "from"):
                    specifier = token(lookahead + 1)
                    if specifier is not None and specifier[0] == "string":
                        found.append(specifier[1])
                    break

        # `new URL('./asset.png', import.meta.url)`
        if kind == "name" and value == "new" and token(position + 1) == ("name", "URL"):
            if token(position + 2) == ("punct", "("):
                argument = token(position + 3)
                if argument is not None and argument[0] == "string":
                    found.append(argument[1])

        # `fetch('./asset.json')`
        if kind == "name" and value == "fetch" and token(position + 1) == ("punct", "("):
            argument = token(position + 2)
            if argument is not None and argument[0] == "string":
                found.append(argument[1])

        # `element.src = './asset.png'` and the `href` equivalent.
        if kind == "name" and value in {"src", "href"}:
            if token(position - 1) == ("punct", ".") and token(position + 1) == ("punct", "="):
                argument = token(position + 2)
                if argument is not None and argument[0] == "string":
                    found.append(argument[1])

    return found


class _HTMLAssetCollector(HTMLParser):
    """Collect `src`/`href` attributes and inline `<script>` and `<style>` text.

    Both kinds of inline block are real dependency owners. `viewer-bnw.html`
    imports the whole browser bundle from an inline module script, and declares
    its `@font-face` in an inline stylesheet -- so a bundled font is reachable
    ONLY through the `<style>` body. Missing that would leave the font out of
    the published site while every check still reported success, which is
    exactly the silent-omission failure this closure exists to prevent.
    """

    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []
        self.script_sources: list[str] = []
        self.style_sources: list[str] = []
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "script":
            self._in_script = True
        elif lowered == "style":
            self._in_style = True
        self.values.extend(
            value for key, value in attrs if key.lower() in {"src", "href"} and value
        )

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "script":
            self._in_script = False
        elif lowered == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.script_sources.append(data)
        elif self._in_style:
            self.style_sources.append(data)


def _local_specifiers(path: Path) -> tuple[str, ...]:
    """Return every local asset specifier declared by one file.

    :param path: The file to scan. Suffixes outside `_SCANNED_SUFFIXES` return
        nothing, because they cannot declare a browser dependency.
    :returns: Specifiers exactly as written, for the caller to resolve.
    """
    suffix = path.suffix.lower()
    if suffix not in _SCANNED_SUFFIXES:
        return ()
    source = path.read_text(encoding="utf-8")
    values: list[str] = []

    if suffix in {".mjs", ".js"}:
        values.extend(_javascript_specifiers(source))

    if suffix in {".html", ".htm"}:
        collector = _HTMLAssetCollector()
        collector.feed(source)
        values.extend(collector.values)
        # Each inline script is scanned on its own so that an unterminated
        # literal in one cannot corrupt the tokenization of the next.
        for script in collector.script_sources:
            values.extend(_javascript_specifiers(script))
        # Inline stylesheets carry `@font-face { src: url(...) }`, which is the
        # only path by which a bundled font reaches the dependency closure.
        for style in collector.style_sources:
            values.extend(_CSS_ASSET_RE.findall(_CSS_COMMENT_RE.sub("", style)))

    if suffix == ".css":
        # CSS comments are stripped first for the same reason JavaScript
        # comments are dropped: a commented-out `url()` names no dependency.
        values.extend(_CSS_ASSET_RE.findall(_CSS_COMMENT_RE.sub("", source)))

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
    """Verify a built site: dependency reachability AND paint authority.

    Both checks run and both must hold. The dependency walk catches a file
    that fell out of the bundle; the paint-manifest check catches an artifact
    whose authority no longer matches the registers or whose files were
    altered after the build. They are reported together so one failure cannot
    mask the other.

    :param site_root: The built artifact directory.
    :raises RuntimeError: listing every dependency and paint-authority error.
    """
    site_root = site_root.resolve()
    _, errors = browser_dependency_closure(site_root / "index.html", site_root)
    errors.extend(verify_paint_manifest(site_root))
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


# ---------------------------------------------------------------------------
# Release paint manifest
# ---------------------------------------------------------------------------
#
# What this is
# ------------
# The build-time accepted-paint authority required by the execution order's
# paint-manifest step. Until it existed, "which art may be painted in a
# release" was decided at RUNTIME by whatever flags reached the renderer --
# hostname checks, query parameters, `allowUnacceptedArt` -- which meant the
# authority travelled with the caller instead of with the artifact. This
# manifest inverts that: it is a pure function of the two verdict registers
# and the built files, computed once at build time, carrying no knowledge of
# hostnames, queries, review mode or any caller-created permission.
#
# What it guarantees
# ------------------
# * Only IDs whose register verdict is accepted appear. Rejected and
#   not-reviewed paint is absent by construction, not by a runtime check.
# * Every guarantee is pinned to exact bytes: the registers, the atlas, the
#   font and every built file are content-hashed, and the manifest carries
#   a digest of itself. Mutating any of them makes verification fail.


def _sha256_bytes(data: bytes) -> str:
    """The lowercase hex SHA-256 of `data`.

    :param data: Raw bytes to digest.
    :returns: 64 hex characters. SHA-256 because it is the digest every other
        acceptance record in this repository already uses; mixing digest
        algorithms would make receipts incomparable.
    """
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    """The SHA-256 of a file's exact bytes on disk.

    :param path: File to digest. A missing file raises, deliberately: a paint
        authority derived from a file that is not there would be a fabricated
        authority.
    :returns: 64 hex characters.
    """
    return _sha256_bytes(path.read_bytes())


def _checked_verdict(verdict: object, owner: str) -> str:
    """Validate one verdict value against the shared vocabulary.

    :param verdict: The raw value found in a register record.
    :param owner: Human-readable identity of the record, for the error text.
    :returns: The verdict, known-good.
    :raises RuntimeError: if the verdict is not in the shared vocabulary --
        an unknown verdict means the register changed shape underneath this
        builder, and guessing whether "pending" grants paint permission is
        exactly the kind of silent decision this manifest exists to forbid.
    """
    if not isinstance(verdict, str) or verdict not in _KNOWN_VERDICTS:
        raise RuntimeError(
            f"unknown verdict {verdict!r} on {owner}; the register vocabulary "
            f"is {sorted(_KNOWN_VERDICTS)} and this build refuses to guess"
        )
    return verdict


def _accepted_asset_ids(register: dict) -> list[str]:
    """Every asset ID the asset register currently accepts.

    :param register: Parsed ``docs/garden-asset-acceptance.json``.
    :returns: Sorted accepted IDs. Sorted so the manifest is byte-stable
        across builds of the same inputs -- identity hashes require it.
    """
    accepted = []
    for record in register["assets"]:
        asset_id = record["asset_id"]
        if _checked_verdict(record["verdict"], f"asset {asset_id!r}") in _ACCEPTED_VERDICTS:
            accepted.append(asset_id)
    return sorted(accepted)


def _accepted_recipe_ids(register: dict) -> list[str]:
    """Every recipe ID the presentation-recipe register currently accepts.

    :param register: Parsed ``docs/garden-presentation-recipes.json``.
    :returns: Sorted accepted IDs, for the same byte-stability reason as
        :func:`_accepted_asset_ids`.
    """
    accepted = []
    for recipe_id, record in register["records"].items():
        if _checked_verdict(record["verdict"], f"recipe {recipe_id!r}") in _ACCEPTED_VERDICTS:
            accepted.append(recipe_id)
    return sorted(accepted)


def _artifact_file_hashes(site_root: Path) -> dict[str, str]:
    """Content hashes for every file in the built site, keyed by POSIX relpath.

    :param site_root: The built artifact directory.
    :returns: ``{relative_path: sha256}`` for every file except the manifest
        itself, which is excluded because a file cannot contain its own digest.
        Paths are POSIX-form so the map is identical across platforms.
    """
    hashes: dict[str, str] = {}
    for path in sorted(site_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(site_root).as_posix()
        if relative == PAINT_MANIFEST_NAME:
            continue
        hashes[relative] = _sha256_path(path)
    return hashes


def _canonical_json_bytes(payload: dict) -> bytes:
    """The one canonical byte encoding of a JSON payload.

    Sorted keys and pinned separators, because two builds of the same inputs
    must produce the same digest -- a hash over an unstable encoding would
    report drift where there is none.

    :param payload: JSON-serialisable mapping.
    :returns: UTF-8 bytes of the canonical encoding.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_paint_manifest(site_root: Path, repository_root: Path = REPOSITORY_ROOT) -> dict:
    """Compute the release paint manifest for a built site.

    A pure function of the two verdict registers, the identity sources and the
    built files. It reads no environment, no hostname, no query string and no
    review flag -- that independence is the entire point, so nothing here may
    grow a parameter that carries caller intent.

    :param site_root: The built artifact directory whose files are pinned.
    :param repository_root: Where the registers and identity sources are read
        from. Parameterised (rather than hard-coded) so the mutation tests can
        point verification at a deliberately altered register and prove the
        build fails; production callers always pass the real repository.
    :returns: The manifest mapping, including its own ``manifest_identity``.
    :raises RuntimeError: on an unknown verdict in either register.
    """
    asset_register_bytes = (repository_root / ASSET_REGISTER).read_bytes()
    recipe_register_bytes = (repository_root / RECIPE_REGISTER).read_bytes()
    asset_register = json.loads(asset_register_bytes)
    recipe_register = json.loads(recipe_register_bytes)

    # The atlas is also parsed (not only hashed) so the manifest can name the
    # atlas id/version a reviewer would recognise, next to the exact bytes.
    atlas_path = repository_root / PAINT_IDENTITY_SOURCES[0]
    font_path = repository_root / PAINT_IDENTITY_SOURCES[1]
    atlas = json.loads(atlas_path.read_bytes())

    files = _artifact_file_hashes(site_root)
    # The artifact identity digests the (path, hash) lines rather than the
    # files again: it is an identity over the MAP, so adding, removing or
    # editing any file changes it.
    artifact_identity = _sha256_bytes(
        "\n".join(f"{name}:{digest}" for name, digest in sorted(files.items())).encode("utf-8")
    )

    body = {
        "schema": 1,
        "purpose": (
            "Build-time accepted-paint authority for the Garden release "
            "artifact. Only IDs listed here may be painted by a release "
            "build. Derived solely from the verdict registers and the built "
            "files; hostname, query parameters, review mode and "
            "caller-created permissions are not inputs and must never become "
            "inputs."
        ),
        "registers": {
            "asset_register": {
                "path": ASSET_REGISTER.as_posix(),
                "sha256": _sha256_bytes(asset_register_bytes),
            },
            "recipe_register": {
                "path": RECIPE_REGISTER.as_posix(),
                "sha256": _sha256_bytes(recipe_register_bytes),
            },
        },
        "accepted_assets": _accepted_asset_ids(asset_register),
        "accepted_recipes": _accepted_recipe_ids(recipe_register),
        "profile_identity": {
            "atlas": {
                "path": PAINT_IDENTITY_SOURCES[0].as_posix(),
                "sha256": _sha256_path(atlas_path),
                # The human-recognisable identity beside the bytes, so a
                # reviewer can tell WHICH atlas without re-hashing anything.
                "id": atlas.get("id"),
                "version": atlas.get("version"),
            },
            "font": {
                "path": PAINT_IDENTITY_SOURCES[1].as_posix(),
                "sha256": _sha256_path(font_path),
            },
        },
        "artifact": {
            "identity": artifact_identity,
            "files": files,
        },
    }
    # The manifest's own identity: a digest of everything above. Editing any
    # field by hand -- including quietly adding an ID to an accepted list --
    # breaks this digest and fails verification.
    body["manifest_identity"] = _sha256_bytes(_canonical_json_bytes(body))
    return body


def write_paint_manifest(site_root: Path, repository_root: Path = REPOSITORY_ROOT) -> Path:
    """Generate the paint manifest into a built site.

    :param site_root: The built artifact directory.
    :param repository_root: See :func:`build_paint_manifest`.
    :returns: The path of the written manifest. Written with an indent (unlike
        the canonical digest encoding) because humans read this file during
        review; the digest is computed over the canonical encoding, so the
        pretty form does not participate in any identity.
    """
    manifest = build_paint_manifest(site_root, repository_root)
    destination = site_root / PAINT_MANIFEST_NAME
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


def verify_paint_manifest(
    site_root: Path, repository_root: Path = REPOSITORY_ROOT
) -> list[str]:
    """Recompute the paint manifest and report every disagreement.

    This is the teeth of the authority: the build wrote a manifest, and this
    recomputes the same pure function from the CURRENT registers and the
    CURRENT files. Any drift -- an edited register, a tampered file, a
    hand-modified manifest -- surfaces as a named error instead of reaching
    a deploy.

    :param site_root: The built artifact directory to verify.
    :param repository_root: Where the registers are read from now.
    :returns: Error strings; empty means the artifact's paint authority is
        exactly what the registers currently grant.
    """
    manifest_path = site_root / PAINT_MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"missing release paint manifest: {PAINT_MANIFEST_NAME}"]
    try:
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"unreadable release paint manifest: {exc}"]

    errors: list[str] = []

    # Self-consistency first: the stored body must match its stored digest.
    # This catches hand edits even when they happen to agree with the current
    # registers, because an edited file no longer matches its own identity.
    claimed_identity = stored.get("manifest_identity")
    body = {key: value for key, value in stored.items() if key != "manifest_identity"}
    if _sha256_bytes(_canonical_json_bytes(body)) != claimed_identity:
        errors.append(
            "release paint manifest identity does not match its content; "
            "the manifest was edited after it was generated"
        )

    # Then recompute the whole manifest from current sources and compare
    # field-by-field, so each kind of drift gets an error naming its cause.
    expected = build_paint_manifest(site_root, repository_root)
    for register_name in ("asset_register", "recipe_register"):
        stored_digest = stored.get("registers", {}).get(register_name, {}).get("sha256")
        if stored_digest != expected["registers"][register_name]["sha256"]:
            errors.append(
                f"{register_name} has changed since the manifest was "
                "generated; the artifact's paint authority is stale"
            )
    for list_name in ("accepted_assets", "accepted_recipes"):
        if stored.get(list_name) != expected[list_name]:
            errors.append(
                f"{list_name} in the manifest does not match what the "
                "registers currently accept"
            )
    if stored.get("profile_identity") != expected["profile_identity"]:
        errors.append("profile/font identity has changed since the manifest was generated")

    stored_files = stored.get("artifact", {}).get("files", {})
    expected_files = expected["artifact"]["files"]
    for name in sorted(set(stored_files) | set(expected_files)):
        if stored_files.get(name) != expected_files.get(name):
            errors.append(f"artifact file does not match its manifest hash: {name}")
    if stored.get("artifact", {}).get("identity") != expected["artifact"]["identity"]:
        errors.append("artifact identity does not match the built files")

    return errors


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

    for relative in THIRD_PARTY_NOTICES:
        source = REPOSITORY_ROOT / relative
        destination = output / relative
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

    # The paint manifest is written LAST, after every other file exists, so
    # its artifact map covers the whole build. Verification then recomputes
    # it immediately: a build whose own authority does not verify never
    # reaches a caller.
    write_paint_manifest(output)
    verify_pages_site(output)


def enforce_release_gate() -> None:
    """Refuse to hand back a root artifact while release blockers stand.

    Until now ``scripts/validate_presentation_identity.py`` was a diagnostic
    somebody had to remember to run: nothing in the build or the Pages workflow
    invoked it, so a root artifact could be produced with unaccepted art,
    anonymous paint and no operator acceptance, and the only thing standing
    between that and a deploy was a person's memory.  A gate nothing calls is
    indistinguishable from a gate that does not exist.

    This does not touch deployment, which stays on the legacy builder until the
    operator's cutover.  It makes the ROOT artifact refuse to be built while the
    conditions it is gated on are unmet, which is the honest place for the check:
    the artifact is the thing that would ship.

    :raises RuntimeError: listing every outstanding blocker
    """
    sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
    from validate_presentation_identity import run as _run_gate  # noqa: PLC0415

    report = _run_gate()
    if report.ok:
        return
    lines = []
    for name, entries in sorted(report.blockers.items()):
        if entries:
            lines.append(f"  {name}: {len(entries)}")
            lines.extend(f"      {entry}" for entry in entries[:4])
    for violation in report.violations[:10]:
        lines.append(f"  violation: {violation}")
    raise RuntimeError(
        "refusing to build the root artifact while release blockers stand:\n"
        + "\n".join(lines)
        + "\n\nRun scripts/validate_presentation_identity.py for the full report. "
        "Pass --skip-release-gate to build anyway; doing so produces an artifact "
        "that must not be deployed."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_root", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--skip-release-gate",
        action="store_true",
        help=(
            "build even though release blockers stand. Deliberately explicit and "
            "deliberately loud: a bypass that has to be typed is visible in a "
            "command line and a CI log, where a default would not be."
        ),
    )
    args = parser.parse_args()
    if args.verify_only:
        verify_pages_site(args.site_root)
        return 0
    if not args.skip_release_gate:
        enforce_release_gate()
    prepare_pages_site(args.site_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
