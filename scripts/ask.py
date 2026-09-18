#!/usr/bin/env python3
"""Ask the user structured questions through a schemaui Web form.

Built for AI agents, which have no TTY: this script spawns
`schemaui web --host 0.0.0.0`, prints the form URL, optionally opens the
user's browser, blocks until the user clicks "Save & Exit", and leaves the
answer JSON at a stable path under `.schemaui/answers/`.

Stdout contract (each line printed flushed, in order):
  SCHEMAUI_URL=http://127.0.0.1:8787/        URL to open on this machine
  SCHEMAUI_LAN_URL=http://192.168.1.5:8787/  LAN URL (only for wildcard hosts)
  SCHEMAUI_ANSWER=.schemaui/answers/<topic>-<timestamp>.json
  <answer JSON payload>                      echoed once the session finishes,
                                             unless --stdout-echo already made
                                             schemaui print it
  SCHEMAUI_RESULT=<same answer path>         final line on success

Exit codes:
  0  success, answer file written
  2  usage error (argparse)
  3  schemaui binary not found
  4  timed out waiting for the user (no answer committed)
  5  schemaui exited non-zero (bind failure, Ctrl+C abort, ...)
  6  schema/config input problem

`--timeout` is enforced by schemaui itself when the installed build supports it,
so the user sees a live countdown in the form instead of the form going dead
under them. The wrapper keeps only a backstop for an engine that never returns.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

EXIT_OK = 0
EXIT_NO_BINARY = 3
EXIT_TIMEOUT = 4
EXIT_SESSION_FAILED = 5
EXIT_BAD_INPUT = 6

# Exit code schemaui uses when a session's own deadline fires. Deliberately
# distinct from 1 so "nobody answered" is not confused with "the run failed".
ENGINE_EXIT_TIMEOUT = 4

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
DEFAULT_TIMEOUT = 300
# Extra wall-clock time allowed after schemaui's own deadline before the wrapper
# kills it. The engine is expected to exit on its own; this only catches an
# engine that wedges, and it must be comfortably longer than the deadline so a
# normal timeout is never mistaken for a hang.
TIMEOUT_GRACE = 30.0
WILDCARD_HOSTS = {"0.0.0.0", "::"}
URL_PARTS = re.compile(r"^(https?://)(\[[0-9a-fA-F:]+\]|[^:/]+)(:\d+)?(/.*)?$")
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+")


def slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug or "question"


def extract_url(text: str) -> str | None:
    """Pull the first HTTP URL out of a schemaui stderr line."""
    match = URL_IN_TEXT.search(text)
    return match.group(0) if match else None


def _split_url(url: str) -> tuple[str, str, str, str] | None:
    match = URL_PARTS.match(url)
    if not match:
        return None
    scheme, host, port, path = match.groups()
    return scheme, host, port or "", path or "/"


def localize_url(url: str) -> str:
    """Rewrite a wildcard bind address so a local browser can open it."""
    parts = _split_url(url)
    if not parts:
        return url
    scheme, host, port, path = parts
    if host.strip("[]") in WILDCARD_HOSTS:
        host = "127.0.0.1"
    return f"{scheme}{host}{port}{path}"


def detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # TEST-NET-1 (RFC 5737); UDP connect sends no traffic.
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
    except OSError:
        return None


def lan_url(url: str) -> str | None:
    """Swap a wildcard host for this machine's LAN address, if detectable."""
    parts = _split_url(url)
    if not parts:
        return None
    scheme, host, port, path = parts
    if host.strip("[]") not in WILDCARD_HOSTS:
        return None
    lan_ip = detect_lan_ip()
    if not lan_ip:
        return None
    return f"{scheme}{lan_ip}{port}{path}"


def build_paths(topic: str, now: datetime | None = None) -> tuple[Path, Path]:
    """Return (schema_path, answer_path) under .schemaui/ for this question."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = Path(".schemaui")
    name = f"{slugify(topic)}-{stamp}.json"
    return base / "schemas" / name, base / "answers" / name


def find_binary() -> str | None:
    override = os.environ.get("SCHEMAUI_BIN")
    if override:
        if Path(override).is_file():
            return override
        return shutil.which(override)  # allow a bare command name
    return shutil.which("schemaui")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ask",
        description=__doc__.splitlines()[0],
        epilog="Agents: relay SCHEMAUI_URL to the user in chat, then block on "
        "this command. Any non-zero exit means: fall back to plain text.",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="question schema path, or '-' to read draft-07 JSON from stdin "
        "(persisted under .schemaui/schemas/ for the audit trail)",
    )
    parser.add_argument("--config", help="optional defaults file (JSON/YAML/TOML)")
    parser.add_argument("--title", help="title shown at the top of the form")
    parser.add_argument("--description", help="one-line context under the title")
    parser.add_argument(
        "--topic",
        help="slug used to name .schemaui files (default: title or schema name)",
    )
    parser.add_argument(
        "--output",
        help="answer file (default: .schemaui/answers/<topic>-<timestamp>.json)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"bind address (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"bind port, 0 = random free port (default: {DEFAULT_PORT}; "
        "auto-retried as 0 if busy)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for the user, 0 = forever (default: {DEFAULT_TIMEOUT}); "
        "the form counts the remaining time down when schemaui supports it",
    )
    parser.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        default=True,
        help="open the form in the user's browser (default)",
    )
    parser.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_false",
        help="do not open a browser (remote/headless runs; print the URL only)",
    )
    parser.add_argument(
        "--stdout-echo",
        action="store_true",
        help="also pass '-o -' so schemaui echoes the result JSON to stdout",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing answer file"
    )
    return parser.parse_args(argv)


def resolve_schema(spec: str, schema_path: Path) -> Path:
    """Return a real schema file path, persisting stdin schemas first."""
    if spec != "-":
        path = Path(spec)
        if not path.is_file():
            raise FileNotFoundError(f"schema file not found: {spec}")
        return path
    payload = sys.stdin.read()
    json.loads(payload)  # fail fast on invalid JSON
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(payload, encoding="utf-8")
    return schema_path


def supports_native_timeout(binary: str) -> bool:
    """Whether this schemaui build understands `--timeout`.

    Probed rather than assumed: a2ui-ask runs against whatever schemaui happens
    to be on PATH, and passing a flag an older build does not have would turn a
    working setup into a hard failure. The cost is one `--help` per run.
    """
    try:
        proc = subprocess.run(
            [binary, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "--timeout" in (proc.stdout + proc.stderr)


def build_command(
    binary: str,
    args: argparse.Namespace,
    schema: Path,
    answer: Path,
    port: int,
    native_timeout: bool,
) -> list[str]:
    # NOTE: `-o` is greedy (clap `num_args = 1..` + hyphen values): it swallows
    # every following token, including later flags. Every other flag must come
    # before the single trailing `-o`, and extra destinations follow it
    # space-separated (`-o file -`), never as a repeated flag.
    cmd = [
        binary,
        "web",
        "--host",
        args.host,
        "--port",
        str(port),
        "--schema",
        str(schema),
    ]
    if args.config:
        cmd += ["--config", args.config]
    if args.title:
        cmd += ["--title", args.title]
    if args.description:
        cmd += ["--description", args.description]
    # Let the engine own the deadline when it can: it is the only side that can
    # show the user a countdown, and it refuses to write a half-filled answer.
    if args.timeout > 0 and native_timeout:
        cmd += ["--timeout", str(args.timeout)]
    if args.force:
        cmd += ["--force"]
    cmd += ["-o", str(answer)]
    if args.stdout_echo:
        cmd.append("-")
    return cmd


def announce(url: str, answer: Path, open_browser: bool) -> None:
    local = localize_url(url)
    print(f"SCHEMAUI_URL={local}", flush=True)
    lan = lan_url(url)
    if lan:
        print(f"SCHEMAUI_LAN_URL={lan}", flush=True)
    print(f"SCHEMAUI_ANSWER={answer}", flush=True)
    if open_browser:
        opened = webbrowser.open(local)
        note = "opened in your browser" if opened else "could not auto-open a browser"
        print(f"Form ready at {local} ({note}); waiting for Save & Exit...", flush=True)
    else:
        print(f"Form ready at {local}; waiting for Save & Exit...", flush=True)


def run_session(
    cmd: list[str], args: argparse.Namespace, answer: Path, native_timeout: bool
) -> tuple[int, bool]:
    """Spawn schemaui, relay stderr, announce the URL, block until done.

    Returns (exit_code, announced): announced=False means the server never
    came up (e.g. port busy), so retrying on another port is safe.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=None if args.stdout_echo else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    announced = False
    if args.timeout <= 0:
        deadline = None
    elif native_timeout:
        # The engine ends the session at args.timeout on its own; this is only
        # a backstop for an engine that never returns.
        deadline = time.monotonic() + args.timeout + TIMEOUT_GRACE
    else:
        # No engine-side deadline, so the wrapper is the only thing enforcing
        # one.
        deadline = time.monotonic() + args.timeout
    assert proc.stderr is not None

    # Pump stderr on a thread: a blocking readline() would otherwise prevent
    # the deadline check below from ever running once the server goes quiet.
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        for line in proc.stderr:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()

    try:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                proc.kill()
                if native_timeout:
                    print(
                        f"schemaui did not exit within {TIMEOUT_GRACE:.0f}s of "
                        f"its {args.timeout}s deadline; killed. "
                        "Fall back to plain-text questions.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"Timed out after {args.timeout}s waiting for the user; "
                        "session killed. Fall back to plain-text questions.",
                        file=sys.stderr,
                    )
                return EXIT_TIMEOUT, announced
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if line is None:
                break
            sys.stderr.write(line)
            sys.stderr.flush()
            if not announced:
                url = extract_url(line)
                if url:
                    announce(url, answer, args.open_browser)
                    announced = True
        code = proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(signal.SIGINT)
        proc.wait()
        return EXIT_SESSION_FAILED, announced
    if not announced:
        return EXIT_SESSION_FAILED, False
    if code == ENGINE_EXIT_TIMEOUT:
        print(
            f"Timed out after {args.timeout}s waiting for the user; "
            "no answer was committed. Fall back to plain-text questions.",
            file=sys.stderr,
        )
        return EXIT_TIMEOUT, True
    if code != 0:
        print(
            f"schemaui exited with code {code}; no answer was committed. "
            "Fall back to plain-text questions.",
            file=sys.stderr,
        )
        return EXIT_SESSION_FAILED, True
    return EXIT_OK, True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    binary = find_binary()
    if not binary:
        print(
            "schemaui binary not found (set SCHEMAUI_BIN or install schemaui-cli). "
            "Fall back to plain-text questions.",
            file=sys.stderr,
        )
        return EXIT_NO_BINARY

    topic = args.topic or args.title or Path(args.schema).stem
    schema_path, answer_path = build_paths(topic)
    answer = Path(args.output) if args.output else answer_path

    try:
        schema = resolve_schema(args.schema, schema_path)
    except FileNotFoundError as err:
        print(f"{err}. Fall back to plain-text questions.", file=sys.stderr)
        return EXIT_BAD_INPUT
    except (json.JSONDecodeError, OSError) as err:
        print(
            f"invalid schema on stdin: {err}. Fall back to plain-text questions.",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT
    if args.config and not Path(args.config).is_file():
        print(f"config file not found: {args.config}", file=sys.stderr)
        return EXIT_BAD_INPUT

    answer.parent.mkdir(parents=True, exist_ok=True)

    native_timeout = supports_native_timeout(binary)
    if args.timeout > 0 and not native_timeout:
        print(
            f"Note: this schemaui build has no --timeout, so the {args.timeout}s "
            "deadline is enforced by the wrapper and the form shows no countdown. "
            "Upgrade schemaui-cli to 0.13.1+ to see the remaining time.",
            file=sys.stderr,
        )

    code, announced = run_session(
        build_command(binary, args, schema, answer, args.port, native_timeout),
        args,
        answer,
        native_timeout,
    )
    if code == EXIT_SESSION_FAILED and not announced and args.port != 0:
        print(
            f"Port {args.port} unavailable; retrying with a random free port.",
            file=sys.stderr,
        )
        code, _ = run_session(
            build_command(binary, args, schema, answer, 0, native_timeout),
            args,
            answer,
            native_timeout,
        )

    if code == EXIT_OK:
        try:
            payload = answer.read_text(encoding="utf-8")
        except OSError:
            payload = ""
            code = EXIT_SESSION_FAILED
        if not args.stdout_echo and payload:
            print(payload, end="" if payload.endswith("\n") else "\n", flush=True)
        print(f"SCHEMAUI_RESULT={answer}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
