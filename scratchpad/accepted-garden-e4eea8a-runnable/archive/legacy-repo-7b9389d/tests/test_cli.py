"""Tests for the CLI entry point."""

import curses
from unittest.mock import patch

from lateletter.cli import main, _author_mode
from lateletter.intake import IntakeData


class TestMainDispatch:
    def test_no_args_shows_help(self, capsys):
        assert main([]) == 0
        assert "lateletter" in capsys.readouterr().out

    def test_write_routes_to_author_mode(self):
        with patch("lateletter.cli._author_mode", return_value=0) as m:
            main(["--write"])
        m.assert_called_once_with(accessible=False)

    def test_write_accessible_routes_correctly(self):
        with patch("lateletter.cli._author_mode", return_value=0) as m:
            main(["--write", "--accessible"])
        m.assert_called_once_with(accessible=True)


class TestAuthorMode:
    def _patch_deps(self, **overrides):
        """Return a context manager patching CLI dependencies."""
        from contextlib import ExitStack
        stack = ExitStack()
        defaults = {
            "lateletter.cli.SessionStore": lambda: None,
            "lateletter.cli.load_intake": lambda *a: None,
            "lateletter.cli.check_session_corruption": lambda *a: False,
        }
        defaults.update(overrides)
        for target, val in defaults.items():
            stack.enter_context(patch(target, val if callable(val) and not isinstance(val, type) else return_value_of(val)))
        return stack

    def test_curses_error_falls_back_to_accessible(self, capsys):
        data = IntakeData(author_name="Robert", recipient_name="Maya")
        with patch("lateletter.cli.SessionStore"), \
             patch("lateletter.cli.load_intake", return_value=None), \
             patch("lateletter.cli.check_session_corruption", return_value=False), \
             patch("lateletter.intake_tui.run_intake_tui", side_effect=curses.error("no term")), \
             patch("lateletter.intake_accessible.run_intake_accessible",
                   return_value=(data, "pass")):
            result = _author_mode(accessible=False)
        assert result == 0
        assert "Robert" in capsys.readouterr().out

    def test_oserror_not_swallowed(self):
        with patch("lateletter.cli.SessionStore"), \
             patch("lateletter.cli.load_intake", return_value=None), \
             patch("lateletter.cli.check_session_corruption", return_value=False), \
             patch("lateletter.intake_tui.run_intake_tui", side_effect=OSError("disk full")):
            try:
                _author_mode(accessible=False)
                assert False, "Should have raised"
            except OSError:
                pass

    def test_corruption_warning(self, capsys):
        with patch("lateletter.cli.SessionStore"), \
             patch("lateletter.cli.load_intake", return_value=None), \
             patch("lateletter.cli.check_session_corruption", return_value=True), \
             patch("lateletter.intake_accessible.run_intake_accessible", return_value=None):
            _author_mode(accessible=True)
        assert "corrupted" in capsys.readouterr().out.lower()

    def test_none_result_exits_cleanly(self, capsys):
        with patch("lateletter.cli.SessionStore"), \
             patch("lateletter.cli.load_intake", return_value=None), \
             patch("lateletter.cli.check_session_corruption", return_value=False), \
             patch("lateletter.intake_accessible.run_intake_accessible", return_value=None):
            assert _author_mode(accessible=True) == 0
        assert "Exited" in capsys.readouterr().out


def return_value_of(val):
    """Helper for _patch_deps — not used currently, kept for future."""
    from unittest.mock import MagicMock
    m = MagicMock()
    m.return_value = val
    return m
