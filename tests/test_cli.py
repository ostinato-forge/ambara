"""Tests for jurati.cli."""

from __future__ import annotations

from click.testing import CliRunner

from jurati.cli import main


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "jurati" in result.output.lower()

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "stdio" in result.output.lower() or "mcp" in result.output.lower()
