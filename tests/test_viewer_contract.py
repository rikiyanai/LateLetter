"""Browser Garden ownership and accessibility integration contracts."""

from pathlib import Path
import json
import os
import re
import subprocess

from lateletter.bundle import read_bundle, verify_checksum
from lateletter.sealed import open_garden_program, verify_bundle_hmac


ROOT = Path(__file__).parents[1]
VIEWER = ROOT / "viewer-bnw.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


def _viewer_source() -> str:
    return VIEWER.read_text(encoding="utf-8")


def _relative_luminance(color: tuple[int, int, int]) -> float:
    channels = []
    for value in color:
        normalized = value / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _hex_color(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _alpha_contrast(foreground: str, background: str, alpha: float) -> float:
    front, back = _hex_color(foreground), _hex_color(background)
    composite = tuple(round(alpha * left + (1 - alpha) * right)
                      for left, right in zip(front, back, strict=True))
    lighter, darker = sorted(
        (_relative_luminance(composite), _relative_luminance(back)), reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


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
    assert "setSeed(" not in source
    assert "setAnimalData(" not in source
    assert "setPostComplete(" not in source
    assert "_animalData" not in source
    assert "_devAnimal" not in source
    assert "garden.state.animalData" not in source
    assert "triggerAnimalFeedReaction({objectId:target_id})" in source
    assert "let animalType=null,animalTier" not in source
    assert "animalTriggered" not in source
    assert "postComplete=!postComplete" not in source
    assert "projection?.objects.find(item=>item.kind==='animal')" not in source
    assert "target_id:animal.object_id,metadata:{control:'hud'}" in source
    assert "deliveryAnimal?.semantic_state?.bond_tier" in source
    assert "#hud.vis { opacity: 1; pointer-events: none; }" in source
    assert "#hud button { pointer-events: auto; }" in source
    assert "position: fixed; top: max(1rem, env(safe-area-inset-top));" in source
    assert source.count("startFirstRunBanner();") == 1
    assert "startFirstRunBanner();" not in source[source.index("function showGarden()"):
                                                    source.index("function showPassphrase()")]
    assert "slice(0, 24)" not in source
    assert 'aria-label="garden actions" aria-live="polite"' in source


def test_viewer_gates_diagnostics_and_exposes_compact_semantic_actions():
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
    assert 'data-garden-action="pan" data-dy="-20"' in source
    assert 'data-garden-action="pan" data-dy="20"' in source
    assert 'data-garden-action="frame"' in source
    assert 'id="garden-controls" aria-label="Garden diagnostic controls" hidden' in source
    assert 'id="garden-controls-close"' in source
    assert "return Boolean(GARDEN_DEBUG_REQUESTED&&(standaloneMode||isDevFixture))" in source
    assert "new URLSearchParams(location.search).get('garden_debug')==='1'" in source
    assert "if(gardenControlsEnabled()){" in source
    assert "controls.id='garden-controls-open'" in source
    assert "if(!syncGardenControlsAvailability())return" in source
    assert "button.dataset.contextAction=action" in source
    assert "const unavailableWithoutEditor=new Set(['move','rotate','transplant','open_journal'])" in source
    assert "guide.textContent='Choose a detail, or take a slow look around.'" in source
    assert "actions.appendChild(_mkHudButton('take a closer look'" in source
    assert "event=>focusGardenObject('previous',event),'['" in source
    assert "event=>focusGardenObject('next',event),']'" in source
    assert "garden?.setPresentationActive?.(name==='garden')" in source
    assert "dx:focused.position[0]-camera[0],dy:focused.position[1]-camera[1]" in source
    assert "metadata:{control:`${source}-frame`}" in source
    assert "gardenContextObjectId=focused?.object_id||null" in source
    assert "garden?.setFocusedObject?.(gardenRuntime.state.ui.focus_id)" in source
    assert "ArrowUp:['pan',{args:{dx:0,dy:-20}}]" in source
    assert "ArrowDown:['pan',{args:{dx:0,dy:20}}]" in source
    assert "classList.toggle('open',name==='garden')" not in source


def test_reproducible_review_clock_is_local_only_and_resets_world_persistence():
    source = _viewer_source()

    assert "new URLSearchParams(location.search).get('garden_review_time')" in source
    assert "hostname==='localhost'||hostname==='127.0.0.1'||hostname==='::1'" in source
    assert "GARDEN_REVIEW_IS_LOCAL&&GARDEN_REVIEW_TIME_SECONDS!==null" in source
    assert "const worldPersistence=persistent&&reviewTime===null" in source
    assert "now:()=>reviewTime??Math.floor(Date.now()/1000)" in source
    assert "reducedMotionQuery.matches||gardenReviewTime()!==null" in source
    assert "async function _receiptGet(key)" in source
    assert "async function _receiptSet(key,value)" in source
    assert "return gardenReviewTime()===null?kvGet(key):null" in source
    assert "if(gardenReviewTime()===null)await kvSet(key,value)" in source
    assert "kvGet(kRead(" not in source
    assert "kvGet(kFirst(" not in source
    assert "kvSet(kRead(" not in source
    assert "kvSet(kFirst(" not in source
    assert "document.documentElement.dataset.gardenReviewTime" in source


def test_every_theme_opacity_token_keeps_normal_text_at_readable_contrast():
    source = _viewer_source()
    matches = re.findall(
        r"(day|evening|night):\{text:'(#[0-9a-fA-F]{6})',"
        r"bg:'(#[0-9a-fA-F]{6})',scrim:'[^']+',"
        r"strong:'([.0-9]+)',muted:'([.0-9]+)',faint:'([.0-9]+)'\}",
        source,
    )
    assert {match[0] for match in matches} == {"day", "evening", "night"}
    for mode, foreground, background, *alphas in matches:
        for role, alpha in zip(("strong", "muted", "faint"), alphas, strict=True):
            assert _alpha_contrast(foreground, background, float(alpha)) >= 4.5, (
                mode, role,
            )
    assert "transition: opacity .25s ease; pointer-events: none" in source


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
    assert "await import(\n      './web/vendor/pretext/layout.js'" in source
    assert "_textLayoutMode='pretext'" in source
    assert "bundled PreText unavailable; using browser text fallback" in source
    assert "bundled PreText layout failed; using browser text fallback" in source
    assert "catch(error){disablePretext(error);renderBodyFallback(text,el);}" in source
    assert "_textLayoutMode='fallback'" in source
    load = source[source.index("async function loadBundle"):source.index("// ── Auth")]
    assert "authenticated=false;authenticatedBinding=null;decoded={};gardenProgram=null;gardenRuntime=null" in load
    assert "persistent:false,expectedEpoch:loadEpoch" in load
    assert "PREVIEW_WORLD_ID,PREVIEW_SEED" in load
    assert "program:PREVIEW_PROGRAM" in load
    assert "const PREVIEW_PROGRAM=Object.freeze({variables:{},entities:[],animals:[]})" in source
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
    assert "persistent:true,deferPersistence,program" in authenticated
    assert "attemptBundle,candidateBinding,{deferPersistence:true,program:programCandidate}" in source
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
    assert "garden?.setReducedMotion?.(" in source
    assert "reducedMotionQuery.matches||gardenReviewTime()!==null" in source
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


def test_garden_palette_themes_the_complete_recipient_surface():
    source = _viewer_source()

    assert "onTheme:applyGardenPageTheme" in source
    assert "root.dataset.gardenTheme=mode" in source
    assert "--opacity-strong" in source
    assert "night:{text:'#f1ede3',bg:'#0b0e16'" in source
    assert ".inbox-btn.read   { opacity: var(--opacity-strong); }" in source
    assert ".warn-st  { opacity: var(--opacity-strong);" in source
    assert "spawnAmbientBirdBurst" not in source


def test_legacy_corner_camera_is_migrated_through_the_canonical_reducer():
    source = _viewer_source()

    assert "camera[0]<=1&&camera[1]<=1&&runtime.projection.objects.length" in source
    assert "metadata:{migration:'legacy-corner-camera-v1'}" in source
    assert "await runtime.dispatch('browser_keyboard','pan'" in source
    assert "Standalone is the Garden itself; it has no synthetic letter archive." in source


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
        "web/garden-atlas.mjs",
        "web/garden-sky.mjs",
        "web/vendor/pretext/layout.js",
        "web/vendor/pretext/analysis.js",
        "web/vendor/pretext/bidi.js",
        "web/vendor/pretext/line-break.js",
        "web/vendor/pretext/measurement.js",
        "web/vendor/pretext/LICENSE",
        "src/lateletter/garden/data/atlas.v1.json",
        "src/lateletter/garden/data/bright-stars.v1.json",
    }
    assert expected <= {
        str(path.relative_to(site)) for path in site.rglob("*") if path.is_file()
    }
    assert not (site / "to-chloe/index.html").exists()

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


def test_letter_justification_gap_kinds_match_the_prepared_whitespace_profile():
    """The justified letter body must actually be reachable at runtime.

    Regression guard for a defect that every existing test missed: the viewer
    prepared its text with ``whiteSpace: 'pre-wrap'``, under which PreText
    classifies an ordinary space as ``preserved-space``. The justification
    branch, however, only recognised ``space``. The two never intersected, so
    no line was ever justified and the library did nothing but line breaking --
    while the source-string contracts above all still passed.

    Rather than assert on spelling, this drives the real vendored library with
    the exact options the viewer passes and requires that the segment kinds it
    produces overlap the set the viewer is willing to stretch.
    """
    source = _viewer_source()

    # The literal options object handed to prepareWithSegments.
    options_match = re.search(
        r"prepareWithSegments\(text,LETTER_FONT,(\{[^)]*\})\)", source
    )
    assert options_match, "could not locate the prepareWithSegments call"
    options_literal = options_match.group(1)

    # The kinds the justification path treats as stretchable gaps.
    kinds_match = re.search(
        r"JUSTIFY_GAP_KINDS=new Set\(\[([^\]]*)\]\)", source
    )
    assert kinds_match, "could not locate JUSTIFY_GAP_KINDS"
    gap_kinds = set(re.findall(r"'([^']+)'", kinds_match.group(1)))
    assert gap_kinds, "JUSTIFY_GAP_KINDS is empty"

    # Ask the vendored library, through Node, what it actually emits for those
    # options. Any prose with more than one word exercises the gap classifier.
    probe = f"""
      import {{ prepareWithSegments }} from './web/vendor/pretext/layout.js';
      // Canvas measurement is unavailable in Node, so provide the minimum
      // surface prepareWithSegments needs to segment text.
      globalThis.document = {{
        createElement: () => ({{
          getContext: () => ({{
            measureText: (t) => ({{ width: t.length * 7 }}),
            set font(_v) {{}},
            get font() {{ return ''; }},
          }}),
        }}),
      }};
      const prepared = prepareWithSegments(
        'Remember when my collar fell from the hook yesterday?',
        '13px serif',
        {options_literal}
      );
      console.log(JSON.stringify([...new Set(prepared.kinds)]));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", probe],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    emitted = set(json.loads(result.stdout.strip().splitlines()[-1]))

    assert "text" in emitted, f"probe produced no word segments: {emitted}"
    overlap = emitted & gap_kinds
    assert overlap, (
        "the viewer can never justify a line: PreText emits gap kinds "
        f"{sorted(emitted - {'text'})} under {options_literal}, but the "
        f"justification path only stretches {sorted(gap_kinds)}"
    )
