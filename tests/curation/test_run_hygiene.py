"""Tests for jurati.curation.run_hygiene CLI entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jurati.curation.run_hygiene import main


class TestRunHygiene:
    def test_missing_remote_raises_system_exit(self) -> None:
        with patch.dict("os.environ", {}, clear=True), pytest.raises(SystemExit):
            main()

    @patch("jurati.curation.run_hygiene.build_hygiene_pr_body", return_value="## Report")
    @patch("jurati.curation.run_hygiene.detect_contradictions", return_value=[])
    @patch("jurati.curation.run_hygiene.summarize_lifecycle")
    @patch("jurati.curation.run_hygiene.find_stale_entries", return_value=[])
    @patch("jurati.curation.run_hygiene.load_index_from_repo")
    @patch("jurati.curation.run_hygiene.fetch_all")
    @patch("jurati.curation.run_hygiene.ensure_repo", return_value="/tmp/repo")
    def test_calls_pipeline_in_order(
        self,
        mock_ensure: MagicMock,
        mock_fetch: MagicMock,
        mock_load: MagicMock,
        mock_stale: MagicMock,
        mock_hygiene: MagicMock,
        mock_contra: MagicMock,
        mock_body: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_index = MagicMock()
        mock_index.entries = {}
        mock_load.return_value = mock_index
        mock_hygiene.return_value.revalidation = []

        with patch.dict(
            "os.environ",
            {"JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git"},
            clear=True,
        ):
            main()

        mock_ensure.assert_called_once_with("https://example.com/kb.git", "/tmp/jurati-knowledge")
        mock_fetch.assert_called_once()
        mock_load.assert_called_once()
        mock_stale.assert_called_once()
        mock_hygiene.assert_called_once()
        mock_body.assert_called_once()
        assert mock_body.call_args.kwargs["revalidation_entries"] is (
            mock_hygiene.return_value.revalidation
        )
        assert capsys.readouterr().out.strip() == "## Report"

    @patch("jurati.curation.run_hygiene.build_hygiene_pr_body", return_value="body")
    @patch("jurati.curation.run_hygiene.detect_contradictions", return_value=[])
    @patch("jurati.curation.run_hygiene.summarize_lifecycle")
    @patch("jurati.curation.run_hygiene.find_stale_entries", return_value=[])
    @patch("jurati.curation.run_hygiene.load_index_from_repo")
    @patch("jurati.curation.run_hygiene.fetch_all")
    @patch("jurati.curation.run_hygiene.ensure_repo", return_value="/tmp/repo")
    def test_uses_custom_cache_dir(
        self,
        mock_ensure: MagicMock,
        mock_fetch: MagicMock,
        mock_load: MagicMock,
        _stale: MagicMock,
        mock_hygiene: MagicMock,
        _contra: MagicMock,
        _body: MagicMock,
    ) -> None:
        mock_index = MagicMock()
        mock_index.entries = {}
        mock_load.return_value = mock_index
        mock_hygiene.return_value.revalidation = []

        with patch.dict(
            "os.environ",
            {
                "JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                "JURATI_CACHE_DIR": "/custom/cache",
            },
            clear=True,
        ):
            main()

        mock_ensure.assert_called_once_with("https://example.com/kb.git", "/custom/cache")
