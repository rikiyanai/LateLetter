"""HTTP contracts for the loopback adapter over the canonical author service."""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import threading
import zipfile
from pathlib import Path

from lateletter.author_web import create_author_server
from lateletter.bundle import Bundle
from lateletter.sealed import verify_bundle_hmac
from lateletter.session_store import SessionStore


ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _author_server(tmp_path: Path):
    server = create_author_server(
        session_store=SessionStore(base_dir=tmp_path),
        static_root=ROOT,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(
    server, method: str, path: str, *, payload=None, csrf: str | None = None,
    extra_headers: dict[str, str] | None = None,
):
    connection = http.client.HTTPConnection(*server.server_address[:2], timeout=10)
    headers = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if csrf is not None:
        headers["X-LateLetter-CSRF"] = csrf
    headers.update(extra_headers or {})
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    data = response.read()
    result = response.status, dict(response.getheaders()), data
    connection.close()
    return result


def _export_draft() -> dict:
    return {
        "author_name": "Riki",
        "recipient_name": "Mara",
        "passphrase_hint": "the road behind grandma's house",
        "garden_seed": 20260810,
        "messages": [{
            "date": "2032-06-14",
            "label": "On a good day",
            "body": "Dear Mara,\nI remember the yellow kitchen.",
        }],
        "garden_beats": {
            "author_timezone": "UTC",
            "variables": {},
            "entities": [],
            "animals": [],
            "beats": [],
        },
    }


def test_questionnaire_and_static_application_are_served(tmp_path):
    with _author_server(tmp_path) as server:
        status, _headers, data = _request(server, "GET", "/api/author/questionnaire")
        questionnaire = json.loads(data)
        assert status == 200
        assert len(questionnaire["rows"]) == 40
        assert [stage["id"] for stage in questionnaire["stages"]] == [
            "people", "letters", "gifts", "review", "export",
        ]
        assert questionnaire["passphrase_policy"]["minimum_length"] == 4

        status, _headers, data = _request(server, "GET", "/web/author-app.mjs")
        assert status == 200
        assert b"/api/author/export" in data


def test_loopback_host_origin_csrf_and_static_boundaries_are_enforced(tmp_path):
    with _author_server(tmp_path) as server:
        status, _headers, _data = _request(
            server, "GET", "/api/author/session",
            extra_headers={"Host": "attacker.example"},
        )
        assert status == 400

        status, _headers, _data = _request(
            server, "GET", "/api/author/session",
            extra_headers={"Origin": "https://attacker.example"},
        )
        assert status == 403

        status, _headers, _data = _request(
            server, "PUT", "/api/author/session",
            payload={"draft": {}, "revision": 0},
        )
        assert status == 403

        status, _headers, _data = _request(server, "GET", "/viewer-bnw.html")
        assert status == 404


def test_session_is_revisioned_and_refuses_nested_secrets(tmp_path):
    with _author_server(tmp_path) as server:
        status, _headers, data = _request(server, "GET", "/api/author/session")
        session = json.loads(data)
        assert status == 200

        draft = {"author_name": "Riki", "letters": []}
        status, _headers, data = _request(
            server, "PUT", "/api/author/session",
            payload={"draft": draft, "revision": 0}, csrf=session["csrf_token"],
        )
        assert status == 200
        assert json.loads(data)["revision"] == 1

        status, _headers, data = _request(
            server, "PUT", "/api/author/session",
            payload={"draft": draft, "revision": 0}, csrf=session["csrf_token"],
        )
        assert status == 409
        assert json.loads(data)["revision"] == 1

        hostile = {"letters": [{"meta": {"passphrase": "must-not-land"}}]}
        status, _headers, data = _request(
            server, "PUT", "/api/author/session",
            payload={"draft": hostile, "revision": 1}, csrf=session["csrf_token"],
        )
        assert status == 400
        assert "secret field" in json.loads(data)["error"]
        assert "must-not-land" not in (tmp_path / "session.json").read_text(encoding="utf-8")


def test_passphrase_advice_is_advisory_and_four_characters_export(tmp_path):
    with _author_server(tmp_path) as server:
        _, _, data = _request(server, "GET", "/api/author/session")
        csrf = json.loads(data)["csrf_token"]

        status, _headers, data = _request(
            server, "POST", "/api/author/passphrase-advice",
            payload={"passphrase": "1234"}, csrf=csrf,
        )
        assert status == 200
        assert json.loads(data)["warning"]

        status, headers, payload = _request(
            server, "POST", "/api/author/export",
            payload={
                "draft": _export_draft(),
                "passphrase": "1234",
                "passphrase_confirm": "1234",
            },
            csrf=csrf,
        )
        assert status == 200
        assert headers["X-LateLetter-Messages"] == "1"
        assert headers["X-LateLetter-Garden-Events"] == "0"
        assert ".lateletter" in headers["Content-Disposition"]
        bundle = Bundle.from_dict(json.loads(payload))
        assert verify_bundle_hmac(bundle, "1234")


def test_complete_handoff_package_contains_closed_viewer_bundle_and_instructions(tmp_path):
    with _author_server(tmp_path) as server:
        _, _, data = _request(server, "GET", "/api/author/session")
        csrf = json.loads(data)["csrf_token"]
        status, headers, payload = _request(
            server, "POST", "/api/author/export-package",
            payload={"draft": _export_draft(), "passphrase": "1234",
                     "passphrase_confirm": "1234"},
            csrf=csrf,
        )
        assert status == 200
        assert headers["Content-Type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            assert "LateLetter-handoff/index.html" in names
            assert "LateLetter-handoff/README.txt" in names
            assert "LateLetter-handoff/start.py" in names
            assert "LateLetter-handoff/web/vendor/pretext/LICENSE" in names
            packaged = [
                Bundle.from_dict(json.loads(archive.read(name)))
                for name in names
                if name.endswith(".lateletter") and name.count("/") == 1
            ]
            authored = [bundle for bundle in packaged if verify_bundle_hmac(bundle, "1234")]
            assert len(authored) == 1
            authority = json.loads(archive.read(
                "LateLetter-handoff/web/garden-accepted-paint.v1.json"
            ))
            assert authority["review_candidate_assets"] == []
            assert b"Passphrase reminder" in archive.read("LateLetter-handoff/README.txt")
