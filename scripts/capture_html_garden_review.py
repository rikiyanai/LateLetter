#!/usr/bin/env python3
"""Capture a candidate-only HTML Garden motion review package.

This is a visual-review tool, not an acceptance oracle.  It drives the real
visible standalone-Garden button in ``viewer-bnw.html`` with system Chrome,
records desktop and mobile video, creates static stills, derives a review GIF,
and writes a machine-readable receipt.  The receipt proves that the browser
surface moved and remained structurally healthy; a person must still watch the
complete output and decide whether the Garden meets the visual specification.

The Python ``playwright`` package, system Google Chrome, ``ffmpeg``, and
``ffprobe`` must already be installed.  The tool never downloads browsers.

Example (run a local server separately):

    python3 -m http.server 8770 --bind 127.0.0.1
    python3 scripts/capture_html_garden_review.py \
      --url http://127.0.0.1:8770/viewer-bnw.html \
      --output-dir docs/visual-review/2026-07-26/garden \
      --label 14-garden-motion-candidate

Default artifacts:

* 1600x1000, ten-second desktop WebM master and PNG still
* 390x844, ten-second mobile WebM master and PNG still
* 960x600, ten-second, 10fps looping GIF
* JSON capture and validation receipt

Existing artifacts are never overwritten.  Do not use ``garden_review_time``:
that query intentionally freezes disposable presentation motion.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Sequence
from urllib.parse import parse_qs, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESKTOP = (1600, 1000)
DEFAULT_MOBILE = (390, 844)
DEFAULT_GIF = (960, 600)
DEFAULT_DURATION_SECONDS = 10.0
DEFAULT_GIF_FPS = 10
DEFAULT_SAMPLE_COUNT = 10
DEFAULT_WARMUP_SECONDS = 2.0
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class Dimensions:
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> "Dimensions":
        match = re.fullmatch(r"([1-9][0-9]{1,4})x([1-9][0-9]{1,4})", text)
        if not match:
            raise argparse.ArgumentTypeError("dimensions must look like 1600x1000")
        width, height = (int(value) for value in match.groups())
        if width > 7680 or height > 4320:
            raise argparse.ArgumentTypeError("dimensions exceed the 7680x4320 safety limit")
        return cls(width, height)

    def slug(self) -> str:
        return f"{self.width}x{self.height}"

    def __str__(self) -> str:
        return self.slug()


@dataclass(frozen=True)
class ArtifactPaths:
    desktop_master: Path
    desktop_still: Path
    mobile_master: Path
    mobile_still: Path
    gif: Path
    receipt: Path

    def media_paths(self) -> tuple[Path, ...]:
        return (
            self.desktop_master,
            self.desktop_still,
            self.mobile_master,
            self.mobile_still,
            self.gif,
        )


def artifact_paths(
    output_dir: Path,
    label: str,
    desktop: Dimensions,
    mobile: Dimensions,
    gif: Dimensions,
) -> ArtifactPaths:
    return ArtifactPaths(
        desktop_master=output_dir / f"{label}-desktop-{desktop.slug()}.webm",
        desktop_still=output_dir / f"{label}-desktop-{desktop.slug()}.png",
        mobile_master=output_dir / f"{label}-mobile-{mobile.slug()}.webm",
        mobile_still=output_dir / f"{label}-mobile-{mobile.slug()}.png",
        gif=output_dir / f"{label}-desktop-{gif.slug()}.gif",
        receipt=output_dir / f"{label}-receipt.json",
    )


def validate_label(value: str) -> str:
    if not _LABEL_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "label must be 1-80 letters, digits, dots, underscores, or hyphens"
        )
    return value


def validate_capture_url(value: str, *, allow_remote: bool = False) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("capture URL must be an absolute http(s) URL")
    loopback = parts.hostname in {"127.0.0.1", "::1", "localhost"}
    if not loopback and not allow_remote:
        raise ValueError("capture URL must be loopback unless --allow-remote is explicit")
    query = parse_qs(parts.query)
    if "garden_review_time" in query:
        raise ValueError(
            "garden_review_time freezes presentation motion and cannot be captured"
        )
    return value


def parse_aria_object_counts(label: str | None) -> dict[str, int]:
    text = label or ""
    patterns = {
        "plants": r"\b(\d+) plants?\b",
        "fixtures": r"\b(\d+) fixtures?\b",
        "relationship_animals": r"\b(\d+) relationship animals?\b",
        "collectibles": r"\b(\d+) collectibles?\b",
    }
    counts: dict[str, int] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            counts[name] = int(match.group(1))
    return counts


def gif_loop_count_bytes(data: bytes) -> int | None:
    """Return the GIF application-extension loop count (0 means forever)."""

    for marker in (b"NETSCAPE2.0", b"ANIMEXTS1.0"):
        index = data.find(marker)
        if index < 0:
            continue
        block = index + len(marker)
        if data[block : block + 2] != b"\x03\x01":
            continue
        if block + 4 <= len(data):
            return int.from_bytes(data[block + 2 : block + 4], "little")
    return None


def _run_checked(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "no command output"
        raise RuntimeError(f"{Path(command[0]).name} failed: {detail}") from exc


def _git_state() -> dict[str, Any]:
    try:
        sha = _run_checked(("git", "rev-parse", "HEAD")).stdout.strip()
        status = _run_checked(("git", "status", "--porcelain=v1")).stdout.splitlines()
    except (FileNotFoundError, RuntimeError):
        return {"sha": None, "dirty": None}
    return {"sha": sha, "dirty": bool(status)}


def _ffprobe(path: Path) -> dict[str, Any]:
    command = (
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:"
        "format=duration",
        "-of",
        "json",
        str(path),
    )
    return json.loads(_run_checked(command).stdout)


def _first_video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams") or []
    if len(streams) != 1:
        raise ValueError(f"expected exactly one video stream, found {len(streams)}")
    return streams[0]


def _probe_duration(probe: dict[str, Any]) -> float:
    stream = _first_video_stream(probe)
    raw = stream.get("duration") or (probe.get("format") or {}).get("duration")
    if raw in {None, "N/A"}:
        raise ValueError("ffprobe did not report a duration")
    return float(raw)


def _probe_rate(stream: dict[str, Any]) -> float:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not raw or raw == "0/0":
        raise ValueError("ffprobe did not report a frame rate")
    return float(Fraction(raw))


def _framemd5_hashes(path: Path) -> list[str]:
    output = _run_checked(
        ("ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-f", "framemd5", "-")
    ).stdout
    hashes = []
    for line in output.splitlines():
        if not line or line.startswith("#"):
            continue
        hashes.append(line.rsplit(",", 1)[-1].strip())
    return hashes


def _desktop_master_command(
    raw_video: Path,
    output: Path,
    duration_seconds: float,
) -> tuple[str, ...]:
    duration = f"{duration_seconds:.3f}"
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-sseof",
        f"-{duration}",
        "-i",
        str(raw_video),
        "-t",
        duration,
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "libvpx-vp9",
        "-crf",
        "28",
        "-b:v",
        "0",
        "-pix_fmt",
        "yuv420p",
        str(output),
    )


def _gif_command(
    master: Path,
    output: Path,
    dimensions: Dimensions,
    duration_seconds: float,
    fps: int,
) -> tuple[str, ...]:
    filters = (
        f"fps={fps},scale={dimensions.width}:{dimensions.height}:flags=lanczos,"
        "split[s0][s1];"
        "[s0]palettegen=max_colors=256:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle"
    )
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        str(master),
        "-t",
        f"{duration_seconds:.3f}",
        "-vf",
        filters,
        "-loop",
        "0",
        str(output),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "observed": observed,
            "expected": expected,
        }
    )


def validate_gif(
    gif_path: Path,
    *,
    dimensions: Dimensions,
    duration_seconds: float,
    fps: int,
    min_unique_frames: int,
) -> dict[str, Any]:
    probe = _ffprobe(gif_path)
    stream = _first_video_stream(probe)
    frame_hashes = _framemd5_hashes(gif_path)
    frame_count = int(stream.get("nb_frames") or len(frame_hashes))
    unique_frames = len(set(frame_hashes))
    actual_duration = _probe_duration(probe)
    actual_fps = _probe_rate(stream)
    loop_count = gif_loop_count_bytes(gif_path.read_bytes())
    expected_frames = round(duration_seconds * fps)
    tolerance = 1.0 / fps + 0.01
    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "gif dimensions",
        (int(stream["width"]), int(stream["height"]))
        == (dimensions.width, dimensions.height),
        [int(stream["width"]), int(stream["height"])],
        [dimensions.width, dimensions.height],
    )
    _check(checks, "gif fps", abs(actual_fps - fps) < 0.01, actual_fps, fps)
    _check(
        checks,
        "gif duration",
        abs(actual_duration - duration_seconds) <= tolerance,
        actual_duration,
        duration_seconds,
    )
    _check(
        checks,
        "gif frame count",
        frame_count == expected_frames,
        frame_count,
        expected_frames,
    )
    _check(checks, "gif loops forever", loop_count == 0, loop_count, 0)
    _check(
        checks,
        "gif has unique motion frames",
        unique_frames >= min_unique_frames,
        unique_frames,
        f">={min_unique_frames}",
    )
    return {
        "probe": probe,
        "frame_count": frame_count,
        "unique_frame_count": unique_frames,
        "loop_count": loop_count,
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def validate_master(
    path: Path,
    *,
    dimensions: Dimensions,
    duration_seconds: float,
) -> dict[str, Any]:
    probe = _ffprobe(path)
    stream = _first_video_stream(probe)
    actual_dimensions = (int(stream["width"]), int(stream["height"]))
    actual_duration = _probe_duration(probe)
    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "master dimensions",
        actual_dimensions == (dimensions.width, dimensions.height),
        list(actual_dimensions),
        [dimensions.width, dimensions.height],
    )
    _check(
        checks,
        "master duration",
        abs(actual_duration - duration_seconds) <= 0.25,
        actual_duration,
        duration_seconds,
    )
    return {
        "probe": probe,
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def _capture_viewport(
    browser: Any,
    *,
    url: str,
    dimensions: Dimensions,
    raw_video_dir: Path,
    raw_video_name: str,
    still_path: Path,
    duration_seconds: float,
    warmup_seconds: float,
    sample_count: int,
    timeout_ms: int,
) -> tuple[Path, dict[str, Any]]:
    context = browser.new_context(
        viewport={"width": dimensions.width, "height": dimensions.height},
        record_video_dir=str(raw_video_dir),
        record_video_size={"width": dimensions.width, "height": dimensions.height},
        device_scale_factor=1,
        reduced_motion="no-preference",
        color_scheme="light",
    )
    page = context.new_page()
    video = page.video
    page.set_default_timeout(timeout_ms)
    page_errors: list[str] = []
    console_errors: list[str] = []
    bad_responses: list[dict[str, Any]] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "response",
        lambda response: bad_responses.append(
            {"status": response.status, "url": response.url}
        )
        if response.status >= 400
        else None,
    )

    try:
        page.goto(url, wait_until="networkidle")
        standalone = page.locator("#btn-standalone")
        standalone.wait_for(state="visible")
        standalone.click()
        page.locator("#hud.vis").wait_for(state="visible")
        page.locator("#g div").first.wait_for(state="attached")
        page.wait_for_timeout(round(warmup_seconds * 1000))

        samples: list[dict[str, Any]] = []
        interval_ms = duration_seconds * 1000 / sample_count
        for index in range(sample_count):
            text = page.locator("#g").inner_text()
            samples.append(
                {
                    "index": index,
                    "performance_ms": round(page.evaluate("performance.now()"), 3),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "text_length": len(text),
                }
            )
            page.wait_for_timeout(round(interval_ms))

        page.screenshot(path=str(still_path))
        aria_label = page.locator("#g").get_attribute("aria-label")
        details = {
            "dimensions": asdict(dimensions),
            "title": page.locator("#hud-author").inner_text(),
            "aria_label": aria_label,
            "object_counts": parse_aria_object_counts(aria_label),
            "reduced_motion": bool(
                page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
            ),
            "dom_samples": samples,
            "unique_dom_sample_count": len(
                {sample["text_sha256"] for sample in samples}
            ),
            "page_errors": page_errors,
            "console_errors": console_errors,
            "bad_responses": bad_responses,
        }
    finally:
        context.close()

    if video is None:
        raise RuntimeError("Playwright did not provide a recorded video")
    raw_video = raw_video_dir / raw_video_name
    video.save_as(str(raw_video))
    return raw_video, details


def _validate_browser_capture(
    details: dict[str, Any],
    *,
    sample_count: int,
    min_unique_dom_samples: int,
    name: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    _check(
        checks,
        f"{name} sampled Garden text",
        len(details["dom_samples"]) >= sample_count,
        len(details["dom_samples"]),
        f">={sample_count}",
    )
    _check(
        checks,
        f"{name} Garden DOM moved",
        details["unique_dom_sample_count"] >= min_unique_dom_samples,
        details["unique_dom_sample_count"],
        f">={min_unique_dom_samples}",
    )
    _check(
        checks,
        f"{name} reduced motion disabled",
        details["reduced_motion"] is False,
        details["reduced_motion"],
        False,
    )
    _check(
        checks,
        f"{name} page errors",
        not details["page_errors"],
        details["page_errors"],
        [],
    )
    _check(
        checks,
        f"{name} console errors",
        not details["console_errors"],
        details["console_errors"],
        [],
    )
    _check(
        checks,
        f"{name} bad responses",
        not details["bad_responses"],
        details["bad_responses"],
        [],
    )
    _check(
        checks,
        f"{name} ARIA object counts",
        set(details["object_counts"])
        == {"plants", "fixtures", "relationship_animals", "collectibles"},
        details["object_counts"],
        "all four canonical object-kind counts",
    )
    return checks


def _artifact_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _ensure_dependencies() -> None:
    missing = [
        command for command in ("git", "ffmpeg", "ffprobe")
        if shutil.which(command) is None
    ]
    if missing:
        raise RuntimeError(f"missing required command(s): {', '.join(missing)}")
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Python Playwright is required; install it without downloading a browser"
        ) from exc


def capture_package(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    _ensure_dependencies()
    url = validate_capture_url(args.url, allow_remote=args.allow_remote)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(
        output_dir, args.label, args.desktop, args.mobile, args.gif
    )
    collisions = [path for path in (*paths.media_paths(), paths.receipt) if path.exists()]
    if collisions:
        joined = ", ".join(str(path) for path in collisions)
        raise FileExistsError(f"refusing to overwrite existing review artifacts: {joined}")

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "review_status": "candidate_only",
        "acceptance_claim": False,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "git": _git_state(),
        "settings": {
            "desktop": asdict(args.desktop),
            "mobile": asdict(args.mobile),
            "gif": asdict(args.gif),
            "duration_seconds": args.duration,
            "gif_fps": args.fps,
            "warmup_seconds": args.warmup,
            "sample_count": args.samples,
            "min_unique_dom_samples": args.min_unique_dom_samples,
            "min_unique_gif_frames": args.min_unique_gif_frames,
            "browser": "system Google Chrome via Playwright channel=chrome",
        },
        "captures": {},
        "artifacts": {},
        "validation": {"checks": [], "passed": False},
        "operator_signoff_required": True,
    }

    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="lateletter-garden-capture-") as temp:
        raw_dir = Path(temp)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                raw_desktop, desktop_details = _capture_viewport(
                    browser,
                    url=url,
                    dimensions=args.desktop,
                    raw_video_dir=raw_dir,
                    raw_video_name="desktop-raw.webm",
                    still_path=paths.desktop_still,
                    duration_seconds=args.duration,
                    warmup_seconds=args.warmup,
                    sample_count=args.samples,
                    timeout_ms=args.timeout_ms,
                )
                raw_mobile, mobile_details = _capture_viewport(
                    browser,
                    url=url,
                    dimensions=args.mobile,
                    raw_video_dir=raw_dir,
                    raw_video_name="mobile-raw.webm",
                    still_path=paths.mobile_still,
                    duration_seconds=args.duration,
                    warmup_seconds=args.warmup,
                    sample_count=args.samples,
                    timeout_ms=args.timeout_ms,
                )
            finally:
                browser.close()

        _run_checked(
            _desktop_master_command(
                raw_desktop, paths.desktop_master, args.duration
            )
        )
        _run_checked(
            _desktop_master_command(raw_mobile, paths.mobile_master, args.duration)
        )
        _run_checked(
            _gif_command(
                paths.desktop_master,
                paths.gif,
                args.gif,
                args.duration,
                args.fps,
            )
        )

    receipt["captures"] = {
        "desktop": desktop_details,
        "mobile": mobile_details,
    }
    receipt["artifacts"] = {
        "desktop_master": _artifact_record(paths.desktop_master),
        "desktop_still": _artifact_record(paths.desktop_still),
        "mobile_master": _artifact_record(paths.mobile_master),
        "mobile_still": _artifact_record(paths.mobile_still),
        "gif": _artifact_record(paths.gif),
    }
    desktop_validation = validate_master(
        paths.desktop_master,
        dimensions=args.desktop,
        duration_seconds=args.duration,
    )
    mobile_validation = validate_master(
        paths.mobile_master,
        dimensions=args.mobile,
        duration_seconds=args.duration,
    )
    gif_validation = validate_gif(
        paths.gif,
        dimensions=args.gif,
        duration_seconds=args.duration,
        fps=args.fps,
        min_unique_frames=args.min_unique_gif_frames,
    )
    checks = [
        *_validate_browser_capture(
            desktop_details,
            sample_count=args.samples,
            min_unique_dom_samples=args.min_unique_dom_samples,
            name="desktop",
        ),
        *_validate_browser_capture(
            mobile_details,
            sample_count=args.samples,
            min_unique_dom_samples=args.min_unique_dom_samples,
            name="mobile",
        ),
        *desktop_validation["checks"],
        *mobile_validation["checks"],
        *gif_validation["checks"],
    ]
    _check(
        checks,
        "desktop and mobile object counts agree",
        desktop_details["object_counts"] == mobile_details["object_counts"],
        {
            "desktop": desktop_details["object_counts"],
            "mobile": mobile_details["object_counts"],
        },
        "identical counts",
    )
    receipt["media_validation"] = {
        "desktop_master": desktop_validation,
        "mobile_master": mobile_validation,
        "gif": gif_validation,
    }
    passed = all(check["passed"] for check in checks)
    receipt["validation"] = {"checks": checks, "passed": passed}
    paths.receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt, passed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture candidate-only desktop/mobile HTML Garden video, stills, "
            "a GIF, and a motion-validation receipt."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--url", required=True, help="viewer-bnw.html URL")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="review artifact directory"
    )
    parser.add_argument(
        "--label", required=True, type=validate_label, help="artifact checkpoint label"
    )
    parser.add_argument(
        "--desktop",
        type=Dimensions.parse,
        default=Dimensions(*DEFAULT_DESKTOP),
        help="desktop master viewport",
    )
    parser.add_argument(
        "--mobile",
        type=Dimensions.parse,
        default=Dimensions(*DEFAULT_MOBILE),
        help="mobile master viewport",
    )
    parser.add_argument(
        "--gif",
        type=Dimensions.parse,
        default=Dimensions(*DEFAULT_GIF),
        help="desktop GIF output dimensions",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
        help="motion-only duration in seconds",
    )
    parser.add_argument(
        "--fps", type=int, default=DEFAULT_GIF_FPS, help="GIF frames per second"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLE_COUNT,
        help="Garden DOM samples per viewport",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=DEFAULT_WARMUP_SECONDS,
        help="seconds to wait after the Garden becomes visible",
    )
    parser.add_argument(
        "--min-unique-dom-samples",
        type=int,
        default=5,
        help="minimum unique sampled #g text hashes per viewport",
    )
    parser.add_argument(
        "--min-unique-gif-frames",
        type=int,
        default=30,
        help="minimum unique decoded GIF frames",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Playwright action timeout",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit an explicit non-loopback capture URL",
    )
    return parser


def _validate_cli_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not (1.0 <= args.duration <= 120.0):
        parser.error("--duration must be between 1 and 120 seconds")
    if not (1 <= args.fps <= 30):
        parser.error("--fps must be between 1 and 30")
    if args.samples < 10:
        parser.error("--samples must be at least 10")
    if not (0 <= args.warmup <= 30):
        parser.error("--warmup must be between 0 and 30 seconds")
    if not (2 <= args.min_unique_dom_samples <= args.samples):
        parser.error("--min-unique-dom-samples must be between 2 and --samples")
    expected_frames = round(args.duration * args.fps)
    if not (2 <= args.min_unique_gif_frames <= expected_frames):
        parser.error(
            "--min-unique-gif-frames must be between 2 and duration*fps"
        )
    if not (1_000 <= args.timeout_ms <= 120_000):
        parser.error("--timeout-ms must be between 1000 and 120000")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_cli_args(parser, args)
    paths = artifact_paths(
        args.output_dir.resolve(), args.label, args.desktop, args.mobile, args.gif
    )
    try:
        _receipt, passed = capture_package(args)
    except Exception as exc:
        # Preserve a bounded failure record when capture created only part of a
        # checkpoint.  Never replace an existing receipt from an earlier run.
        try:
            paths.receipt.parent.mkdir(parents=True, exist_ok=True)
            if not paths.receipt.exists():
                paths.receipt.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "review_status": "candidate_capture_failed",
                            "acceptance_claim": False,
                            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                            "url": args.url,
                            "git": _git_state(),
                            "error": str(exc),
                            "operator_signoff_required": True,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
        except OSError:
            pass
        print(f"capture failed: {exc}", file=sys.stderr)
        return 2
    print(f"review receipt: {paths.receipt}")
    print(
        "candidate evidence validated; operator visual sign-off is still required"
        if passed
        else "candidate evidence failed validation; inspect the receipt",
        file=sys.stdout if passed else sys.stderr,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
