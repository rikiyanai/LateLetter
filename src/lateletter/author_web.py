"""author_web — a loopback-only HTTP adapter in front of ``author_service``.

WHY THIS EXISTS
===============
The author service is a Python library. The author UI is an HTML page. This
module is the smallest thing that lets one talk to the other: a standard-library
HTTP server, bound to the loopback interface only, that exposes the service's
existing functions and serves the one page that uses them.

It deliberately contains no letter logic. Drafts are checked, sealed and
round-tripped by ``lateletter.author_service``; drafts are persisted by
``lateletter.session_store``. If a rule about letters appears to live here,
it is in the wrong file.

THREAT MODEL
============
This server runs on the author's own machine while they write a letter that is
often the most private thing they will ever write. It assumes the machine
itself is trusted and everything else is not:

* It binds 127.0.0.1 and refuses a Host header naming anything else, so a page
  on another site cannot reach it through a hostname that points at loopback.
* It requires a CSRF token, minted per server run and read only from a header,
  on every state-changing request, so a page the author happens to have open
  cannot silently drive the API.
* It refuses any Origin it did not serve.
* It caps request bodies, because an unbounded read on a local server is a
  trivial way to exhaust memory.
* It serves exactly one HTML file plus a small allow-list of asset directories,
  and re-checks the real path afterwards, so no request can escape the root.
* It never writes a passphrase anywhere: not to the session store, not to a
  log line, not into an error message. Request logging is disabled outright
  rather than filtered, because a filter is one forgotten field away from
  leaking a letter.

TEST COVERAGE — KNOWN GAP
=========================
There is no dedicated test file for this module. A local tooling hook rejects
any file whose content carries bare HTTP method tokens, so the intended
``tests/test_author_web.py`` could not be created, and it was deliberately not
smuggled past that hook by disguising the method names.

What that leaves unproven HERE, by automated test: the request guards
(Host, Origin, CSRF, body cap, non-JSON bodies), the revision-conflict path,
static-path traversal refusal, and that an export response carries openable
bytes with an attachment filename.

What IS proven elsewhere: everything this module delegates to. The service it
calls is covered by ``tests/test_author_service.py``, including that exported
bytes match the command-line builder byte for byte, that a sealed bundle opens
again, and that a secret buried anywhere in a draft is refused. The gap is in
the HTTP layer only, and it is verified by hand rather than by suite.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from lateletter.author_service import (
    AuthorServiceError, export_bundle_bytes, find_passphrase_key,
    validate_draft,
)
from lateletter.session_store import SessionStore

# Largest request body accepted, in bytes. A letter is text; a megabyte is
# already far more than any plausible draft, and the cap exists so a malformed
# or hostile request cannot make the server allocate without bound.
MAX_BODY_BYTES = 1_048_576

# Only these hosts may appear in the Host header. Anything else means the
# request reached us by a route we did not intend to exist.
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})

# Static files the author page needs, relative to the repository root. Nothing
# outside these is reachable, whatever path is requested.
STATIC_FILE_ALLOWLIST = ("author.html", "web/author-app.mjs")
STATIC_DIR_ALLOWLIST = ("web/vendor",)

# Keys used inside the session store's session document.
DRAFT_KEY = "author_draft"
REVISION_KEY = "author_draft_revision"


def _json_bytes(payload: Any) -> bytes:
    """Encode a response body as UTF-8 JSON."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class AuthorRequestHandler(BaseHTTPRequestHandler):
    """One HTTP request against the author API or its static page.

    The server instance carries the shared state — session store, CSRF token,
    static root — so the handler stays a per-request object with no state of
    its own beyond what the base class gives it.
    """

    server_version = "LateLetterAuthor/1"
    protocol_version = "HTTP/1.1"

    # ── logging ────────────────────────────────────────────────────────────
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Silence request logging entirely.

        A request line can carry a draft in a query string, and a body can
        carry a passphrase. Rather than trying to redact, nothing is logged at
        all: this server serves exactly one local user who can see the UI.
        """

    # ── helpers ────────────────────────────────────────────────────────────
    def _send(self, status: int, payload: Any) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # This API is for one local page; nothing may embed or sniff it.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        """Send a refusal. The message never echoes request content back."""
        self._send(status, {"error": message})

    def _host_allowed(self) -> bool:
        """True when the Host header names loopback and nothing else.

        Refusing an unexpected Host is what stops a hostile page reaching a
        local server through a hostname that points at 127.0.0.1.
        """
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return False
        # Strip the port; IPv6 literals keep their brackets.
        if host.startswith("["):
            name = host.split("]")[0] + "]"
        else:
            name = host.split(":")[0]
        return name in ALLOWED_HOSTS

    def _origin_allowed(self) -> bool:
        """True when there is no Origin, or it is one we could have served.

        A same-origin fetch from our own page may omit Origin entirely; a
        cross-site request cannot forge it.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        for scheme in ("http://", "https://"):
            if origin.startswith(scheme):
                rest = origin[len(scheme):]
                name = rest.split("]")[0] + "]" if rest.startswith("[") else rest.split(":")[0]
                return name in ALLOWED_HOSTS
        return False

    def _csrf_ok(self) -> bool:
        """True when the request carries this run's CSRF token.

        Read from a header only. A token accepted from a form field or a query
        string could be supplied by a cross-site navigation; a custom header
        cannot be set cross-origin without a preflight we never approve.
        """
        supplied = self.headers.get("X-LateLetter-CSRF") or ""
        return secrets.compare_digest(supplied, self.server.csrf_token)

    def _read_json(self) -> tuple[Any, str | None]:
        """Read and parse a JSON request body.

        Returns ``(value, error)``. Enforces a declared, sane Content-Length and
        the body cap before reading a single byte, so an oversized or
        chunk-encoded request is refused rather than buffered.
        """
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return None, "chunked request bodies are not accepted"
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return None, "Content-Length is required"
        try:
            length = int(raw_length)
        except ValueError:
            return None, "Content-Length must be an integer"
        if length < 0:
            return None, "Content-Length must not be negative"
        if length > MAX_BODY_BYTES:
            return None, "request body is too large"
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type != "application/json":
            return None, "Content-Type must be application/json"
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "request body must be valid UTF-8 JSON"
        if not isinstance(value, dict):
            return None, "request body must be a JSON object"
        return value, None

    def _guard(self, *, needs_csrf: bool) -> bool:
        """Run the checks every request shares. True means carry on."""
        if not self._host_allowed():
            self._error(400, "unrecognised Host")
            return False
        if not self._origin_allowed():
            self._error(403, "cross-origin request refused")
            return False
        if needs_csrf and not self._csrf_ok():
            self._error(403, "missing or invalid CSRF token")
            return False
        return True

    # ── session persistence ────────────────────────────────────────────────
    def _load_session(self) -> tuple[dict, int]:
        """Return the stored draft and its revision number.

        A missing or malformed session is reported as an empty draft at
        revision 0 rather than an error: an author opening the page for the
        first time is the normal case, not a fault.
        """
        data = self.server.session_store.load_session() or {}
        draft = data.get(DRAFT_KEY)
        revision = data.get(REVISION_KEY, 0)
        if not isinstance(draft, dict):
            draft = {}
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            revision = 0
        return draft, revision

    # ── routes ─────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
        if not self._guard(needs_csrf=False):
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/author/session":
            draft, revision = self._load_session()
            self._send(200, {
                "draft": draft,
                "revision": revision,
                "csrf_token": self.server.csrf_token,
            })
            return
        self._serve_static(path)

    def do_PUT(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
        if not self._guard(needs_csrf=True):
            return
        if self.path.split("?", 1)[0] != "/api/author/session":
            self._error(404, "unknown endpoint")
            return
        body, error = self._read_json()
        if error is not None:
            self._error(413 if "too large" in error else 400, error)
            return

        draft = body.get("draft")
        if not isinstance(draft, dict):
            self._error(400, "draft must be an object")
            return

        # Deep scan before anything is written. The session store rejects
        # secret-looking keys at its own top level; a draft from a browser is
        # nested, so a passphrase could otherwise be buried inside a message or
        # a guided answer and be persisted to disk.
        secret_at = find_passphrase_key(draft)
        if secret_at is not None:
            self._error(400, f"draft contains a secret field at '{secret_at}'")
            return

        stored_draft, stored_revision = self._load_session()
        supplied = body.get("revision")
        if not isinstance(supplied, int) or isinstance(supplied, bool):
            self._error(400, "revision must be an integer")
            return
        if supplied != stored_revision:
            # Another tab, or the same tab after a restart, has already moved
            # on. Overwriting here would silently destroy the newer draft.
            self._send(409, {
                "error": "draft revision is stale",
                "revision": stored_revision,
                "draft": stored_draft,
            })
            return

        next_revision = stored_revision + 1
        session = self.server.session_store.load_session() or {}
        session[DRAFT_KEY] = draft
        session[REVISION_KEY] = next_revision
        try:
            self.server.session_store.save_session(session)
        except ValueError as exc:
            # The store's own secret-key guard fired; surface it rather than
            # letting the write appear to have succeeded.
            self._error(400, str(exc))
            return
        self._send(200, {"revision": next_revision})

    def do_POST(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
        if not self._guard(needs_csrf=True):
            return
        path = self.path.split("?", 1)[0]
        if path not in {"/api/author/validate", "/api/author/export"}:
            self._error(404, "unknown endpoint")
            return
        body, error = self._read_json()
        if error is not None:
            self._error(413 if "too large" in error else 400, error)
            return

        draft = body.get("draft")
        if not isinstance(draft, dict):
            self._error(400, "draft must be an object")
            return

        if path == "/api/author/validate":
            result = validate_draft(draft)
            self._send(200, {
                "ok": result.ok, "errors": result.errors, "preview": result.preview,
            })
            return

        self._export(draft, body)

    def _export(self, draft: dict, body: dict) -> None:
        """Seal the draft and return the bundle as a download.

        The passphrase and its confirmation exist only as local variables for
        the duration of this call. They are not stored, not echoed, and not
        included in any error.
        """
        passphrase = body.get("passphrase")
        confirmation = body.get("passphrase_confirm")
        if not isinstance(passphrase, str) or not isinstance(confirmation, str):
            self._error(400, "passphrase and passphrase_confirm are required")
            return
        if not secrets.compare_digest(passphrase, confirmation):
            self._error(400, "passphrase and confirmation do not match")
            return
        try:
            payload, summary = export_bundle_bytes(draft, passphrase)
        except AuthorServiceError as exc:
            self._send(422, {"error": "draft cannot be exported", "issues": exc.issues})
            return
        except ValueError as exc:
            self._send(422, {"error": "draft cannot be exported", "issues": [str(exc)]})
            return

        filename = self._download_filename(draft)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"',
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        # Counts only; useful for the UI to confirm what it just produced.
        self.send_header("X-LateLetter-Messages", str(summary["message_count"]))
        self.send_header("X-LateLetter-Garden-Events", str(summary["garden_event_count"]))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _download_filename(draft: dict) -> str:
        """Build a safe attachment filename from the draft.

        Reduced to a conservative character set so nothing in an author's own
        text can inject a quote, a path separator, or a header break into the
        Content-Disposition value.
        """
        raw = str(draft.get("bundle_name") or draft.get("author_name") or "letter")
        safe = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in raw
        ).strip("-")
        return f"{(safe or 'letter')[:48]}.lateletter"

    # ── static files ───────────────────────────────────────────────────────
    def _serve_static(self, path: str) -> None:
        """Serve the author page and its same-origin assets, or refuse.

        Every request is matched against an allow-list first and only then
        turned into a real path on disk, and the outcome is re-checked against
        the static root. Checking only beforehand would miss a symlink;
        checking only afterwards would allow probing.
        """
        relative = "author.html" if path in {"/", "/author.html"} else path.lstrip("/")
        allowed = (
            relative in STATIC_FILE_ALLOWLIST
            or any(relative.startswith(f"{prefix}/") for prefix in STATIC_DIR_ALLOWLIST)
        )
        if not allowed or ".." in relative.split("/"):
            self._error(404, "not found")
            return
        root = self.server.static_root.resolve()
        target = (root / relative).resolve()
        # Afterwards the file must still be inside the static root, and must be
        # a real file rather than a directory or a device.
        if not target.is_file() or root not in target.parents:
            self._error(404, "not found")
            return
        data = target.read_bytes()
        guessed = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", guessed)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class AuthorServer(ThreadingHTTPServer):
    """A loopback HTTP server carrying the shared author-session state."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        session_store: SessionStore,
        static_root: Path,
    ) -> None:
        super().__init__(address, AuthorRequestHandler)
        self.session_store = session_store
        self.static_root = Path(static_root)
        # Minted per run. Restarting the server invalidates every token an old
        # page still holds, which is the behaviour we want: a stale tab must
        # re-read the session before it can write.
        self.csrf_token = secrets.token_urlsafe(32)


def create_author_server(
    *,
    session_store: SessionStore | None = None,
    static_root: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> AuthorServer:
    """Build an author server without starting it.

    host  refused unless it is a loopback address; this server must never be
          reachable from another machine, because the draft it holds is the
          author's private letter
    port  0 asks the operating system for a free port, which is what tests use

    The caller owns the returned server's lifecycle: call ``serve_forever`` in
    a thread, or drive it request by request. Returning an unstarted server is
    what makes the whole API testable without opening a browser.
    """
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("the author server may only bind a loopback address")
    root = Path(static_root) if static_root is not None else Path.cwd()
    return AuthorServer(
        (host, port),
        session_store=session_store or SessionStore(),
        static_root=root,
    )


def main() -> None:
    """Run the author server until interrupted.

    Prints the loopback URL for the author to open. The port defaults to 0 so
    the operating system picks a free one; the printed URL is therefore the
    authoritative address, not a number to guess at.
    """
    import argparse

    parser = argparse.ArgumentParser(description="LateLetter author server")
    parser.add_argument("--port", type=int, default=8765,
                        help="loopback port to bind (0 picks a free one)")
    parser.add_argument("--static-root", type=Path, default=Path.cwd(),
                        help="directory holding author.html and web/vendor")
    arguments = parser.parse_args()

    server = create_author_server(
        static_root=arguments.static_root, port=arguments.port,
    )
    host, port = server.server_address[:2]
    print(f"author server on http://{host}:{port}/  (loopback only)")
    print("the passphrase is never stored; close this window when you are done.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
