"""Static contract checks for recipient-visible browser garden controls."""

from pathlib import Path


VIEWER = Path(__file__).parents[1] / "viewer-bnw.html"


def _viewer_source() -> str:
    return VIEWER.read_text(encoding="utf-8")


def test_browser_garden_exposes_pointer_and_touch_actions():
    source = _viewer_source()

    assert 'id="hud-actions"' in source
    assert "'examine memory'" in source
    assert "`feed ${animalType}`" in source
    assert "b.onclick=fn" in source
    assert "aria-keyshortcuts" in source


def test_browser_garden_wires_keyboard_actions_to_shared_handlers():
    source = _viewer_source()

    assert "e.key==='i'&&gardenReady" in source
    assert "e.preventDefault();showGardenMemories();" in source
    assert "e.key==='f'&&gardenReady" in source
    assert "e.preventDefault();feedAnimal();" in source


def test_browser_garden_actions_require_authentication():
    source = _viewer_source()

    assert "cachedPassphrase===null||bundleCorrupted" in source
    assert "cachedPassphrase!==null&&!bundleCorrupted" in source


def test_browser_post_completion_releases_remaining_gifts():
    source = _viewer_source()

    assert "if(postComplete)hit=true;" in source
    assert "postComplete=isPostComplete();\n    await evalTriggers(null);" in source
    assert "postComplete=isPostComplete();\n  await evalTriggers(msg.id);" in source
