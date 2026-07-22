"""Tests for the draft editor (§8.4)."""

import os
import stat
import subprocess
from unittest.mock import patch

import pytest

from lateletter.draft_editor import (
    _EditorState,
    _run_external_editor,
    delete_draft,
    edit_draft,
    load_draft,
    save_draft,
)


# ---------------------------------------------------------------------------
# Draft file I/O
# ---------------------------------------------------------------------------

class TestDraftFiles:
    def test_save_load_roundtrip(self, tmp_path):
        path = save_draft("msg-001", "Hello world", base_dir=tmp_path)
        assert path.exists()
        assert load_draft("msg-001", base_dir=tmp_path) == "Hello world"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_overwrite(self, tmp_path):
        save_draft("msg-001", "first", base_dir=tmp_path)
        save_draft("msg-001", "second", base_dir=tmp_path)
        assert load_draft("msg-001", base_dir=tmp_path) == "second"

    def test_load_nonexistent(self, tmp_path):
        assert load_draft("nope", base_dir=tmp_path) is None

    def test_delete(self, tmp_path):
        save_draft("msg-001", "to delete", base_dir=tmp_path)
        delete_draft("msg-001", base_dir=tmp_path)
        assert load_draft("msg-001", base_dir=tmp_path) is None

    def test_delete_nonexistent(self, tmp_path):
        delete_draft("nope", base_dir=tmp_path)  # no error

    def test_delete_refuses_symlink(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("do not overwrite me")
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "msg-1.txt").symlink_to(target)
        delete_draft("msg-1", base_dir=tmp_path)
        assert target.read_text() == "do not overwrite me"


# ---------------------------------------------------------------------------
# Editor state
# ---------------------------------------------------------------------------

class TestEditorState:
    def test_empty_init(self):
        s = _EditorState()
        assert s.lines == [""] and s.cx == 0 and s.cy == 0 and not s.dirty

    def test_insert_and_newline(self):
        s = _EditorState()
        s.insert_char("a"); s.insert_char("b")
        assert s.text == "ab" and s.dirty
        s.cx = 1; s.insert_newline()
        assert s.lines == ["a", "b"] and s.cy == 1 and s.cx == 0

    def test_backspace(self):
        s = _EditorState("abc")
        s.cx = 2; s.backspace()
        assert s.text == "ac"
        # At line start — merges with previous
        s2 = _EditorState("first\nsecond")
        s2.cy = 1; s2.cx = 0; s2.backspace()
        assert s2.lines == ["firstsecond"] and s2.cx == 5
        # At origin — noop
        s3 = _EditorState("x"); s3.cx = 0; s3.backspace()
        assert s3.text == "x"

    def test_delete(self):
        s = _EditorState("abc")
        s.cx = 1; s.delete()
        assert s.text == "ac"
        # At line end — merges
        s2 = _EditorState("first\nsecond")
        s2.cx = 5; s2.delete()
        assert s2.lines == ["firstsecond"]

    def test_movement(self):
        s = _EditorState("ab\ncd\nef")
        s.move_down(); assert s.cy == 1
        s.move_down(); assert s.cy == 2
        s.move_down(); assert s.cy == 2  # clamped
        s.move_up(); assert s.cy == 1
        # Left/right with wrapping
        s.cy = 0; s.cx = 2; s.move_right()
        assert s.cy == 1 and s.cx == 0
        s.move_left()
        assert s.cy == 0 and s.cx == 2

    def test_cursor_clamp_on_short_line(self):
        s = _EditorState("abcdef\nab")
        s.cx = 5; s.move_down()
        assert s.cx == 2

    def test_dirty_only_on_edits(self):
        s = _EditorState("existing")
        assert not s.dirty
        s.move_down()
        assert not s.dirty
        s.insert_char("x")
        assert s.dirty

    def test_text_roundtrip(self):
        original = "line one\nline two\nline three"
        assert _EditorState(original).text == original


# ---------------------------------------------------------------------------
# External editor
# ---------------------------------------------------------------------------

class TestEditDraftRouting:
    def test_env_var_routes_to_external(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LATELETTER_EDITOR", "/usr/bin/true")
        with patch("lateletter.draft_editor.subprocess.run"), \
             patch("lateletter.draft_editor.load_draft", return_value="edited"), \
             patch("builtins.input", return_value="n"):
            result = edit_draft("msg-1", "initial", base_dir=tmp_path)
        assert result[0] == "edited"

    def test_accessible_routes_to_external(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LATELETTER_EDITOR", raising=False)
        with patch("lateletter.draft_editor.subprocess.run"), \
             patch("lateletter.draft_editor.load_draft", return_value="edited"), \
             patch("builtins.input", return_value="n"):
            result = edit_draft("msg-1", "initial", accessible=True, base_dir=tmp_path)
        assert result[0] == "edited"


class TestExternalEditorErrors:
    def _run(self, tmp_path, side_effect, **kw):
        output = []
        with patch("lateletter.draft_editor.subprocess.run", side_effect=side_effect):
            result = _run_external_editor(
                "msg-1", "content", "editor",
                base_dir=tmp_path, output_fn=output.append, **kw,
            )
        return result, output

    def test_not_found(self, tmp_path):
        output = []
        result = _run_external_editor(
            "msg-1", "content", "/nonexistent/editor",
            base_dir=tmp_path, output_fn=output.append,
        )
        assert result == (None, False)

    def test_nonzero_exit(self, tmp_path):
        r, _ = self._run(tmp_path, subprocess.CalledProcessError(1, "ed"))
        assert r == (None, False)

    def test_timeout(self, tmp_path):
        r, out = self._run(tmp_path, subprocess.TimeoutExpired("ed", 7200))
        assert r == (None, False)
        assert any("timed out" in l.lower() for l in out)

    def test_draft_deleted_externally(self, tmp_path):
        output = []
        with patch("lateletter.draft_editor.subprocess.run"), \
             patch("lateletter.draft_editor.load_draft", return_value=None):
            result = _run_external_editor(
                "msg-1", "content", "editor",
                base_dir=tmp_path, output_fn=output.append,
            )
        assert result == (None, False)


@pytest.mark.parametrize("answer,expect_encrypt", [("y", True), ("n", False)])
def test_encrypt_confirmation(tmp_path, answer, expect_encrypt):
    with patch("lateletter.draft_editor.subprocess.run"), \
         patch("lateletter.draft_editor.load_draft", return_value="text"), \
         patch("builtins.input", return_value=answer):
        result = _run_external_editor(
            "msg-1", "content", "editor",
            base_dir=tmp_path, output_fn=lambda x: None,
        )
    assert result == ("text", expect_encrypt)
