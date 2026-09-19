"""Tests for the a2ui-ask helper scripts.

Unit tests cover the pure helpers inside ask.py. The e2e tests run
the real scripts against a real `schemaui` binary and drive the Web session
through its HTTP API (POST /api/exit), so no browser or TTY is needed.

Set SCHEMAUI_BIN to test a specific binary; otherwise the tests use whatever
`schemaui` is on PATH and skip when none is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
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
    "rollout": {"rollout_percent": 20, "confidence": 0.8, "business_hours": [9, 17], "accent_color": "#6366f1"},
}

WEB_RESEARCH_SCHEMA = ROOT / "examples" / "web-research-brief.schema.json"
WEB_RESEARCH_DEFAULTS = ROOT / "examples" / "web-research-brief.defaults.json"
WEB_RESEARCH_ANSWER = {
    "topic": "最近三个月发布的新款新能源车",
    "goal": "给家里换一台新能源车做决策依据。",
    "publish_age_days": [7, 90],
    "source_types": ["官方发布", "权威媒体"],
    "delivery": {"kind": "markdown", "include_toc": True},
}

# Every control the schemaui gallery can draw, pinned to the one field in
# web-research-brief.schema.json that must draw it. The whole mapping is
# compared, so a dropped hint — or a hinted field nobody meant to add — fails
# here instead of quietly shrinking the reference form.
GALLERY_CONTROLS = {
    "/focus_terms": "text",
    "/goal": "textarea",
    "/focus_items": "slider",
    "/fetch_timeout_seconds": "slider",
    "/relevance_floor": "slider",
    "/dedup_similarity": "slider",
    "/depth_level": "slider",
    "/source_authority": "slider",
    "/freshness_weight": "slider",
    "/publish_age_days": "range",
    "/price_range": "range",
    "/confidence_band": "range",
    "/run_mode": "segmented",
    "/track_window": "range",
    "/track_sample_percent": "slider",
    "/report_language": "segmented",
    "/report_style": "radio",
    "/urgency": "segmented",
    "/include_competitor_pricing": "checkbox",
    "/accent_color": "color",
}

# The other half of that contract: a hint is opt-in, so these fields must stay
# on their shape's default control — text input, number box, `select` for the
# long enum, `switch` for the plain boolean — even though they carry bounds or
# a `format`.
SHAPE_DEFAULT_FIELDS = (
    "/topic",
    "/expected_words",
    "/max_sources",
    "/time_budget_minutes",
    "/brand_hex",
    "/market",
    "/include_charts",
)

# The launcher matrix every e2e test runs against. Both twins must keep the same
# contract, so each behavioural test is exercised through both rather than
# trusting the "same flags, same stdout contract" claim.
LAUNCHERS = [
    pytest.param([sys.executable, str(PY_SCRIPT)], id="python"),
    pytest.param(
        ["bash", str(SH_SCRIPT)],
        # ask.sh targets macOS/Linux; on Windows the supported twin is ask.ps1
        # (covered by test_e2e_powershell_commit), so the Git-Bash path is
        # intentionally out of the matrix.
        marks=pytest.mark.skipif(
            sys.platform == "win32", reason="ask.sh targets macOS/Linux; Windows uses ask.ps1"
        ),
        id="shell",
    ),
]


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


def _namespace(**overrides) -> argparse.Namespace:
    """A Namespace with the defaults `build_command` cares about."""
    base = {
        "host": "0.0.0.0",
        "config": None,
        "title": "T",
        "description": None,
        "timeout": 300,
        "force": False,
        "stdout_echo": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _build(**overrides) -> list[str]:
    return ask.build_command(
        "schemaui",
        _namespace(**overrides),
        Path("s.json"),
        Path("a.json"),
        8787,
        native_timeout=True,
    )


def test_build_command_passes_the_deadline_to_a_capable_engine():
    cmd = _build(timeout=90)
    assert cmd[cmd.index("--timeout") + 1] == "90"


def test_build_command_omits_the_deadline_for_an_older_engine():
    # A build without `--timeout` would abort on an unknown flag, so the flag
    # must be dropped entirely and the wrapper's own timer used instead.
    cmd = ask.build_command(
        "schemaui",
        _namespace(timeout=90),
        Path("s.json"),
        Path("a.json"),
        8787,
        native_timeout=False,
    )
    assert "--timeout" not in cmd


def test_build_command_never_asks_for_an_instant_deadline():
    # `--timeout 0` means "no deadline" on both sides; forwarding it would ask
    # the engine to expire the session the moment it opened.
    assert "--timeout" not in _build(timeout=0)


def test_build_command_keeps_the_deadline_before_the_greedy_output_flag():
    # `-o` swallows every following token, so a `--timeout` placed after it
    # would be read as a second output path instead of a flag.
    cmd = _build(timeout=90)
    assert cmd.index("--timeout") < cmd.index("-o")


def test_supports_native_timeout_reads_the_help_output(tmp_path, monkeypatch):
    # The positive fake is *this interpreter* running a tiny script, not a
    # #!/bin/sh file: a shebang means nothing on Windows, where only PE
    # executables can be spawned, and the probe would (correctly) report False
    # for a file it cannot run at all. SCHEMAUI_BIN is the supported injection
    # point, and "python script" passes through find_binary verbatim — that is
    # the contract the probe has to honour.
    fake = tmp_path / "fake_schemaui.py"
    fake.write_text(
        "import sys\n"
        "print('Usage: schemaui web [OPTIONS]')\n"
        "print('      --timeout <SECONDS>  abort the session after this long')\n"
    )
    monkeypatch.setenv("SCHEMAUI_BIN", f"{sys.executable} {fake}")
    assert ask.supports_native_timeout(ask.find_binary()) is True

    old = tmp_path / "old-schemaui"
    old.write_text("#!/bin/sh\necho 'Usage: schemaui web [OPTIONS]'\necho '  -o, --output'\n")
    old.chmod(0o755)
    assert ask.supports_native_timeout(str(old)) is False


def test_supports_native_timeout_survives_a_broken_binary(tmp_path: Path):
    # The probe must not turn an unhelpful binary into a crash; falling back to
    # the wrapper's own timer is always safe.
    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\nexit 127\n")
    broken.chmod(0o755)
    assert ask.supports_native_timeout(str(broken)) is False
    assert ask.supports_native_timeout(str(tmp_path / "does-not-exist")) is False


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
@pytest.mark.parametrize("launcher", LAUNCHERS)
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


def collect_nodes(nodes: list[dict]) -> list[dict]:
    """Flatten a UiAst node tree, descending into object children."""
    flat: list[dict] = []
    for node in nodes:
        flat.append(node)
        if node["kind"].get("type") == "object":
            flat.extend(collect_nodes(node["kind"]["children"]))
    return flat


@needs_binary
def test_e2e_feature_brief_full_control_showcase(tmp_path: Path):
    """The rich 12-question example loads and round-trips every control type."""
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
        assert len(session["ui_ast"]["roots"]) == 13
        assert {"field", "array", "composite", "object", "key_value"} <= set(kinds)

        # presentation hints survive the trip to the browser: the escape-hatch
        # input stays hidden until the sibling it names matches, and long-form
        # answers render as a text area.
        by_pointer = {node["pointer"]: node for node in collect_nodes(session["ui_ast"]["roots"])}
        assert by_pointer["/breaking_change_notes"]["visible_when"] == {
            "field": "breaking_change",
            "op": "equals",
            "value": True,
        }
        assert by_pointer["/breaking_change_notes"]["kind"]["multiline"] is True
        assert by_pointer["/cache/ttl_seconds"]["visible_when"]["field"] == "enabled"
        assert by_pointer["/owner_email"]["visible_when"] is None

        # the x-control hints on the rollout section also survive: slider /
        # range / colour arrive as the control the schema asked for.
        assert by_pointer["/rollout/rollout_percent"]["control"] == "slider"
        assert by_pointer["/rollout/business_hours"]["control"] == "range"
        assert by_pointer["/rollout/accent_color"]["control"] == "color"
        assert by_pointer["/rollout/rollout_percent"]["bounds"]["step"] == 5.0

        answer = tmp_path / read_until(proc, "SCHEMAUI_ANSWER=").strip().split("=", 1)[1]
        drive_session(url, FEATURE_BRIEF_ANSWER)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill() if proc.poll() is None else None
    assert json.loads(answer.read_text()) == FEATURE_BRIEF_ANSWER


@needs_binary
def test_e2e_web_research_brief_covers_the_control_gallery(tmp_path: Path):
    """The Chinese research form is the worked reference for the whole gallery.

    Agents copy from it, so its coverage is a contract rather than a detail:
    every control, the conditional wiring, and the a2ui-ask structures are
    asserted here instead of being trusted to survive the next edit.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            str(PY_SCRIPT),
            "--schema",
            str(WEB_RESEARCH_SCHEMA),
            "--config",
            str(WEB_RESEARCH_DEFAULTS),
            "--title",
            "联网调研任务确认",
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
        by_pointer = {node["pointer"]: node for node in collect_nodes(session["ui_ast"]["roots"])}

        def bounds(pointer: str) -> dict:
            return by_pointer[pointer]["bounds"]

        # every gallery control, and only those fields, carry a hint
        hinted = {pointer: node["control"] for pointer, node in by_pointer.items() if node.get("control")}
        assert hinted == GALLERY_CONTROLS
        for pointer in SHAPE_DEFAULT_FIELDS:
            assert by_pointer[pointer]["control"] is None, pointer
        # `select` is the shape default for an enum, so the long market list
        # must still reach the browser as one
        assert by_pointer["/market"]["kind"]["enum_values"] is not None
        # ... and `x-multiline` marks a string multi-line without naming a control
        assert by_pointer["/background"]["kind"]["multiline"] is True

        # the slider/range variants the gallery separates: a derived step
        # against a declared one, and bare against labelled against unit marks
        assert bounds("/relevance_floor")["step"] is None
        assert bounds("/fetch_timeout_seconds")["step"] == 15.0
        assert bounds("/price_range")["step"] == 10000.0
        assert [mark["label"] for mark in bounds("/depth_level")["marks"]] == [None] * 5
        assert bounds("/source_authority")["marks"][1]["label"] == "均衡"
        assert bounds("/freshness_weight")["marks"][-1]["label"] == "100%"

        # `x-visible-when`: escape hatches gated by `equals` and by `contains`,
        # plus the mode-gated group
        assert by_pointer["/market_custom"]["visible_when"]["value"] == "其他"
        assert by_pointer["/source_types_custom"]["visible_when"]["op"] == "contains"
        assert by_pointer["/track_window"]["visible_when"]["field"] == "run_mode"
        assert by_pointer["/track_sample_percent"]["visible_when"]["field"] == "run_mode"
        assert by_pointer["/topic"]["visible_when"] is None

        # the a2ui-ask conventions: multi-select and record list are both
        # arrays, told apart by their item node
        assert by_pointer["/source_types"]["kind"]["item"]["enum_values"] is not None
        assert by_pointer["/watchlist"]["kind"]["item"]["type"] == "composite"
        assert by_pointer["/delivery"]["kind"]["mode"] == "one_of"
        assert by_pointer["/labels"]["kind"]["type"] == "key_value"

        answer = tmp_path / read_until(proc, "SCHEMAUI_ANSWER=").strip().split("=", 1)[1]
        drive_session(url, WEB_RESEARCH_ANSWER)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill() if proc.poll() is None else None
    assert json.loads(answer.read_text()) == WEB_RESEARCH_ANSWER


@needs_binary
def test_e2e_cjk_title_survives_a_non_utf8_locale(tmp_path: Path):
    """A Chinese form must round-trip where the platform codec is not UTF-8.

    schemaui writes UTF-8 and its first stderr line echoes the form title, so
    decoding that stream with the platform's codec (cp1252 on Windows) used to
    kill ask.py's stderr pump: no URL was announced, no answer was committed,
    exit 5 with nothing on screen. The answer payload echo covers the write
    side, which fails the same way on the way out. LC_ALL=C reproduces both on
    POSIX; Windows reaches them without help.
    """
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "SCHEMAUI_BIN": BINARY or "schemaui",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            str(PY_SCRIPT),
            "--schema",
            str(WEB_RESEARCH_SCHEMA),
            "--config",
            str(WEB_RESEARCH_DEFAULTS),
            "--title",
            "联网调研任务确认",
            "--port",
            "0",
            "--no-open",
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # The script's contract is UTF-8 on both streams; decoding anything
        # else here would hide the very regression this test is about.
        encoding="utf-8",
        errors="replace",
    )
    try:
        url = read_until(proc, "SCHEMAUI_URL=").strip().split("=", 1)[1]
        answer = tmp_path / read_until(proc, "SCHEMAUI_ANSWER=").strip().split("=", 1)[1]
        drive_session(url, WEB_RESEARCH_ANSWER)
        assert proc.wait(timeout=15) == 0
        echoed = proc.stdout.read() if proc.stdout else ""
    finally:
        proc.kill() if proc.poll() is None else None
    assert json.loads(answer.read_text(encoding="utf-8")) == WEB_RESEARCH_ANSWER
    assert "最近三个月发布的新款新能源车" in echoed


@needs_binary
@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_e2e_timeout_kills_session(tmp_path: Path, launcher: list[str]):
    proc = subprocess.Popen(
        [
            *launcher,
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
        stderr=subprocess.PIPE,
        text=True,
    )
    read_until(proc, "SCHEMAUI_URL=")
    assert proc.wait(timeout=15) == ask.EXIT_TIMEOUT
    stderr = proc.stderr.read() if proc.stderr else ""
    assert not list(tmp_path.glob(".schemaui/answers/*.json"))
    # The engine should have ended the session at its own deadline. If the
    # wrapper's backstop had to kill it instead, the user never saw a countdown
    # and the two messages differ -- so assert on which one was printed.
    assert "no answer was committed" in stderr, stderr
    assert "session killed" not in stderr, stderr


@needs_binary
@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_e2e_timeout_is_announced_on_stderr(tmp_path: Path, launcher: list[str]):
    """The deadline must be visible to whoever reads the process, not just the browser."""
    proc = subprocess.Popen(
        [
            *launcher,
            "--schema",
            str(EXAMPLE_SCHEMA),
            "--port",
            "0",
            "--no-open",
            "--timeout",
            "120",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        read_until(proc, "SCHEMAUI_URL=")
        # The engine announces the budget right after the URL. A wrapper that
        # killed the process locally would never produce this line, so its
        # presence is also the proof that the flag was actually forwarded.
        #
        # Drained on a thread rather than with readline(): a blocking read on a
        # quiet pipe would never return, so the deadline below could not fire.
        assert proc.stderr is not None
        seen: list[str] = []
        pump = threading.Thread(target=lambda: seen.extend(proc.stderr), daemon=True)
        pump.start()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if any("closes automatically in" in line for line in seen):
                break
            time.sleep(0.05)

        text = "".join(seen)
        assert "closes automatically in 2m" in text, text
    finally:
        proc.kill() if proc.poll() is None else None


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


# install.sh targets macOS/Linux/FreeBSD; on Windows the supported installer
# is install.ps1 (covered by test_install_ps1_dry_run_and_platform_guard).
no_windows = pytest.mark.skipif(
    sys.platform == "win32", reason="install.sh targets Unix; Windows uses install.ps1"
)


@no_windows
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


@no_windows
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
