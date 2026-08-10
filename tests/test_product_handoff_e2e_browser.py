"""One exported artifact traverses the browser author and recipient products.

This is the successor to the deleted mechanics-first Garden browser harness.
It proves product lineage only: author controls create one file, then ordinary
recipient controls open that exact file on desktop and touch-mobile Chromium.
Garden appearance and interaction acceptance remain separate operator gates.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lateletter.author_web import create_author_server
from lateletter.bundle import Bundle
from lateletter.sealed import open_message, verify_bundle_hmac
from lateletter.session_store import SessionStore


playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed in this interpreter",
)

ROOT = Path(__file__).resolve().parents[1]
PASSPHRASE = "1234"
LETTER_LABEL = "The yellow kitchen"
LETTER_BODY = "Dear Mara,\n\nThe yellow kitchen.\n\nLove, Riki"
LETTER_ROWS = LETTER_BODY.split("\n")


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        """The test asserts browser failures directly; suppress HTTP chatter."""


@contextlib.contextmanager
def _product_servers(tmp_path: Path):
    author = create_author_server(
        session_store=SessionStore(base_dir=tmp_path / "author-session"),
        static_root=ROOT,
    )
    static_handler = partial(_QuietStaticHandler, directory=str(ROOT))
    recipient = ThreadingHTTPServer(("127.0.0.1", 0), static_handler)
    author_thread = threading.Thread(target=author.serve_forever, daemon=True)
    recipient_thread = threading.Thread(target=recipient.serve_forever, daemon=True)
    author_thread.start()
    recipient_thread.start()
    try:
        author_host, author_port = author.server_address[:2]
        recipient_host, recipient_port = recipient.server_address[:2]
        yield (
            f"http://{author_host}:{author_port}",
            f"http://{recipient_host}:{recipient_port}",
        )
    finally:
        author.shutdown()
        recipient.shutdown()
        author.server_close()
        recipient.server_close()
        author_thread.join(timeout=5)
        recipient_thread.join(timeout=5)


def _watch_browser(page) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    bad_responses: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console.{message.type}: {message.text}")
        if message.type == "error"
        and "favicon.ico" not in ((message.location or {}).get("url", "") + message.text)
        else None,
    )
    page.on(
        "response",
        lambda response: bad_responses.append(
            f"HTTP {response.status}: {response.url}",
        )
        if response.status >= 400 and "favicon.ico" not in response.url
        else None,
    )
    return errors, bad_responses


def _export_once_through_author(page, origin: str, tmp_path: Path) -> Path:
    page.goto(f"{origin}/", wait_until="networkidle")
    page.locator("#btn-start-fresh").click()
    page.locator('section[data-stage="people"]').wait_for(state="visible")
    page.locator("#f-author-name").fill("Riki")
    page.locator("#f-recipient-name").fill("Mara")
    page.locator("#f-timezone").select_option("UTC")
    page.locator("#f-hint").fill("the room with the yellow table")
    page.locator("#btn-next").click()
    page.locator('section[data-stage="letters"]').wait_for(state="visible")
    page.locator("#f-letter-date").fill(date.today().isoformat())
    page.locator("#f-letter-label").fill(LETTER_LABEL)
    page.locator("#f-letter-body").fill(LETTER_BODY)
    page.locator("#btn-next").click()
    page.locator('section[data-stage="gifts"]').wait_for(state="visible")
    page.locator("#btn-next").click()
    page.locator('section[data-stage="review"]').wait_for(state="visible")
    page.locator("#btn-validate").click()
    page.locator("#validate-state").filter(has_text="1 letter ready").wait_for()
    page.locator("#btn-next").click()
    page.locator('section[data-stage="export"]').wait_for(state="visible")
    page.locator("#pp-new").fill(PASSPHRASE)
    page.locator("#pp-confirm").fill(PASSPHRASE)
    with page.expect_download() as download_info:
        page.locator("#btn-export").click()
    download = download_info.value
    artifact = tmp_path / download.suggested_filename
    download.save_as(artifact)
    return artifact


def _open_exact_artifact_as_recipient(
    browser,
    *,
    origin: str,
    artifact: Path,
    expected_sha256: str,
    viewport: tuple[int, int],
    touch: bool,
) -> dict[str, object]:
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        has_touch=touch,
        is_mobile=touch,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.set_default_timeout(30_000)
    errors, bad_responses = _watch_browser(page)
    try:
        page.goto(f"{origin}/viewer-bnw.html", wait_until="networkidle")
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_sha256
        page.locator("#file-input").set_input_files(str(artifact))

        page.locator("#hud.vis").wait_for(state="visible")
        page.locator("#g div").first.wait_for(state="attached")
        assert "planted for you by Riki" in page.locator("#hud-author").inner_text()
        assert page.locator("#g").inner_text().strip()

        page.get_by_role("button", name="open letters").click()
        page.locator("#s-passphrase.active").wait_for(state="visible")
        page.locator("#pp-input").fill(PASSPHRASE)
        page.locator("#btn-unlock").click()
        page.locator("#s-archive.active").wait_for(state="visible")

        due = page.locator("#arc-content .inbox-btn.unread")
        assert due.count() == 1
        due.click()
        page.locator("#s-reading.active").wait_for(state="visible")
        page.locator("#letter-body .ll").first.wait_for(state="attached")
        assert page.locator("#lm-label").inner_text() == LETTER_LABEL
        painted_rows = page.locator("#letter-body .ll").all_text_contents()
        assert painted_rows == LETTER_ROWS
        assert "\n".join(painted_rows) == LETTER_BODY

        page.locator("#btn-all").click()
        page.locator("#s-archive.active").wait_for(state="visible")
        assert page.locator("#arc-content .inbox-btn.read").inner_text() == LETTER_LABEL
        page.locator("#btn-arc-back").click()
        page.locator("#hud.vis").wait_for(state="visible")

        return {
            "viewport": viewport,
            "touch": touch,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "painted_rows": painted_rows,
            "errors": errors,
            "bad_responses": bad_responses,
        }
    finally:
        context.close()


def test_one_browser_author_download_reaches_desktop_and_mobile_recipients(tmp_path):
    with _product_servers(tmp_path) as (author_origin, recipient_origin):
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as failure:  # pragma: no cover - environment dependent
                pytest.skip(f"installed Chromium is unavailable: {failure}")
            try:
                author_context = browser.new_context(
                    accept_downloads=True,
                    viewport={"width": 1280, "height": 900},
                )
                author_page = author_context.new_page()
                author_errors, author_bad_responses = _watch_browser(author_page)
                artifact = _export_once_through_author(
                    author_page, author_origin, tmp_path,
                )
                author_context.close()

                artifact_bytes = artifact.read_bytes()
                artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
                bundle = Bundle.from_dict(json.loads(artifact_bytes))
                assert verify_bundle_hmac(bundle, PASSPHRASE)
                assert open_message(PASSPHRASE, bundle.messages[0])["body"] == LETTER_BODY

                results = [
                    _open_exact_artifact_as_recipient(
                        browser,
                        origin=recipient_origin,
                        artifact=artifact,
                        expected_sha256=artifact_sha256,
                        viewport=(1280, 900),
                        touch=False,
                    ),
                    _open_exact_artifact_as_recipient(
                        browser,
                        origin=recipient_origin,
                        artifact=artifact,
                        expected_sha256=artifact_sha256,
                        viewport=(390, 844),
                        touch=True,
                    ),
                ]
            finally:
                browser.close()

    assert author_errors == []
    assert author_bad_responses == []
    assert {result["sha256"] for result in results} == {artifact_sha256}
    assert all(result["painted_rows"] == LETTER_ROWS for result in results)
    assert all(result["errors"] == [] for result in results)
    assert all(result["bad_responses"] == [] for result in results)
