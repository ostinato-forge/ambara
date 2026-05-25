"""Tests for jurati.curation.run_hygiene CLI entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jurati.curation.run_hygiene import main
from jurati.git.curation import CurationReportWriteResult


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
        assert mock_body.call_args.kwargs["curation_advisories"] == []
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

    @patch("jurati.curation.run_hygiene.build_hygiene_pr_body", return_value="body")
    @patch("jurati.curation.run_hygiene.suggest_revalidation_from_signals")
    @patch("jurati.curation.run_hygiene.fetch_all_signals", return_value=["signal"])
    @patch("jurati.curation.run_hygiene.detect_contradictions", return_value=[])
    @patch("jurati.curation.run_hygiene.summarize_lifecycle")
    @patch("jurati.curation.run_hygiene.find_stale_entries", return_value=[])
    @patch("jurati.curation.run_hygiene.load_index_from_repo")
    @patch("jurati.curation.run_hygiene.fetch_all")
    @patch("jurati.curation.run_hygiene.ensure_repo", return_value="/tmp/repo")
    def test_fetches_configured_signals_for_curation(
        self,
        _ensure: MagicMock,
        _fetch: MagicMock,
        mock_load: MagicMock,
        _stale: MagicMock,
        mock_hygiene: MagicMock,
        _contra: MagicMock,
        mock_fetch_signals: MagicMock,
        mock_suggest: MagicMock,
        mock_body: MagicMock,
    ) -> None:
        mock_index = MagicMock()
        mock_index.entries = {}
        mock_load.return_value = mock_index
        mock_hygiene.return_value.revalidation = []
        mock_suggest.return_value = ["advisory"]

        with patch.dict(
            "os.environ",
            {
                "JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                "JURATI_PR_SIGNAL_REPOS": "org/api, org/web",
            },
            clear=True,
        ):
            main()

        signal_config = mock_fetch_signals.call_args.args[0]
        assert signal_config.repos == ("org/api", "org/web")
        mock_suggest.assert_called_once()
        assert mock_suggest.call_args.args == ([], ["signal"])
        assert mock_suggest.call_args.kwargs["recency_days"] == 30
        assert mock_body.call_args.kwargs["curation_advisories"] == ["advisory"]

    @patch(
        "jurati.curation.run_hygiene.materialize_curation_report",
        return_value=CurationReportWriteResult(
            branch="jurati/curation/custom",
            commit="a" * 40,
            path=".jurati/curation/2026-05-25-weekly-hygiene.md",
        ),
    )
    @patch("jurati.curation.run_hygiene.build_hygiene_pr_body", return_value="body")
    @patch("jurati.curation.run_hygiene.detect_contradictions", return_value=[])
    @patch("jurati.curation.run_hygiene.summarize_lifecycle")
    @patch("jurati.curation.run_hygiene.find_stale_entries", return_value=["stale"])
    @patch("jurati.curation.run_hygiene.load_index_from_repo")
    @patch("jurati.curation.run_hygiene.fetch_all")
    @patch("jurati.curation.run_hygiene.ensure_repo", return_value="/tmp/repo")
    def test_can_write_curation_review_branch_when_findings_exist(
        self,
        _ensure: MagicMock,
        _fetch: MagicMock,
        mock_load: MagicMock,
        _stale: MagicMock,
        mock_hygiene: MagicMock,
        _contra: MagicMock,
        _body: MagicMock,
        mock_materialize: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_index = MagicMock()
        mock_index.entries = {}
        mock_load.return_value = mock_index
        mock_hygiene.return_value.revalidation = []

        with patch.dict(
            "os.environ",
            {
                "JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                "JURATI_CURATION_WRITE": "true",
                "JURATI_CURATION_BRANCH": "jurati/curation/custom",
            },
            clear=True,
        ):
            main()

        mock_materialize.assert_called_once()
        assert mock_materialize.call_args.args == ("/tmp/repo", "body")
        assert mock_materialize.call_args.kwargs["branch"] == "jurati/curation/custom"
        assert mock_materialize.call_args.kwargs["base"] == "origin/main"
        out = capsys.readouterr().out
        assert "Wrote curation review branch:" in out
        assert "jurati/curation/custom" in out

    @patch("jurati.curation.run_hygiene.materialize_curation_report")
    @patch("jurati.curation.run_hygiene.build_hygiene_pr_body", return_value="clean")
    @patch("jurati.curation.run_hygiene.detect_contradictions", return_value=[])
    @patch("jurati.curation.run_hygiene.summarize_lifecycle")
    @patch("jurati.curation.run_hygiene.find_stale_entries", return_value=[])
    @patch("jurati.curation.run_hygiene.load_index_from_repo")
    @patch("jurati.curation.run_hygiene.fetch_all")
    @patch("jurati.curation.run_hygiene.ensure_repo", return_value="/tmp/repo")
    def test_does_not_write_curation_review_branch_without_findings(
        self,
        _ensure: MagicMock,
        _fetch: MagicMock,
        mock_load: MagicMock,
        _stale: MagicMock,
        mock_hygiene: MagicMock,
        _contra: MagicMock,
        _body: MagicMock,
        mock_materialize: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_index = MagicMock()
        mock_index.entries = {}
        mock_load.return_value = mock_index
        mock_hygiene.return_value.revalidation = []

        with patch.dict(
            "os.environ",
            {
                "JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                "JURATI_CURATION_WRITE": "yes",
            },
            clear=True,
        ):
            main()

        mock_materialize.assert_not_called()
        assert "No curation review branch written; no findings." in capsys.readouterr().out
