"""Regression tests for package and Horizon file-based server imports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _build_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "SUPABASE_DATABASE_URL",
        "MCP_ALLOWED_SCHEMAS",
        "MCP_ALLOWED_TABLES",
        "PYTHONPATH",
    ):
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["PYTHONUTF8"] = "1"
    return environment


def test_installed_package_imports_mcp_without_runtime_secrets(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastmcp import FastMCP; "
                "from supabase_mcp.server import mcp; "
                "assert isinstance(mcp, FastMCP); "
                "print(type(mcp).__name__)"
            ),
        ],
        cwd=tmp_path,
        env=_build_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FastMCP"


def test_horizon_file_entrypoint_can_be_inspected_without_runtime_secrets() -> None:
    project_root = Path(__file__).resolve().parents[1]
    executable_name = "fastmcp.exe" if os.name == "nt" else "fastmcp"
    fastmcp_executable = Path(sys.executable).with_name(executable_name)
    result = subprocess.run(
        [
            str(fastmcp_executable),
            "inspect",
            "src/supabase_mcp/server.py:mcp",
        ],
        cwd=project_root,
        env=_build_environment(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Supabase Read-Only" in result.stdout
