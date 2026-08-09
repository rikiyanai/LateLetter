"""Tests for the CLI entry point."""

from unittest.mock import patch

import pytest

from lateletter.cli import main


class TestMainDispatch:
    def test_no_args_shows_help(self, capsys):
        assert main([]) == 0
        assert "lateletter" in capsys.readouterr().out

    @pytest.mark.parametrize("removed_flag", ["--write", "--accessible"])
    def test_removed_terminal_author_flags_are_rejected(self, removed_flag):
        with pytest.raises(SystemExit) as excinfo:
            main([removed_flag])
        assert excinfo.value.code == 2

    def test_garden_routes_without_reintroducing_author_mode(self):
        with patch("lateletter.cli._garden_mode", return_value=0) as garden:
            assert main(["--garden", "--season", "winter"]) == 0
        garden.assert_called_once_with(season="winter")
