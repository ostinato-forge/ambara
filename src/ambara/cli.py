# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI entry point: ambara serve, ambara init, ambara validate."""

from __future__ import annotations

import click

from ambara import __version__
from ambara.cli_capture import register_capture_commands
from ambara.cli_client_smoke import register_client_smoke_command
from ambara.cli_file_adapter import (
    _compile_startup_cli_packet,
    register_file_adapter_commands,
)
from ambara.cli_hooks import register_hook_commands
from ambara.cli_html import register_html_command
from ambara.cli_import import register_import_commands
from ambara.cli_inspect import register_inspect_commands
from ambara.cli_install import register_install_claude_md_command
from ambara.cli_local import register_local_commands
from ambara.cli_lookup import register_lookup_commands
from ambara.cli_mcp_config import register_mcp_config_command
from ambara.cli_posture import register_posture_command
from ambara.cli_project_config import _write_project_team_config
from ambara.cli_read_model import register_read_model_commands
from ambara.cli_runtime import (
    _repair_project_config_then_print_doctor,
    register_runtime_commands,
)
from ambara.cli_scope import register_scope_commands
from ambara.cli_setup import register_setup_commands
from ambara.cli_setup_diagnostics import register_doctor_command
from ambara.cli_sources import register_source_commands
from ambara.cli_status import register_status_command
from ambara.cli_value import (
    _build_value_rollup,
    _value_ledger_path,
    _write_startup_value_event,
)


@click.group(name="ambara")
@click.version_option(__version__)
def main() -> None:
    """Ambara: shared agent context for people and AI coding agents."""


register_runtime_commands(main)


register_import_commands(main)


register_setup_commands(main)


register_scope_commands(main)


register_lookup_commands(main)


register_capture_commands(main)


register_file_adapter_commands(main)


register_client_smoke_command(
    main,
    write_project_team_config=_write_project_team_config,
    write_startup_value_event=_write_startup_value_event,
    build_value_rollup=_build_value_rollup,
    value_ledger_path=_value_ledger_path,
)
register_doctor_command(
    main,
    repair_project_config=_repair_project_config_then_print_doctor,
)
register_status_command(main, compile_startup=_compile_startup_cli_packet)
register_posture_command(main)
register_install_claude_md_command(main)
register_hook_commands(main)
register_mcp_config_command(main)
register_source_commands(main)
register_read_model_commands(main)
register_local_commands(main)
register_html_command(main)
register_inspect_commands(main)
