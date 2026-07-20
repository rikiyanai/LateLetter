"""Browser Garden ownership and accessibility integration contracts."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
VIEWER = ROOT / "viewer-bnw.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


def _viewer_source() -> str:
    return VIEWER.read_text(encoding="utf-8")


def test_viewer_uses_canonical_runtime_for_live_garden_actions():
    source = _viewer_source()

    assert "import { GardenRuntime } from './web/garden-runtime.mjs'" in source
    assert "gardenRuntime.dispatch(modality,intent" in source
    assert "if(result.changed&&gardenProgram&&cachedPassphrase!==null&&!bundleCorrupted)" in source
    assert "await runAuthenticatedGardenProgram()" in source
    assert "gardenRuntime.materializeProgram(gardenProgram,result)" in source
    assert "new GardenState" not in source
    assert "evalTriggers" not in source
    assert "kGift" not in source
    assert "kAnimal" not in source
    assert "animalTrustActions++" not in source


def test_viewer_exposes_focusable_44px_semantic_controls():
    source = _viewer_source()

    assert 'id="garden-object-list"' in source
    assert 'id="garden-action-sheet"' in source
    assert 'id="garden-scene-summary"' in source
    assert 'aria-live="polite"' in source
    assert "min-width: 44px; min-height: 44px" in source
    for action in ("open_journal", "undo", "place", "pause_motion", "back"):
        assert f'data-garden-action="{action}"' in source
    for action in ("inspect", "tend", "feed", "play", "collect", "move_fixture"):
        assert action in source


def test_v1_and_v2_programs_share_authenticated_materialization_path():
    source = _viewer_source()

    assert "if(![1,2].includes(data.version))" in source
    assert "lateletter:garden-program:v1" in source
    assert "migrateAuthenticatedLegacyGifts" in source
    assert "runAuthenticatedGardenProgram" in source
    assert "expandGardenSchedule(event.schedule" in source
    assert "'animal.interaction'" in source
    assert "'plant.growth_stage'" in source
    load_end = source.index("// ── Auth")
    assert "migrateAuthenticatedLegacyGifts" not in source[source.index("async function loadBundle"):load_end]


def test_resize_cannot_regenerate_canonical_topology():
    source = _viewer_source()

    assert "onResize(){ this.dom.resize(); }" in source
    assert "window.addEventListener('resize',()=>{if(garden)garden.onResize()" in source


def test_pages_deploy_includes_browser_modules():
    deploy = DEPLOY.read_text(encoding="utf-8")
    assert "mkdir -p _site/web" in deploy
    assert "cp web/*.mjs _site/web/" in deploy


def test_behavioral_browser_modules_pass_node_contracts():
    completed = subprocess.run(
        [
            "node", "--test",
            "tests/garden_adapters/test_garden_input.mjs",
            "tests/garden_adapters/test_garden_world.mjs",
            "tests/garden_adapters/test_garden_live_runtime.mjs",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
