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
THIRD_PARTY_NOTICES = (Path("web/vendor/pretext/LICENSE"),)
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
