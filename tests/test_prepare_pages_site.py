"""Tests for the Pages deployment dependency scanner.

Why this file exists
--------------------
The deploy artifact is built by walking every local asset reachable from
`viewer-bnw.html`. If that walk invents a dependency, the build fails on a file
nobody ever imported; if it misses one, a real asset is silently left out of the
published site and the Garden breaks live. Both directions are deployment
failures, so the walk is worth testing directly rather than only through the
end-to-end deploy test.

The scanner used to find import specifiers with a regular expression over raw
source text. That could not tell code apart from text that merely looks like
code, so a commented-out import, an import mentioned in prose inside a string,
or one appearing in template literal text each fabricated a dependency. The
four tests marked "regression" below are exactly those cases.
"""

from __future__ import annotations

from pathlib import Path
import sys

# The scanner lives in `scripts/`, which is not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prepare_pages_site import (  # noqa: E402  (import follows path setup)
    REPOSITORY_ROOT,
    _javascript_specifiers,
    _local_specifiers,
    browser_dependency_closure,
)


# ---------------------------------------------------------------------------
# Forms the scanner must recognise
# ---------------------------------------------------------------------------


def test_static_import_specifier_is_found():
    assert _javascript_specifiers("import x from './a.mjs';") == ["./a.mjs"]


def test_side_effect_import_specifier_is_found():
    """`import './x.mjs'` has no clause; the string follows the keyword."""
    assert _javascript_specifiers("import './a.mjs';") == ["./a.mjs"]


def test_named_import_clause_does_not_hide_the_specifier():
    source = "import { a, b as c } from './a.mjs';"
    assert _javascript_specifiers(source) == ["./a.mjs"]


def test_re_export_specifier_is_found():
    """`export ... from` pulls a module into the graph exactly like `import`."""
    assert _javascript_specifiers("export { a } from './a.mjs';") == ["./a.mjs"]
    assert _javascript_specifiers("export * from './b.mjs';") == ["./b.mjs"]


def test_dynamic_import_specifier_is_found():
    source = "const m = await import('./a.mjs');"
    assert _javascript_specifiers(source) == ["./a.mjs"]


def test_runtime_asset_references_are_found():
    """Assets fetched at runtime are dependencies even though they are not imports."""
    assert _javascript_specifiers("new URL('./a.png', import.meta.url)") == ["./a.png"]
    assert _javascript_specifiers("fetch('./a.json')") == ["./a.json"]
    assert _javascript_specifiers("img.src = './a.png';") == ["./a.png"]


def test_import_meta_url_alone_is_not_a_specifier():
    """`import.meta.url` contains the `import` keyword but names no module."""
    assert _javascript_specifiers("const u = import.meta.url;") == []


# ---------------------------------------------------------------------------
# Regressions: text that only LOOKS like an import
# ---------------------------------------------------------------------------


def test_regression_import_inside_a_line_comment_is_not_a_dependency():
    assert _javascript_specifiers("// import './ghost.mjs'\n") == []


def test_regression_import_inside_a_block_comment_is_not_a_dependency():
    assert _javascript_specifiers("/* import './ghost.mjs' */") == []


def test_regression_import_quoted_as_prose_is_not_a_dependency():
    """A string that talks ABOUT an import must not create one."""
    source = "const doc = \"import './ghost.mjs'\";"
    assert _javascript_specifiers(source) == []


def test_regression_import_in_template_literal_text_is_not_a_dependency():
    source = "const t = `import './ghost.mjs'`;"
    assert _javascript_specifiers(source) == []


def test_real_import_inside_a_template_substitution_is_still_found():
    """`${ ... }` holds real code, so an import inside one is a real edge.

    This is the counterpart to the test above: template TEXT is inert, template
    SUBSTITUTIONS are not, and the tokenizer has to tell them apart.
    """
    source = "const t = `x ${await import('./a.mjs')} y`;"
    assert _javascript_specifiers(source) == ["./a.mjs"]


def test_imports_after_a_template_literal_are_still_found():
    """Regression: a template must terminate so later code is still scanned.

    The tokenizer opens a brace level when `${` starts a substitution. If it
    records the depth without incrementing it, the closing `}` never compares
    equal, the template never terminates, and the next backtick starts a bogus
    template that swallows the remainder of the file -- silently dropping every
    import after it. That is not a hypothetical: it removed all five vendored
    PreText modules from the real deploy closure, and no check objected, because
    a closure that is merely too small raises no error.

    The trailing text after the last `${...}` matters here; without it the
    template ends at a backtick and the bug does not show.
    """
    source = (
        "const spec = `${a.weight} ${a.size}px '${a.family}'`;\n"
        "const m = await import('./after-template.mjs');\n"
    )
    assert _javascript_specifiers(source) == ["./after-template.mjs"]


def test_nested_braces_inside_a_template_substitution_do_not_end_it_early():
    """An object literal inside `${ }` must not be read as closing it."""
    source = (
        "const t = `x ${fn({a: 1})} y`;\n"
        "import './after-nested.mjs';\n"
    )
    assert _javascript_specifiers(source) == ["./after-nested.mjs"]


def test_division_is_not_mistaken_for_a_regular_expression():
    """A `/` after a value divides; misreading it would swallow later source."""
    source = "const r = a / b; import './a.mjs';"
    assert _javascript_specifiers(source) == ["./a.mjs"]


# ---------------------------------------------------------------------------
# CSS and HTML owners
# ---------------------------------------------------------------------------


def test_css_url_is_a_dependency_but_a_commented_one_is_not(tmp_path):
    stylesheet = tmp_path / "s.css"
    stylesheet.write_text(
        "@font-face { src: url('./real.woff2'); }\n"
        "/* @font-face { src: url('./ghost.woff2'); } */\n",
        encoding="utf-8",
    )
    assert _local_specifiers(stylesheet) == ("./real.woff2",)


def test_inline_script_bodies_in_html_are_scanned(tmp_path):
    """`viewer-bnw.html` imports the whole bundle from an inline module script."""
    page = tmp_path / "p.html"
    page.write_text(
        "<html><body>\n"
        "<script type='module'>\n"
        "  import './real.mjs';\n"
        "  // import './ghost.mjs'\n"
        "</script>\n"
        "</body></html>\n",
        encoding="utf-8",
    )
    assert _local_specifiers(page) == ("./real.mjs",)


# ---------------------------------------------------------------------------
# Loud failure on genuinely unresolved dependencies
# ---------------------------------------------------------------------------


def test_a_missing_asset_is_reported_as_an_error(tmp_path):
    """Erring toward silence would publish a broken site; this must stay loud."""
    (tmp_path / "index.html").write_text(
        "<script type='module'>import './absent.mjs';</script>", encoding="utf-8"
    )
    _, errors = browser_dependency_closure(tmp_path / "index.html", tmp_path)
    assert any("absent.mjs" in error for error in errors)


def test_a_dependency_escaping_the_site_root_is_reported(tmp_path):
    """A path climbing out of the root cannot be published, so it must fail."""
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(
        "<script type='module'>import '../outside.mjs';</script>", encoding="utf-8"
    )
    _, errors = browser_dependency_closure(root / "index.html", root)
    assert any("escapes site root" in error for error in errors)


# ---------------------------------------------------------------------------
# The real repository closure
# ---------------------------------------------------------------------------


def test_the_real_viewer_closure_resolves_with_no_errors():
    """The product entrypoint must have a fully resolvable dependency graph."""
    files, errors = browser_dependency_closure(
        REPOSITORY_ROOT / "viewer-bnw.html", REPOSITORY_ROOT
    )
    assert errors == []
    assert files


def test_the_real_closure_contains_the_modules_the_garden_needs():
    """Guards against an asset silently dropping out of the published bundle."""
    files, _ = browser_dependency_closure(
        REPOSITORY_ROOT / "viewer-bnw.html", REPOSITORY_ROOT
    )
    relative = {str(path.relative_to(REPOSITORY_ROOT)) for path in files}

    for required in ("web/garden-geometry.mjs", "web/garden-atlas-art.mjs"):
        assert required in relative, f"{required} fell out of the deploy closure"

    # PreText is vendored as several modules that import one another; the
    # measurement module is the one the geometry layer depends on directly.
    assert "web/vendor/pretext/measurement.js" in relative
