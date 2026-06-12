# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "ambara" / "core"
_AMBARA_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "ambara"

_FORBIDDEN_BOUNDARIES = ["git", "providers"]
_SOURCE_IO_IMPORTS = {
    "ambara.sources.auth",
    "ambara.sources.cache",
    "ambara.sources.manager",
    "ambara.sources.registry",
}


def _assert_no_boundary_imports(source_path: Path, boundary: str) -> None:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    abs_prefix = f"ambara.{boundary}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(abs_prefix), (
                    f"{source_path}: absolute import {alias.name!r} crosses {boundary} boundary"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level > 0 and module.split(".")[0] == boundary:
                raise AssertionError(f"{source_path}: relative import crosses {boundary} boundary")
            if node.level > 0 and module == "":
                for alias in node.names:
                    if alias.name.split(".")[0] == boundary:
                        raise AssertionError(
                            f"{source_path}: relative import "
                            f"{alias.name!r} crosses {boundary} boundary"
                        )
            if node.level == 0 and module.startswith(abs_prefix):
                raise AssertionError(
                    f"{source_path}: absolute import {module!r} crosses {boundary} boundary"
                )


@pytest.mark.parametrize("boundary", _FORBIDDEN_BOUNDARIES)
def test_core_modules_do_not_cross_boundary(boundary: str) -> None:
    for source_path in _CORE_ROOT.rglob("*.py"):
        _assert_no_boundary_imports(source_path, boundary)


def test_core_modules_do_not_import_source_io() -> None:
    for source_path in _CORE_ROOT.rglob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported = {node.module or ""}
            else:
                continue
            assert imported.isdisjoint(_SOURCE_IO_IMPORTS), (
                f"{source_path}: core modules must not import source I/O modules"
            )


def test_server_facade_keeps_extracted_helper_modules() -> None:
    server_path = _AMBARA_ROOT / "server.py"
    server_source = server_path.read_text()

    assert len(server_source.splitlines()) < 1300
    assert "class ServerState" not in server_source
    assert "def _format_entry" not in server_source
    assert "def _write_receipt" not in server_source
    assert "def _format_guidance" not in server_source
    for module in (
        "server_state.py",
        "server_read.py",
        "server_write.py",
        "server_guidance.py",
        "server_coordination.py",
        "server_curation.py",
    ):
        assert (_AMBARA_ROOT / module).exists()


def test_server_default_refresh_does_not_wire_legacy_signal_fetcher() -> None:
    server_source = (_AMBARA_ROOT / "server.py").read_text()
    server_signals_source = (_AMBARA_ROOT / "server_signals.py").read_text()

    assert "from ambara.providers.signals import fetch_all_signals" not in server_source
    assert "fetch_signals=fetch_all_signals" not in server_source
    assert "from ambara.providers.signals" not in server_signals_source
    assert "from ambara.sources.runtime import fetch_source_runtime_report" in server_signals_source
    assert "fetch_source_runtime_report" in server_signals_source
    assert "fetch_source_signal_report" not in server_signals_source
    assert "report.signals" not in server_signals_source
    assert "default_fetch_all_signals" not in server_signals_source
    assert "fetch_signals is default_fetch_all_signals" not in server_signals_source


def test_source_signal_report_stores_legacy_signals_natively() -> None:
    runtime_source = (_AMBARA_ROOT / "sources" / "runtime.py").read_text()
    source_signal_report = runtime_source.split("class SourceSignalReport:", 1)[1]
    source_signal_report_body = source_signal_report.split("def fetch_source_runtime_report", 1)[0]
    source_signal_report_lines = [line.strip() for line in source_signal_report_body.splitlines()]

    assert "@dataclass(frozen=True, init=False)" in runtime_source
    assert "legacy_signals: tuple[PRSignal | CoordinationSignal, ...]" in (
        source_signal_report_lines
    )
    assert "signals: tuple[PRSignal | CoordinationSignal, ...]" not in (source_signal_report_lines)
    assert "signals: tuple[PRSignal | CoordinationSignal, ...] | None = None," in (
        source_signal_report
    )
    assert 'object.__setattr__(self, "legacy_signals", legacy_signals or ())' in (
        source_signal_report
    )
    assert "def signals(self) -> tuple[PRSignal | CoordinationSignal, ...]:" in (
        source_signal_report
    )


def test_server_runtime_uses_source_input_helper_names() -> None:
    for module in (
        "server_coordination.py",
        "server_curation.py",
        "server_snapshot.py",
    ):
        source = (_AMBARA_ROOT / module).read_text()
        assert "signal_inputs_for_state" not in source
        assert "signal_inputs_for_snapshot" not in source
        assert "muted_signal_count" not in source


def test_source_aware_runtime_uses_source_input_type_alias() -> None:
    pr_signals_source = (_AMBARA_ROOT / "core/pr_signals.py").read_text()
    assert "type SourceInputLike = PRSignal | CoordinationSignal | SourceArtifact" in (
        pr_signals_source
    )
    assert "type SignalLike = SourceInputLike" in pr_signals_source
    assert "source_inputs: Sequence[SourceInputLike]" in pr_signals_source

    for module in (
        "server_source_inputs.py",
        "core/curation.py",
        "core/scope_policy.py",
        "curation/run_hygiene.py",
    ):
        source = (_AMBARA_ROOT / module).read_text()
        assert "SourceInputLike" in source


def test_core_classifier_uses_source_input_helper_names() -> None:
    pr_signals_source = (_AMBARA_ROOT / "core/pr_signals.py").read_text()
    assert "def _overlapping_paths" not in pr_signals_source
    assert "def _text_blob" not in pr_signals_source
    assert "def _make_evidence(" not in pr_signals_source
    assert "def _overlapping_source_refs" in pr_signals_source
    assert "def _source_input_text_blob" in pr_signals_source
    assert "def _make_evidence_from_pr_signal" in pr_signals_source
    assert "def _make_evidence_from_coordination" in pr_signals_source
    assert "def _classify_one_coordination(\n    source_input" in pr_signals_source
    assert "from this signal alone" not in pr_signals_source
    assert "keep this signal as background context" not in pr_signals_source
    assert "related team signal" not in pr_signals_source

    curation_source = (_AMBARA_ROOT / "core/curation.py").read_text()
    assert "_COMPLETED_SIGNAL_STATES" not in curation_source
    assert "_LOW_VALUE_SIGNAL_TERMS" not in curation_source
    assert "_COMPLETED_SOURCE_INPUT_STATES" in curation_source
    assert "_LOW_VALUE_SOURCE_INPUT_TERMS" in curation_source


def test_server_runtime_uses_source_input_scope_filter_name() -> None:
    for module in ("server_source_inputs.py", "server_snapshot.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "filter_signals" not in source
        assert "filter_source_inputs" in source


def test_server_scope_uses_source_input_policy_alias() -> None:
    source = (_AMBARA_ROOT / "server_scope.py").read_text()

    assert "policy.signal_sources" not in source
    assert "policy.source_inputs" in source


def test_source_aware_runtime_uses_source_curation_helper_name() -> None:
    for module in (
        "server_curation.py",
        "server_snapshot.py",
        "curation/run_hygiene.py",
    ):
        source = (_AMBARA_ROOT / module).read_text()
        assert "suggest_revalidation_from_signals" not in source
        assert "suggest_revalidation_from_source_inputs" in source


def test_source_aware_runtime_uses_source_advisory_names() -> None:
    server_state_source = (_AMBARA_ROOT / "server_state.py").read_text()
    snapshot_body = server_state_source.split("class ContextSnapshot:", 1)[1].split(
        "@dataclass", 1
    )[0]
    snapshot_lines = [line.strip() for line in snapshot_body.splitlines()]
    assert "source_advisories: tuple[CurationAdvisory, ...] = ()" in snapshot_lines
    assert "signal_advisories: tuple[CurationAdvisory, ...] = ()" not in snapshot_lines
    assert "muted_source_inputs_hidden: int = 0" in snapshot_lines
    assert "muted_signals_hidden: int = 0" not in snapshot_lines
    assert "def signal_advisories" not in server_state_source
    assert "def muted_signals_hidden" not in server_state_source

    server_snapshot_source = (_AMBARA_ROOT / "server_snapshot.py").read_text()
    server_snapshot_lines = [line.strip() for line in server_snapshot_source.splitlines()]
    assert "source_advisories=source_advisories," in server_snapshot_lines
    assert "signal_advisories=source_advisories," not in server_snapshot_lines
    assert "muted_source_inputs_hidden=muted_source_inputs_hidden," in (server_snapshot_lines)
    assert "muted_signals_hidden=muted_source_inputs_hidden," not in (server_snapshot_lines)
    assert "snapshot.signal_advisories" not in server_snapshot_source
    assert "snapshot.muted_signals_hidden" not in server_snapshot_source
    assert "snapshot.source_advisories" in server_snapshot_source
    assert "snapshot.muted_source_inputs_hidden" in server_snapshot_source

    for module in ("server_curation.py", "curation/hygiene_pr.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "advisory.signal_source" not in source
        assert "advisory.source_input_source" in source

    core_curation_source = (_AMBARA_ROOT / "core/curation.py").read_text()
    assert "def source_input_id" in core_curation_source
    assert "def source_input_source" in core_curation_source


def test_server_runtime_uses_source_coordination_classifier_name() -> None:
    for module in ("server_coordination.py", "server_snapshot.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "classify_signals" not in source
        assert "classify_source_inputs" in source


def test_source_aware_runtime_uses_source_sanitizer_names() -> None:
    for module in (
        "sources/safety.py",
        "server_coordination.py",
        "server_curation.py",
        "curation/hygiene_pr.py",
    ):
        source = (_AMBARA_ROOT / module).read_text()
        assert "sanitize_untrusted_signal_text" not in source
        assert "sanitize_signal_paths" not in source
        assert "sanitize_untrusted_source_text" in source or "sanitize_source_paths" in source


def test_source_safety_tracks_provider_markdown_syntax_in_core() -> None:
    context_source = (_AMBARA_ROOT / "core/context_rendering.py").read_text()
    safety_source = (_AMBARA_ROOT / "sources/safety.py").read_text()

    assert "source_text_contains_markdown_syntax" in context_source
    assert "source_text_contains_markdown_syntax" in safety_source


def test_context_rendering_uses_source_limit_names() -> None:
    source = (_AMBARA_ROOT / "core/context_rendering.py").read_text()

    assert "def render_source_evidence" in source
    assert "self._source_title_max" in source
    assert "self._source_excerpt_max" in source
    assert "self._source_max_paths" in source

    config_source = (_AMBARA_ROOT / "core/content_policy_config.py").read_text()
    assert "source_title_max_chars" in config_source
    assert "source_excerpt_max_chars" in config_source
    assert "source_max_paths" in config_source


def test_context_accounting_uses_source_excerpt_omission_names() -> None:
    server_read_source = (_AMBARA_ROOT / "server_read.py").read_text()

    assert "source_excerpts_omitted = 0" in server_read_source
    assert '"source_excerpts_omitted": source_excerpts_omitted' in server_read_source
    assert "source_excerpts_omitted_count=" in server_read_source

    accounting_source = (_AMBARA_ROOT / "core/context_accounting.py").read_text()
    assert "source_excerpts_omitted_count: int = 0" in accounting_source
    assert '"source_excerpts_omitted_count": _source_excerpts_omitted_count(inputs)' in (
        accounting_source
    )


def test_server_runtime_uses_source_scope_config_name() -> None:
    for module in ("server_coordination.py", "server_curation.py", "server_snapshot.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "signal_config_for_mute" not in source
        assert "source_config_for_mute" in source


def test_source_aware_runtime_uses_source_runtime_report_name() -> None:
    for module in ("server_signals.py", "curation/run_hygiene.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "fetch_source_signal_report" not in source
        assert "fetch_source_runtime_report" in source


def test_server_refresh_derives_aggregate_health_from_source_report() -> None:
    source = (_AMBARA_ROOT / "server_signals.py").read_text()

    assert "_sync_source_refresh_health_from_report(state, report.source_report)" in source
    assert "errors = report.source_report.source_errors" in source
    assert "errors = _source_refresh_errors" not in source
    assert "def _source_refresh_errors" not in source


def test_legacy_signal_facade_reuses_source_report_errors() -> None:
    source = (_AMBARA_ROOT / "providers/signals.py").read_text()

    assert "report.source_report.source_errors" in source
    assert "from ambara.sources.inspect import SourceInspectionReport" not in source
    assert "def _source_report_errors" not in source


def test_curation_hygiene_uses_source_config_env_name() -> None:
    source = (_AMBARA_ROOT / "curation/run_hygiene.py").read_text()

    assert "source_config = _source_config_from_env()" in source
    assert "signal_config = _signals_config_from_env()" not in source
    assert "def _source_config_from_env" in source
    assert "return _source_config_from_env()" in source


def test_source_config_owns_source_input_selector_shape() -> None:
    source_config = (_AMBARA_ROOT / "sources" / "config.py").read_text()
    git_config = (_AMBARA_ROOT / "git" / "config.py").read_text()

    assert "from ambara.git.config import PRSignalsConfig" not in source_config
    assert "class SourceInputsConfig" in source_config
    assert "PRSignalsConfig = SourceInputsConfig" in source_config
    assert "from ambara.sources.config import (" in git_config
    assert "PRSignalsConfig as PRSignalsConfig" in git_config
    assert "SourceInputsConfig" in git_config
    assert "class PRSignalsConfig" not in git_config


def test_git_config_delegates_legacy_source_env_parsing() -> None:
    source_config = (_AMBARA_ROOT / "sources" / "config.py").read_text()
    git_config = (_AMBARA_ROOT / "git" / "config.py").read_text()

    assert "source_inputs_config_from_env()" in git_config
    assert "legacy_pr_signals_config_from_env()" not in git_config
    for env_name in (
        "AMBARA_SOURCE_PROVIDER",
        "AMBARA_SOURCE_REPOS",
        "AMBARA_SOURCE_FIXTURE",
        "AMBARA_SIGNAL_PROVIDER",
        "AMBARA_PR_SIGNAL_REPOS",
        "AMBARA_PR_SIGNAL_FIXTURE",
        "AMBARA_GITLAB_BASE_URL",
        "AMBARA_JIRA_BASE_URL",
        "AMBARA_JIRA_PROJECTS",
    ):
        assert env_name in source_config
        assert env_name not in git_config


def test_runtime_modules_use_source_owned_pr_signal_config_import() -> None:
    git_config_path = _AMBARA_ROOT / "git" / "config.py"
    for source_path in _AMBARA_ROOT.rglob("*.py"):
        if source_path == git_config_path:
            continue
        source = source_path.read_text()
        assert "from ambara.git.config import PRSignalsConfig" not in source, (
            f"{source_path} must import PRSignalsConfig from ambara.sources.config"
        )


def test_source_runtime_uses_source_inputs_config_name() -> None:
    for module in (
        "cli_startup_sources.py",
        "curation/run_hygiene.py",
        "server_scope.py",
        "server_signals.py",
        "sources/runtime.py",
    ):
        source = (_AMBARA_ROOT / module).read_text()
        assert "SourceInputsConfig" in source
        assert "PRSignalsConfig" not in source


def test_runtime_modules_use_source_inputs_config_alias() -> None:
    for module in (
        "cli_file_adapter.py",
        "server.py",
        "server_coordination.py",
        "server_curation.py",
        "server_read.py",
        "server_snapshot.py",
    ):
        source = (_AMBARA_ROOT / module).read_text()
        assert "config.pr_signals" not in source
        assert "config.source_inputs" in source


def test_source_aware_runtime_uses_source_input_configured_name() -> None:
    for module in ("server.py", "server_read.py", "server_snapshot.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "_signals_configured" not in source
        assert "source_inputs_configured" in source

    server_signals_source = (_AMBARA_ROOT / "server_signals.py").read_text()
    assert "if not source_inputs_configured(config)" in server_signals_source

    for module in ("server_curation.py", "curation/run_hygiene.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "def _signals_configured" not in source
        assert "if include_signals and _signals_configured" not in source
        assert "if _signals_configured" not in source


def test_coordination_and_curation_user_text_names_source_inputs() -> None:
    for module in ("server_coordination.py", "server_curation.py", "server_snapshot.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "source input" in source
        assert "review signal(s)" not in source
        assert "coordination signals" not in source
        assert "Configured signal sources" not in source


def test_runtime_user_text_avoids_legacy_signal_language() -> None:
    sources = {
        "server.py": (_AMBARA_ROOT / "server.py").read_text(),
        "core/hygiene.py": (_AMBARA_ROOT / "core" / "hygiene.py").read_text(),
        "core/context_compiler.py": (_AMBARA_ROOT / "core" / "context_compiler.py").read_text(),
    }
    combined = "\n".join(sources.values())

    assert "Treat this as a coordination signal" not in combined
    assert "Treat it as a review signal" not in combined
    assert "Configured coordination signals are unavailable" not in combined
    assert "configured signal sources" not in combined
    assert "source input" in sources["server.py"]
    assert "Configured source inputs are unavailable" in sources["core/context_compiler.py"]


def test_source_aware_runtime_uses_source_input_baseline_names() -> None:
    source = (_AMBARA_ROOT / "server_snapshot.py").read_text()

    assert "if source_inputs_enabled and _source_input_baseline_unavailable(state)" in source
    assert '"baseline_available": not _source_input_baseline_unavailable(state)' in source
    assert "_startup_source_input_unavailable_reason(state)" in source
    assert "_SIGNAL_UNAVAILABLE_STARTUP_REASON = _SOURCE_INPUT_UNAVAILABLE_STARTUP_REASON" in source


def test_source_aware_runtime_uses_source_input_include_names() -> None:
    for module in ("server.py", "server_read.py"):
        source = (_AMBARA_ROOT / module).read_text()
        assert "include_signals=include_pr_signals" not in source
        assert "source_inputs_enabled" in source
        assert "include_source_inputs=source_inputs_enabled" in source

    snapshot_source = (_AMBARA_ROOT / "server_snapshot.py").read_text()
    assert "include_source_inputs: bool | None = None" in snapshot_source

    curation_source = (_AMBARA_ROOT / "server_curation.py").read_text()
    assert "include_source_inputs: bool | None = None" in curation_source


def test_context_tool_accepts_source_input_include_flag() -> None:
    source = (_AMBARA_ROOT / "server.py").read_text()
    assert "include_source_inputs: bool | None = None" in source
    assert "include_pr_signals: bool | None = None" in source
    assert "resolve_source_inputs_include" in source


def test_cli_scope_mute_user_text_names_source_inputs() -> None:
    source = (_AMBARA_ROOT / "cli_scope.py").read_text()

    assert "--source-input" in source
    assert "Source input/provider to mute" in source
    assert "source-input/tag scopes" in source
    assert "Coordination signal source/provider" not in source
    assert "Pass at least one scope: --project, --repo, --signal-source, or --tag." not in source


def test_demo_user_text_uses_source_fixture_env_names() -> None:
    source = (_AMBARA_ROOT / "cli_setup.py").read_text()

    assert "source fixture:" in source
    assert "signal fixture:" not in source
    assert "AMBARA_SOURCE_REPOS=org/api" in source
    assert "AMBARA_SOURCE_FIXTURE=" in source


def test_server_facade_reexports_extracted_helper_names() -> None:
    import ambara.server as server

    names = [
        "ServerState",
        "SyncHealth",
        "build_context_payload",
        "_build_search_results",
        "_format_entry",
        "_format_entry_manifest",
        "_format_result",
        "_explain_payload",
        "_format_hygiene_report",
        "_state_status_payload",
        "_health_dict",
        "_write_receipt",
        "_expire_receipt",
        "_write_path_error",
        "_propose_correction",
        "_record_correction",
        "_write_advisories_for_intent",
        "build_coordination_payload",
        "build_curation_payload",
    ]

    for name in names:
        assert hasattr(server, name)


def test_cli_facade_keeps_command_modules_extracted() -> None:
    cli_path = _AMBARA_ROOT / "cli.py"
    cli_source = cli_path.read_text()
    client_smoke_source = (_AMBARA_ROOT / "cli_client_smoke.py").read_text()
    runtime_source = (_AMBARA_ROOT / "cli_runtime.py").read_text()

    assert len(cli_source.splitlines()) < 250
    assert "@main.command" not in cli_source
    assert "def serve(" not in cli_source
    assert "def validate(" not in cli_source
    assert "def _serve_check(" not in cli_source
    assert "def _repair_project_config_then_print_doctor(" not in cli_source
    assert "register_runtime_commands(main)" in cli_source
    assert "def register_runtime_commands(" in runtime_source
    assert "def serve(" in runtime_source
    assert "def validate(" in runtime_source
    assert "def _serve_check(" in runtime_source
    assert "def _repair_project_config_then_print_doctor(" in runtime_source
    assert '@main.command("client-smoke")' not in cli_source
    assert "register_client_smoke_command(" in cli_source
    assert '@main.command("client-smoke")' in client_smoke_source
