#!/usr/bin/env python3
"""
notify.py — LateLetter email notification script (§13.3)

Reads a .lateletter bundle's plaintext metadata, checks today's date against
message delivery dates, and sends a warm email via SMTP when a letter becomes
due for the first time.

Usage:
  python notify.py <bundle.lateletter> --to recipient@example.com \
      --smtp-host smtp.gmail.com --smtp-port 587 \
      --smtp-user sender@gmail.com --smtp-password "app-password"

  python notify.py <bundle.lateletter> --print-cron  # show cron/launchd setup

The script never reads or decrypts letter content. It only reads:
  - bundle_id, author_name (for the email body)
  - message dates (to check if a letter is due)
  - notification.email, notification.steward_name (optional, from bundle metadata)

A local sent-log at ~/.lateletter/notify_sent.json prevents duplicate sends.
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

_SENT_LOG = Path.home() / ".lateletter" / "notify_sent.json"


# ---------------------------------------------------------------------------
# Sent-log helpers
# ---------------------------------------------------------------------------

def _load_sent(bundle_id: str) -> set[str]:
    """Return set of message IDs already notified for this bundle."""
    if not _SENT_LOG.exists():
        return set()
    try:
        data = json.loads(_SENT_LOG.read_text(encoding="utf-8"))
        return set(data.get(bundle_id, []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_sent(bundle_id: str, sent: set[str]) -> None:
    _SENT_LOG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data: dict[str, list[str]] = {}
    if _SENT_LOG.exists():
        try:
            data = json.loads(_SENT_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data[bundle_id] = sorted(sent)
    tmp = _SENT_LOG.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8",
                  opener=lambda p, flags: os.open(p, flags, 0o600)) as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, _SENT_LOG)
    except OSError as exc:
        print(f"  Warning: could not update sent-log: {exc}", file=sys.stderr)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Bundle reading (plaintext metadata only — no decryption)
# ---------------------------------------------------------------------------

def _read_bundle_meta(path: Path) -> dict:
    """Read and return the raw bundle JSON dict. No decryption."""
    try:
        raw = path.read_bytes()
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  Error reading bundle: {exc}", file=sys.stderr)
        sys.exit(1)


def _due_messages(bundle: dict, today: date, already_sent: set[str]) -> list[dict]:
    """Return messages that are due today and have not been notified yet."""
    due = []
    for msg in bundle.get("messages", []):
        msg_id = msg.get("id", "")
        msg_date_str = msg.get("date", "")
        if not msg_id or not msg_date_str:
            continue
        if msg_id in already_sent:
            continue
        try:
            msg_date = date.fromisoformat(msg_date_str)
        except ValueError:
            continue
        if today >= msg_date:
            due.append(msg)
    return due


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def _build_email(
    to_addr: str,
    author_name: str,
    steward_name: str | None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "A letter is waiting for you"
    msg["To"] = to_addr

    body_parts = [
        f"{author_name} left a letter for you.",
        "Open your LateLetter garden to read it.",
    ]
    if steward_name:
        body_parts.append(f"\nIf you need help opening it, ask {steward_name}.")

    msg.set_content("\n".join(body_parts))
    return msg


def _send(
    email_msg: EmailMessage,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_addr: str,
) -> None:
    email_msg["From"] = from_addr
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(email_msg)


# ---------------------------------------------------------------------------
# Cron / launchd setup instructions
# ---------------------------------------------------------------------------

_CRON_TEMPLATE = """\
# ── cron setup (runs daily at 9am) ──────────────────────────────────────────
# Add the following line to your crontab (run: crontab -e):
#
#   0 9 * * * /usr/bin/python3 {script} {bundle} --to {email} \\
#       --smtp-host SMTP_HOST --smtp-port 587 \\
#       --smtp-user YOUR_EMAIL --smtp-password YOUR_APP_PASSWORD
#
# Replace SMTP_HOST, YOUR_EMAIL, YOUR_APP_PASSWORD with real values.
# For Gmail: smtp-host=smtp.gmail.com, use an App Password (not your login password).

# ── launchd setup (macOS) ────────────────────────────────────────────────────
# Create ~/Library/LaunchAgents/lateletter.notify.plist:
#
# <?xml version="1.0" encoding="UTF-8"?>
# <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
#     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
# <plist version="1.0"><dict>
#   <key>Label</key><string>lateletter.notify</string>
#   <key>ProgramArguments</key>
#   <array>
#     <string>/usr/bin/python3</string>
#     <string>{script}</string>
#     <string>{bundle}</string>
#     <string>--to</string><string>{email}</string>
#     <string>--smtp-host</string><string>SMTP_HOST</string>
#     <string>--smtp-port</string><string>587</string>
#     <string>--smtp-user</string><string>YOUR_EMAIL</string>
#     <string>--smtp-password</string><string>YOUR_APP_PASSWORD</string>
#   </array>
#   <key>StartCalendarInterval</key>
#   <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
#   <key>RunAtLoad</key><false/>
# </dict></plist>
#
# Then: launchctl load ~/Library/LaunchAgents/lateletter.notify.plist
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Send email notification when a LateLetter letter is due.",
    )
    ap.add_argument("bundle", help=".lateletter bundle file path")
    ap.add_argument("--to", dest="to_addr", help="Recipient email address")
    ap.add_argument("--from", dest="from_addr", help="Sender email address (defaults to --smtp-user)")
    ap.add_argument("--smtp-host", default="")
    ap.add_argument("--smtp-port", type=int, default=587)
    ap.add_argument("--smtp-user", default="")
    ap.add_argument("--smtp-password", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be sent without sending")
    ap.add_argument("--print-cron", action="store_true",
                    help="Print cron/launchd setup instructions and exit")
    args = ap.parse_args()

    bundle_path = Path(args.bundle).resolve()
    if not bundle_path.exists():
        print(f"  Error: file not found: {bundle_path}", file=sys.stderr)
        sys.exit(1)

    bundle = _read_bundle_meta(bundle_path)
    bundle_id = bundle.get("bundle_id", "")
    author_name = bundle.get("author_name", "Someone you love")
    notification = bundle.get("notification") or {}
    to_addr = args.to_addr or notification.get("email", "")
    steward_name = notification.get("steward_name")
    from_addr = args.from_addr or args.smtp_user

    if args.print_cron:
        print(_CRON_TEMPLATE.format(
            script=Path(__file__).resolve(),
            bundle=bundle_path,
            email=to_addr or "RECIPIENT_EMAIL",
        ))
        return

    if not to_addr:
        print("  Error: --to address required (or set notification.email in bundle)",
              file=sys.stderr)
        sys.exit(1)

    today = date.today()
    already_sent = _load_sent(bundle_id)
    due = _due_messages(bundle, today, already_sent)

    if not due:
        print(f"  No new notifications to send for {bundle_path.name}.")
        return

    if args.dry_run:
        for msg in due:
            print(f"  [dry-run] Would notify: message {msg['id'][:8]} (due {msg['date']})")
        return

    if not args.smtp_host or not args.smtp_user or not args.smtp_password:
        print("  Error: --smtp-host, --smtp-user, --smtp-password required for sending",
              file=sys.stderr)
        sys.exit(1)

    newly_sent: set[str] = set()
    for msg in due:
        email_msg = _build_email(to_addr, author_name, steward_name)
        try:
            _send(email_msg, args.smtp_host, args.smtp_port,
                  args.smtp_user, args.smtp_password, from_addr)
            print(f"  Sent notification for message {msg['id'][:8]} (due {msg['date']})")
            newly_sent.add(msg["id"])
        except (smtplib.SMTPException, OSError) as exc:
            print(f"  Error sending for message {msg['id'][:8]}: {exc}", file=sys.stderr)

    if newly_sent:
        _save_sent(bundle_id, already_sent | newly_sent)


if __name__ == "__main__":
    main()
