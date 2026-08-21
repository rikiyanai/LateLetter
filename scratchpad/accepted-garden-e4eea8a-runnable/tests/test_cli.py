"""Tests for the CLI entry point."""

import curses
from pathlib import Path
from unittest.mock import patch

from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    read_bundle,
    verify_checksum,
)
from lateletter.cli import main, _author_mode
from lateletter.garden.authoring import ActionCard, BeatCard, Timeline, When
from lateletter.garden.program import parse_program
from lateletter.intake import IntakeData
from lateletter.sealed import (
    open_garden_program,
    open_message,
    verify_bundle_hmac,
)
from lateletter.session_store import SessionStore


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
                   return_value=(data, "pass")), \
             patch("lateletter.author.run_author_workflow", return_value=0) as workflow:
            result = _author_mode(accessible=False)
        assert result == 0
        workflow.assert_called_once()
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

    def test_accessible_entrypoint_completes_questions_draft_timeline_and_v2_export(
        self, tmp_path: Path,
    ):
        store = SessionStore(base_dir=tmp_path / "author")
        output = tmp_path / "synthetic-chloe.lateletter"
        data = IntakeData(
            author_name="Synthetic Author",
            recipient_name="Chloe",
            recipient_relationship="friend",
            passphrase_hint="synthetic hint",
        )
        passphrase = "synthetic chloe phrase 2026!"
        timeline = Timeline(author_timezone="UTC", variables={"welcomed": False})
        timeline.beats.append(BeatCard(
            id="welcome",
            title="Synthetic welcome",
            track="revisit",
            when=When.fact("visit.total", ">=", 1),
            actions=(ActionCard.set_variable("welcomed", True),),
        ))
        answers = iter(
            ["Synthetic letter", "2027-07-21", "general"]
            + [part for index in range(10) for part in (f"Synthetic answer {index}", "")]
            + ["n"]
        )
        password_answers = iter([passphrase])

        with patch("lateletter.cli.SessionStore", return_value=store), patch(
            "lateletter.cli.load_intake", return_value=None,
        ), patch(
            "lateletter.cli.check_session_corruption", return_value=False,
        ), patch(
            "lateletter.intake_accessible.run_intake_accessible",
            return_value=(data, passphrase),
        ), patch(
            "lateletter.author.edit_draft",
            return_value=("Dear Chloe,\n\nSynthetic reviewed copy.\n", True),
        ), patch(
            "lateletter.author._run_garden_timeline_editor", return_value=timeline,
        ), patch(
            "lateletter.author._prompt_export_path", return_value=output,
        ):
            assert _author_mode(
                accessible=True,
                input_fn=lambda _prompt: next(answers),
                password_fn=lambda _prompt: next(password_answers),
                output_fn=lambda _line: None,
            ) == 0

        bundle = read_bundle(output)
        assert bundle.version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM
        assert verify_checksum(bundle)
        assert verify_bundle_hmac(bundle, passphrase)
        assert open_message(passphrase, bundle.messages[0])["body"].startswith(
            "Dear Chloe,"
        )
        program = parse_program(open_garden_program(passphrase, bundle.garden_program))
        assert [event.id for event in program.events] == ["welcome"]


def return_value_of(val):
    """Helper for _patch_deps — not used currently, kept for future."""
    from unittest.mock import MagicMock
    m = MagicMock()
    m.return_value = val
    return m
