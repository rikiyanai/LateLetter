"""A real browser drives author intake through a verified bundle download."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

from lateletter.author_web import create_author_server
from lateletter.bundle import Bundle
from lateletter.sealed import open_garden_program, open_message, verify_bundle_hmac
from lateletter.session_store import SessionStore


playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed in this interpreter",
)

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _author_server(tmp_path: Path):
    server = create_author_server(
        session_store=SessionStore(base_dir=tmp_path / "session"),
        static_root=ROOT,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_author_can_resume_write_schedule_and_export_one_canonical_bundle(tmp_path):
    browser_errors: list[str] = []
    with _author_server(tmp_path) as origin, playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch()
        except Exception as failure:  # pragma: no cover - environment dependent
            pytest.skip(f"installed Chromium is unavailable: {failure}")
        context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: browser_errors.append(f"pageerror: {error}"))
        page.on(
            "console",
            lambda message: browser_errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error" else None,
        )
        try:
            page.goto(f"{origin}/", wait_until="networkidle")
            page.locator("#btn-start-fresh").click()
            page.locator('section[data-stage="people"]').wait_for(state="visible")

            page.locator("#f-author-name").fill("Riki")
            page.locator("#f-author-relationship").fill("their father")
            page.locator("#f-recipient-name").fill("Mara")
            page.locator("#f-recipient-relationship").fill("daughter")
            page.locator("#f-timezone").select_option("UTC")
            page.locator("#f-hint").fill("the road behind grandma's house")
            page.locator("#btn-next").click()
            page.locator('section[data-stage="letters"]').wait_for(state="visible")

            page.locator("#letter-shape-host button", has_text="a good day").click()
            assert page.locator('[data-question-id="B2"]').inner_text() == (
                "What might they not think to ask on a day like this?"
            )
            page.locator('[data-question-id="B2"]').click()
            assert page.locator("#letter-shape-host").is_hidden()
            assert "What might they not think to ask" in page.locator("#f-letter-body").input_value()
            page.locator("#f-letter-date").fill("2032-06-14")
            page.locator("#f-letter-label").fill("On a good day")
            page.locator("#f-letter-body").fill(
                "Dear Mara,\n\nI remember the yellow kitchen.\n\nLove, Riki",
            )
            page.locator("#btn-add-letter").click()  # Intentionally incomplete.
            page.locator("#btn-next").click()
            page.locator('section[data-stage="gifts"]').wait_for(state="visible")

            page.locator("#f-story-arc").check()
            page.locator("#f-rabbit-name").fill("Juniper")
            page.locator("#btn-next").click()
            page.locator('section[data-stage="review"]').wait_for(state="visible")
            assert "1" in page.locator("#review-summary-host").inner_text()
            assert "incomplete" in page.locator("#review-errors").inner_text()

            page.locator("#btn-validate").click()
            page.locator("#validate-state").filter(has_text="1 letter ready").wait_for()
            page.locator("#garden-story-preview").wait_for(state="visible")
            preview_trace = json.loads(
                page.locator("#garden-story-preview").get_attribute("data-trace")
            )
            assert preview_trace == [
                "arc.rabbit-arrives",
                "arc.third-visit-rose",
                "arc.bonded-autumn-gift",
            ]
            page.locator("#btn-next").click()
            page.locator('section[data-stage="export"]').wait_for(state="visible")
            page.locator("#pp-new").fill("1234")
            page.locator("#pp-confirm").fill("1234")
            assert page.locator("#btn-export").is_enabled()

            with page.expect_download() as download_info:
                page.locator("#btn-export").click()
            download = download_info.value
            saved = tmp_path / download.suggested_filename
            download.save_as(saved)

            bundle = Bundle.from_dict(json.loads(saved.read_text(encoding="utf-8")))
            assert verify_bundle_hmac(bundle, "1234")
            assert len(bundle.messages) == 1
            assert open_message("1234", bundle.messages[0])["body"].startswith("Dear Mara")
            program = open_garden_program("1234", bundle.garden_program)
            assert program["animals"][0]["name"] == "Juniper"
            assert [event["id"] for event in program["events"]] == preview_trace

            node = shutil.which("node")
            if node is None:  # pragma: no cover - release environment has Node
                pytest.skip("Node.js is unavailable for browser-runtime parity")
            script = """
              import {evaluateGardenProgram} from './web/garden-program.mjs';
              let raw=''; for await (const chunk of process.stdin) raw+=chunk;
              const {program,letterId,seed}=JSON.parse(raw);
              let state={applied_occurrences:[],variables:{}};
              const stages=[
                {'letter.read':[letterId],'visit.total':1,'animal.bond_tier':0,'season.current':'summer'},
                {'letter.read':[letterId],'visit.total':3,'animal.bond_tier':1,'season.current':'summer'},
                {'letter.read':[letterId],'visit.total':4,'animal.bond_tier':3,'season.current':'autumn'},
              ];
              const applied=[];
              for(const facts of stages){
                const result=await evaluateGardenProgram(program,state,{seed,facts});
                state=result.state;
                applied.push(...result.trace.filter(row=>row.status==='applied').map(row=>row.event_id));
              }
              process.stdout.write(JSON.stringify({applied,state}));
            """
            completed = subprocess.run(
                [node, "--input-type=module", "-e", script], cwd=ROOT,
                input=json.dumps({"program": program,
                                  "letterId": bundle.messages[0].id,
                                  "seed": bundle.garden_seed}),
                text=True, capture_output=True, check=True,
            )
            runtime = json.loads(completed.stdout)
            assert runtime["applied"] == preview_trace
            assert runtime["state"]["entities"]["arc.rabbit"]["present"] is True
            assert runtime["state"]["entities"]["arc.autumn-rose"]["planted"] is True
            assert runtime["state"]["entities"]["arc.autumn-gift"]["revealed"] is True

            page.locator("#pp-new").fill("1234")
            page.locator("#pp-confirm").fill("1234")
            with page.expect_download() as package_info:
                page.locator("#btn-export-package").click()
            package_path = tmp_path / "handoff.zip"
            package_info.value.save_as(package_path)
            with zipfile.ZipFile(package_path) as package:
                names = set(package.namelist())
                assert "LateLetter-handoff/index.html" in names
                assert "LateLetter-handoff/README.txt" in names
                assert "LateLetter-handoff/start.py" in names

            session_text = (tmp_path / "session" / "session.json").read_text(encoding="utf-8")
            assert '"passphrase"' not in session_text
            saved_session = json.loads(session_text)["author_draft"]
            assert len(saved_session["letters"]) == 2
            assert saved_session["passphrase_hint"] == "the road behind grandma's house"
        finally:
            context.close()
            browser.close()

    assert browser_errors == [], browser_errors
