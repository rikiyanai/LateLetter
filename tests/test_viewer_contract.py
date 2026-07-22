"""Browser Garden ownership and accessibility integration contracts."""

from pathlib import Path
import os
import subprocess

from lateletter.bundle import read_bundle, verify_checksum
from lateletter.sealed import open_garden_program, verify_bundle_hmac


ROOT = Path(__file__).parents[1]
VIEWER = ROOT / "viewer-bnw.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


def _viewer_source() -> str:
    return VIEWER.read_text(encoding="utf-8")


def test_viewer_uses_canonical_runtime_for_live_garden_actions():
    source = _viewer_source()

    assert "GardenRuntime," in source
    assert "from './web/garden-runtime.mjs'" in source
    assert "gardenRuntime.dispatch(modality,intent" in source
    assert "if(result.changed&&gardenProgram&&authenticated&&!bundleCorrupted)" in source
    assert "await runAuthenticatedGardenProgram()" in source
    assert "runtime.materializeProgram(program,result)" in source
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
    assert 'button, [role="button"], .fi {' in source
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


def test_secret_bearing_viewer_is_offline_and_redacts_persisted_world_until_authentication():
    source = _viewer_source()

    assert "cdn.jsdelivr.net" not in source
    assert "await import('http" not in source
    assert "_textLayoutMode='fallback'" in source
    load = source[source.index("async function loadBundle"):source.index("// ── Auth")]
    assert "authenticated=false;authenticatedBinding=null;decoded={};gardenProgram=null;gardenRuntime=null" in load
    assert "persistent:false,expectedEpoch:loadEpoch" in load
    assert "PREVIEW_WORLD_ID,PREVIEW_SEED" in load
    assert "kvGet(kRead" not in load
    assert "kvSet(kFirst" not in load
    assert "`bundle:${bundle.bundle_id}`" not in load
    assert "prepareAuthenticatedBundleGarden(" in source
    assert "publishAuthenticatedCandidate({" in source
    assert "_validateSealedBundleCrypto(attemptBundle,kdf)" in source
    assert "decodeStrictBase64" in source
    assert "validateBrowserPbkdf2Params" in source
    assert "isDevFixture=!bundle.hmac" not in source
    assert "if(!data.hmac&&!trustedDevFixture)" in source
    assert "Unsigned letter bundles are not accepted." in source
    assert "handleFile(file,{trustedDevFixture:true})" in source
    assert source.count("trustedDevFixture:true") == 1
    authenticated = source[source.index("async function prepareAuthenticatedBundleGarden"):
                           source.index("async function dispatchGardenUi")]
    assert "persistent:true,deferPersistence" in authenticated
    assert "attemptBundle,candidateBinding,{deferPersistence:true}" in source
    assert "await attempt.runtime.commitPersistence()" in source
    assert "knownLetterIds:(attemptBundle.messages||[]).map" in source
    assert "await awaitCurrent(_persistenceBinding(hmacKeyBytes))" in source
    assert "`bundle:${data.bundle_id}:${binding}`" in source
    assert "sentiments[g.id]=await awaitCurrent(_gcmDecrypt" in source
    gift_decrypt = source[source.index("// 3. Decrypt gift sentiments"):
                          source.index("if(attemptBundle.version>=2)", source.index("// 3. Decrypt gift sentiments"))]
    assert "catch(_){g._sentiment='';}" not in gift_decrypt
    assert "if(!arc||!bundle||!isDevFixture)return" in source
    assert "window.addEventListener('pagehide',()=>{purgeDecryptedState();})" in source
    assert "if(event.persisted){purgeDecryptedState();restoreGenericPreview()" in source
    assert "if(gardenRuntime)gardenRuntime.invalidate?.()" in source
    assert "document.getElementById('mem-type')?.replaceChildren()" in source
    assert "document.getElementById('mem-text')?.replaceChildren()" in source
    assert "garden?.clear?.()" in source
    assert "if(!isCurrent())return" in source
    assert "const pendingGardenRuntimes=new Set()" in source
    assert "for(const runtime of pendingGardenRuntimes)runtime.invalidate?.()" in source
    assert "if(previous&&previous!==runtime)previous.invalidate()" in source
    assert "attempt.epoch!==authEpoch||!authenticated||gardenRuntime!==attempt.runtime" in source
    assert "await attempt.runtime.commitPersistence();" in source
    assert "const unlockEpoch=authEpoch,unlockBundle=bundle" in source
    assert "if(unlockEpoch!==authEpoch||bundle!==unlockBundle)return" in source
    assert "tx.abort()" in source
    assert "tx.oncomplete" in source
    assert "cachedPassphrase" not in source


def test_v1_bundle_hmac_uses_frozen_auth_profile_not_message_kdf():
    source = _viewer_source()

    assert "const _LEGACY_BUNDLE_AUTH_KDF=Object.freeze" in source
    kdf_owner = source[source.index("function _bundleKdfParams"):
                       source.index("async function _pbkdf2Key")]
    assert "data?.version===1?_LEGACY_BUNDLE_AUTH_KDF:null" in kdf_owner
    assert "m.kdf_params" not in kdf_owner


def test_viewer_derives_modality_and_implements_reduced_motion_and_modal_contracts():
    source = _viewer_source()

    assert "inputModalityFromBrowserEvent(event)" in source
    assert "dispatchGardenUi('touch'" not in source
    assert "dispatchGardenUi('mouse'" not in source
    assert "const nativeButtonActivation=" in source
    assert "garden?.setReducedMotion?.(reducedMotionQuery.matches)" in source
    assert "const enabled=visible&&!Boolean(gardenRuntime.state?.ui?.motion_paused)" in source
    assert "refreshAfterCanonicalLiveAdvance()" in source
    assert "reducedMotionQuery.addEventListener('change',syncAmbientMotion)" in source
    assert 'aria-labelledby="mem-type" aria-describedby="mem-text"' in source
    assert "element.setAttribute('inert','')" in source
    assert "trapMemoryFocus(e)" in source
    assert "if(invoker?.isConnected)invoker.focus()" in source


def test_resize_cannot_regenerate_canonical_topology():
    source = _viewer_source()

    assert "new CanonicalGardenRenderer" in source
    assert "GardenVisualState" not in source
    assert "class PlantLayer" not in source
    assert "collisionMap" not in source
    assert "window.addEventListener('resize',()=>{if(garden)garden.onResize()" in source


def test_pages_deploy_builds_and_verifies_transitive_browser_asset_closure(tmp_path):
    deploy = DEPLOY.read_text(encoding="utf-8")
    assert "python3 scripts/prepare_pages_site.py _site" in deploy
    assert "python3 -m pip install ." in deploy
    assert "python3 scripts/verify_release_install.py" in deploy

    site = tmp_path / "site"
    prepared = subprocess.run(
        ["python3", "scripts/prepare_pages_site.py", str(site)],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    expected = {
        "index.html",
        "sealed_demo.lateletter",
        "test_fixture.lateletter",
        "public_letters/to-a-friend.lateletter",
        "to-a-friend/index.html",
        "to-chloe/index.html",
        "web/garden-atlas.mjs",
        "web/garden-sky.mjs",
        "src/lateletter/garden/data/atlas.v1.json",
        "src/lateletter/garden/data/bright-stars.v1.json",
    }
    assert expected <= {
        str(path.relative_to(site)) for path in site.rglob("*") if path.is_file()
    }
    assert "?l=to-chloe" in (site / "to-chloe/index.html").read_text(encoding="utf-8")

    (site / "src/lateletter/garden/data/atlas.v1.json").unlink()
    verified = subprocess.run(
        ["python3", "scripts/prepare_pages_site.py", str(site), "--verify-only"],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert verified.returncode != 0
    assert "missing browser asset: src/lateletter/garden/data/atlas.v1.json" in verified.stderr


def test_published_demo_bundle_is_the_verified_canonical_safe_artifact():
    root_bundle = ROOT / "sealed_demo.lateletter"
    public_bundle = ROOT / "public_letters" / "to-a-friend.lateletter"
    assert root_bundle.read_bytes() == public_bundle.read_bytes()
    bundle = read_bundle(public_bundle)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, "garden-biscuit-2026")
    program = open_garden_program("garden-biscuit-2026", bundle.garden_program)
    assert len(program["entities"]) == 4
    assert len(program["animals"]) == 1
    assert len(program["events"]) == 5


def test_release_install_verifier_checks_packaged_resources_and_public_bundle():
    verified = subprocess.run(
        ["python3", "scripts/verify_release_install.py"],
        cwd=ROOT, check=False, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_behavioral_browser_modules_pass_node_contracts():
    completed = subprocess.run(
        [
            "node", "--test",
            "tests/garden_adapters/test_garden_input.mjs",
            "tests/garden_adapters/test_garden_world.mjs",
            "tests/garden_adapters/test_garden_live_runtime.mjs",
            "tests/garden_adapters/test_garden_renderer.mjs",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
