"""Tests for the a2ui-ask helper scripts.

Unit tests cover the pure helpers inside ask.py. The e2e tests run
the real scripts against a real `schemaui` binary and drive the Web session
through its HTTP API (POST /api/exit), so no browser or TTY is needed.

Set SCHEMAUI_BIN to test a specific binary; otherwise the tests use whatever
`schemaui` is on PATH and skip when none is installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY_SCRIPT = ROOT / "scripts" / "ask.py"
SH_SCRIPT = ROOT / "scripts" / "ask.sh"
EXAMPLE_SCHEMA = ROOT / "examples" / "env-schema.json"
EXAMPLE_DEFAULTS = ROOT / "examples" / "env-defaults.json"

sys.path.insert(0, str(PY_SCRIPT.parent))
import ask  # noqa: E402

BINARY = os.environ.get("SCHEMAUI_BIN") or shutil.which("schemaui")
PWSH = os.environ.get("PWSH_BIN") or shutil.which("pwsh")
needs_binary = pytest.mark.skipif(not BINARY, reason="schemaui binary not available")
needs_pwsh = pytest.mark.skipif(not PWSH, reason="pwsh not available")

ANSWER = {"environment": "prod", "replicas": 3, "enable_tls": True}

FEATURE_BRIEF_SCHEMA = ROOT / "examples" / "feature-brief.schema.json"
FEATURE_BRIEF_DEFAULTS = ROOT / "examples" / "feature-brief.defaults.json"
FEATURE_BRIEF_ANSWER = {
    "feature_name": "team-invites",
    "target_release": "next-minor",
    "platforms": ["web", "macos"],
    "expected_daily_users": 5000,
    "breaking_change": False,
    "storage": {"kind": "postgres", "connection_string": "postgres://u@h:5432/db", "pool_size": 10},
    "cache": {"enabled": True, "backend": "redis", "ttl_seconds": 600},
    "endpoints": [{"method": "POST", "path": "/api/invites", "auth_required": True}],
    "labels": {"team": "growth"},
}


# ---------------------------------------------------------------- unit tests


def test_slugify():
    assert ask.slugify("Deployment Config!") == "deployment-config"
    assert ask.slugify("  API 设置  ") == "api"
    assert ask.slugify("设置") == "question"
    assert ask.slugify("env") == "env"


def test_extract_url_from_announcement_lines():
    # current format: "<title> schemaui UI available at http://<addr>/"
    assert (
        ask.extract_url("Probe schemaui UI available at http://0.0.0.0:8787/")
        == "http://0.0.0.0:8787/"
    )
    # older binaries print "schemaui web UI available at ..."
    assert (
        ask.extract_url("schemaui web UI available at http://127.0.0.1:56615/")
        == "http://127.0.0.1:56615/"
    )
    assert ask.extract_url("Press Ctrl+C to abort the session.") is None


def test_localize_url_rewrites_wildcard_only():
    assert ask.localize_url("http://0.0.0.0:8787/") == "http://127.0.0.1:8787/"
    assert ask.localize_url("http://[::]:9000/") == "http://127.0.0.1:9000/"
    assert ask.localize_url("http://192.168.1.5:8787/") == "http://192.168.1.5:8787/"


def test_lan_url_only_for_wildcard():
    assert ask.lan_url("http://127.0.0.1:8787/") is None
    url = ask.lan_url("http://0.0.0.0:8787/")
    if url is not None:  # depends on the host having a LAN interface
        assert url.startswith("http://")
        assert url.endswith(":8787/")
        assert "0.0.0.0" not in url


def test_build_paths_layout():
    schema, answer = ask.build_paths("Deploy Config", datetime(2026, 9, 16, 10, 15, 0))
    assert schema == Path(".schemaui/schemas/deploy-config-20260916-101500.json")
    assert answer == Path(".schemaui/answers/deploy-config-20260916-101500.json")


# ----------------------------------------------------------------- e2e tests


def read_until(proc: subprocess.Popen, marker: str, timeout: float = 30) -> str:
    """Read stdout lines until one contains marker; return that line."""
    deadline = time.monotonic() + timeout
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if marker in line:
            return line
        if line == "" and proc.poll() is not None:
            break
    raise AssertionError(f"never saw {marker!r} on stdout")


def drive_session(url: str, payload: dict) -> None:
    """Play the role of the user: load the session, then Save & Exit."""
    url = url.rstrip("/")
    with urllib.request.urlopen(f"{url}/api/session", timeout=5) as resp:
        assert resp.status == 200
    req = urllib.request.Request(
        f"{url}/api/exit",
        data=json.dumps({"data": payload, "commit": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200


@needs_binary
@pytest.mark.parametrize(
    "launcher",
    [
        [sys.executable, str(PY_SCRIPT)],
        pytest.param(
            ["bash", str(SH_SCRIPT)],
            # ask.sh targets macOS/Linux; on Windows the supported twin is
            # ask.ps1 (covered by test_e2e_powershell_commit), so the Git-Bash
            # path is intentionally out of the matrix.
            marks=pytest.mark.skipif(
                sys.platform == "win32", reason="ask.sh targets macOS/Linux; Windows uses ask.ps1"
            ),
            id="shell",
        ),
    ],
    ids=["python", "shell"],
)
def test_e2e_commit_writes_answer(tmp_path: Path, launcher: list[str]):
    proc = subprocess.Popen(
        [
            *launcher,
            "--schema",
            str(EXAMPLE_SCHEMA),
            "--config",
            str(EXAMPLE_DEFAULTS),
            "--title",
            "Deploy Config",
            "--port",
            "0",
            "--no-open",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        url_line = read_until(proc, "SCHEMAUI_URL=")
        url = url_line.strip().split("=", 1)[1]
        answer_line = read_until(proc, "SCHEMAUI_ANSWER=")
        answer = tmp_path / answer_line.strip().split("=", 1)[1]
        drive_session(url, ANSWER)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill() if proc.poll() is None else None
    assert json.loads(answer.read_text()) == ANSWER


@needs_binary
@needs_pwsh
def test_e2e_powershell_commit(tmp_path: Path):
    proc = subprocess.Popen(
        [
            PWSH,
            "-NoProfile",
            "-File",
            str(ROOT / "scripts" / "ask.ps1"),
            "-Schema",
            str(EXAMPLE_SCHEMA),
            "-Config",
            str(EXAMPLE_DEFAULTS),
            "-Title",
            "Deploy Config",
            "-Port",
            "0",
            "-NoOpen",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        url = read_until(proc, "SCHEMAUI_URL=").strip().split("=", 1)[1]
        answer = tmp_path / read_until(proc, "SCHEMAUI_ANSWER=").strip().split("=", 1)[1]
        drive_session(url, ANSWER)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill() if proc.poll() is None else None
    assert json.loads(answer.read_text()) == ANSWER


@needs_binary
def test_e2e_feature_brief_full_control_showcase(tmp_path: Path):
    """The rich 11-question example loads and round-trips every control type."""
    proc = subprocess.Popen(
        [
            sys.executable,
            str(PY_SCRIPT),
            "--schema",
            str(FEATURE_BRIEF_SCHEMA),
            "--config",
            str(FEATURE_BRIEF_DEFAULTS),
            "--title",
            "Feature Requirements Brief",
            "--port",
            "0",
            "--no-open",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        url = read_until(proc, "SCHEMAUI_URL=").strip().split("=", 1)[1].rstrip("/")
        with urllib.request.urlopen(f"{url}/api/session", timeout=5) as resp:
            session = json.loads(resp.read())
        kinds = [
            next(iter(root["kind"].values()) if isinstance(root["kind"], dict) else root["kind"])
            for root in session["ui_ast"]["roots"]
        ]
        # single/multi select, text, number, boolean, oneOf composition,
        # nested object, list of records, key/value map — all present
        assert len(session["ui_ast"]["roots"]) == 11
        assert {"field", "array", "composite", "object", "key_value"} <= set(kinds)

        answer = tmp_path / read_until(proc, "SCHEMAUI_ANSWER=").strip().split("=", 1)[1]
        drive_session(url, FEATURE_BRIEF_ANSWER)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill() if proc.poll() is None else None
    assert json.loads(answer.read_text()) == FEATURE_BRIEF_ANSWER


@needs_binary
def test_e2e_timeout_kills_session(tmp_path: Path):
    proc = subprocess.Popen(
        [
            sys.executable,
            str(PY_SCRIPT),
            "--schema",
            str(EXAMPLE_SCHEMA),
            "--port",
            "0",
            "--no-open",
            "--timeout",
            "2",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    read_until(proc, "SCHEMAUI_URL=")
    assert proc.wait(timeout=15) == ask.EXIT_TIMEOUT
    assert not list(tmp_path.glob(".schemaui/answers/*.json"))


@needs_binary
def test_e2e_stdin_schema_is_persisted(tmp_path: Path):
    proc = subprocess.Popen(
        [
            sys.executable,
            str(PY_SCRIPT),
            "--schema",
            "-",
            "--topic",
            "Inline Question",
            "--port",
            "0",
            "--no-open",
        ],
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    proc.stdin.write(EXAMPLE_SCHEMA.read_text())
    proc.stdin.close()
    try:
        url = read_until(proc, "SCHEMAUI_URL=").strip().split("=", 1)[1]
        drive_session(url, ANSWER)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill() if proc.poll() is None else None
    schemas = list(tmp_path.glob(".schemaui/schemas/inline-question-*.json"))
    assert len(schemas) == 1
    assert json.loads(schemas[0].read_text())["title"] == "Deployment Environment"
    answers = list(tmp_path.glob(".schemaui/answers/inline-question-*.json"))
    assert len(answers) == 1
    assert json.loads(answers[0].read_text()) == ANSWER


def test_missing_binary_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SCHEMAUI_BIN", str(tmp_path / "no-such-binary"))
    result = subprocess.run(
        [sys.executable, str(PY_SCRIPT), "--schema", str(EXAMPLE_SCHEMA), "--no-open"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == ask.EXIT_NO_BINARY
    assert "not found" in result.stderr


def test_missing_schema_exits_6(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(PY_SCRIPT), "--schema", "nope.json", "--no-open"],
        cwd=tmp_path,
        env={**os.environ, "SCHEMAUI_BIN": BINARY or "schemaui"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == ask.EXIT_BAD_INPUT


# ------------------------------------------------------- installer scripts

INSTALL_SH = ROOT / "scripts" / "install.sh"
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"


def host_triple() -> str:
    import platform

    arch = {"x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}[
        platform.machine().lower()
    ]
    system = platform.system()
    if system == "Darwin":
        return f"{arch}-apple-darwin"
    if system == "Linux":
        return f"{arch}-unknown-linux-gnu"
    pytest.skip(f"no host triple expectation for {system}")


def test_install_sh_dry_run_detects_platform():
    env = {**os.environ, "PATH": "/usr/bin:/bin"}  # hide any installed schemaui
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert host_triple() in result.stdout
    assert "schemaui-" in result.stdout and ".tar.gz" in result.stdout
    assert "releases" in result.stdout  # resolved or fallback download URL


def test_install_sh_reports_existing_binary():
    if not BINARY:
        pytest.skip("schemaui binary not available")
    result = subprocess.run(
        ["bash", str(INSTALL_SH)],
        env={**os.environ, "PATH": f"{Path(BINARY).parent}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "already installed" in result.stdout


@needs_pwsh
def test_install_ps1_dry_run_and_platform_guard():
    # dry-run with a stripped PATH: on non-Windows the guard must fire
    script = (
        f'$env:PATH = "/usr/bin:/bin"; & "{INSTALL_PS1}" -DryRun'
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if sys.platform == "win32":
        assert result.returncode == 0
        assert "pc-windows-msvc.zip" in result.stdout
    else:
        assert result.returncode != 0
        assert "install.sh" in result.stderr
