#!/usr/bin/env bash
# Ask the user structured questions through a schemaui Web form.
#
# Same contract as ask.py, for environments without Python:
# spawn `schemaui web --host 0.0.0.0`, print the form URL, optionally open the
# user's browser, block until "Save & Exit", answer lands under
# .schemaui/answers/.
#
# Stdout contract:
#   SCHEMAUI_URL=http://127.0.0.1:8787/
#   SCHEMAUI_ANSWER=.schemaui/answers/<topic>-<timestamp>.json
#   <answer JSON payload>                        (unless --stdout-echo)
#   SCHEMAUI_RESULT=<answer path>                (final line on success)
#
# Exit codes: 0 ok | 2 usage | 3 schemaui missing | 4 timeout | 5 session failed | 6 bad input
#
# `--timeout` is handed to schemaui itself when the installed build supports it,
# so the engine can show the user a countdown and refuse to write a half-filled
# answer. Without that flag this script can only kill the process, which ends the
# session just as abruptly but with no warning on screen.
set -euo pipefail

HOST=0.0.0.0
PORT=8787
TIMEOUT=300
OPEN_BROWSER=1
STDOUT_ECHO=0
FORCE=0
THEME=""
SCHEMA=""
CONFIG=""
TITLE=""
DESCRIPTION=""
TOPIC=""
OUTPUT=""

# How long the engine is allowed to overrun its own deadline before this script
# gives up on it. Generous on purpose: a normal timeout must never be mistaken
# for a hang.
TIMEOUT_GRACE=30

usage() {
  cat <<'EOF'
Usage: ask.sh --schema PATH [options]

  --schema PATH       question schema (required)
  --config PATH       optional defaults file (JSON/YAML/TOML)
  --title TEXT        title shown at the top of the form
  --description TEXT  one-line context under the title
  --topic SLUG        slug used to name .schemaui files
  --output PATH       answer file (default: .schemaui/answers/<topic>-<ts>.json)
  --host IP           bind address (default: 0.0.0.0)
  --port N            bind port, 0 = random (default: 8787; retried as 0 if busy)
  --timeout N         seconds to wait, 0 = forever (default: 300). Handed to
                      schemaui when it supports it, so the form shows a countdown
  --no-open           do not open a browser (remote/headless runs)
  --stdout-echo       also pass '-o -' so schemaui echoes the result JSON
  --force             overwrite an existing answer file
  --theme CSS         stylesheet layered over the web UI's design tokens
                      (--color-*/--radius-*), served at /api/v1/theme.css

Agents: relay SCHEMAUI_URL to the user in chat, then block on this command.
Any non-zero exit means: fall back to plain-text questions.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --schema) SCHEMA="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    --topic) TOPIC="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --no-open) OPEN_BROWSER=0; shift ;;
    --stdout-echo) STDOUT_ECHO=1; shift ;;
    --force) FORCE=1; shift ;;
    --theme) THEME="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$SCHEMA" ] || { echo "--schema is required" >&2; exit 2; }
[ -f "$SCHEMA" ] || { echo "schema file not found: $SCHEMA" >&2; exit 6; }
if [ -n "$CONFIG" ] && [ ! -f "$CONFIG" ]; then
  echo "config file not found: $CONFIG" >&2; exit 6
fi

BINARY="${SCHEMAUI_BIN:-schemaui}"
command -v "$BINARY" >/dev/null 2>&1 || {
  echo "schemaui binary not found (set SCHEMAUI_BIN or install schemaui-cli). Fall back to plain-text questions." >&2
  exit 3
}

# Whether this build understands `--timeout`. Probed once, from the help text,
# because passing an unknown flag to clap is a hard error -- guessing wrong would
# turn every run into a failure.
NATIVE_TIMEOUT=0
if [ "$TIMEOUT" -gt 0 ] && "$BINARY" web --help 2>&1 | grep -q -- '--timeout'; then
  NATIVE_TIMEOUT=1
elif [ "$TIMEOUT" -gt 0 ]; then
  echo "Note: this schemaui build has no --timeout, so the ${TIMEOUT}s deadline is enforced by killing the session instead." >&2
fi

WEB_THEME=0
if [ -n "$THEME" ] && "$BINARY" web --help 2>&1 | grep -q -- '--web-theme'; then
  WEB_THEME=1
elif [ -n "$THEME" ]; then
  echo "Note: this schemaui build has no --web-theme, so the stylesheet was not applied. Upgrade schemaui-cli to 0.16+ to theme the form." >&2
fi

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'
}

if [ -z "$TOPIC" ]; then
  if [ -n "$TITLE" ]; then TOPIC="$TITLE"; else TOPIC="$(basename "$SCHEMA" .json)"; fi
fi
SLUG="$(slugify "$TOPIC")"
[ -n "$SLUG" ] || SLUG="question"
STAMP="$(date +%Y%m%d-%H%M%S)"
if [ -z "$OUTPUT" ]; then
  OUTPUT=".schemaui/answers/${SLUG}-${STAMP}.json"
fi
mkdir -p "$(dirname "$OUTPUT")"

localize_url() {
  case "$1" in
    http://0.0.0.0:*) echo "http://127.0.0.1:${1#http://0.0.0.0:}" ;;
    http://\[::\]:*) echo "http://127.0.0.1:${1#http://[::]:}" ;;
    *) echo "$1" ;;
  esac
}

open_browser() {
  [ "$OPEN_BROWSER" -eq 1 ] || return 0
  case "$(uname -s)" in
    Darwin) open "$1" >/dev/null 2>&1 || true ;;
    Linux) xdg-open "$1" >/dev/null 2>&1 || true ;;
    MINGW*|MSYS*|CYGWIN*) cmd.exe /c start "" "$1" >/dev/null 2>&1 || true ;;
  esac
}

child_alive() {
  # kill -0 alone stays true for unreaped zombies; also reject zombies via ps.
  kill -0 "$1" 2>/dev/null && ! ps -p "$1" -o stat= 2>/dev/null | grep -q Z
}

# Return codes from run_session: 0 ok | 4 timeout | 5 session failed after
# announce | 7 server never came up (safe to retry on another port).
run_session() {
  local port="$1" err_log child url local_url fired watchdog code
  err_log="$(mktemp -t a2ui-ask.XXXXXX)"

  # NOTE: `-o` is greedy (clap `num_args = 1..` + hyphen values): it swallows
  # every following token, including later flags. Keep every other flag before
  # the single trailing `-o`, and pass extra destinations space-separated
  # (`-o file -`), never as a repeated flag.
  set -- "$BINARY" web --host "$HOST" --port "$port" --schema "$SCHEMA"
  [ -n "$CONFIG" ] && set -- "$@" --config "$CONFIG"
  [ -n "$TITLE" ] && set -- "$@" --title "$TITLE"
  [ -n "$DESCRIPTION" ] && set -- "$@" --description "$DESCRIPTION"
  # Let the engine own the deadline when it can: it is the only side that can
  # show the user a countdown, and it refuses to write a half-filled answer.
  [ "$TIMEOUT" -gt 0 ] && [ "$NATIVE_TIMEOUT" -eq 1 ] && set -- "$@" --timeout "$TIMEOUT"
  [ "$FORCE" -eq 1 ] && set -- "$@" --force
  [ -n "$THEME" ] && [ "$WEB_THEME" -eq 1 ] && set -- "$@" --web-theme "$THEME"
  set -- "$@" -o "$OUTPUT"
  [ "$STDOUT_ECHO" -eq 1 ] && set -- "$@" -

  # stderr goes through `tee`: the log file is what this script greps for the
  # URL, and the copy on fd 2 is what makes the engine's announcements visible
  # *while* the user is filling the form -- the deadline is useless if the
  # operator only learns it after the session has already ended.
  if [ "$STDOUT_ECHO" -eq 1 ]; then
    "$@" 2> >(tee "$err_log" >&2) &
  else
    "$@" >/dev/null 2> >(tee "$err_log" >&2) &
  fi
  child=$!

  # Wait for the "available at http://..." line (or an early exit).
  url=""
  for _ in $(seq 1 100); do
    url="$(grep -oE 'https?://[^ "]+' "$err_log" 2>/dev/null | head -1 || true)"
    [ -n "$url" ] && break
    child_alive "$child" || break
    sleep 0.1
  done

  if [ -z "$url" ]; then
    wait "$child" 2>/dev/null || true
    rm -f "$err_log"
    return 7
  fi

  local_url="$(localize_url "$url")"
  echo "SCHEMAUI_URL=$local_url"
  echo "SCHEMAUI_ANSWER=$OUTPUT"
  open_browser "$local_url"
  echo "Form ready at $local_url; waiting for Save & Exit..."

  fired=""
  watchdog=""
  if [ "$TIMEOUT" -gt 0 ]; then
    fired="$(mktemp -t a2ui-ask-timeout.XXXXXX)"
    rm -f "$fired"
    # With engine-side support this is only a backstop for a build that never
    # returns, so it waits out the deadline plus a grace period rather than
    # racing the engine to it.
    local grace=0
    [ "$NATIVE_TIMEOUT" -eq 1 ] && grace=$TIMEOUT_GRACE
    ( sleep $((TIMEOUT + grace)); kill -TERM "$child" 2>/dev/null && touch "$fired" ) &
    watchdog=$!
  fi

  code=0
  wait "$child" || code=$?
  if [ -n "$watchdog" ]; then
    kill "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
  fi
  rm -f "$err_log"

  if [ -n "$fired" ] && [ -f "$fired" ]; then
    rm -f "$fired"
    if [ "$NATIVE_TIMEOUT" -eq 1 ]; then
      echo "schemaui did not exit within ${TIMEOUT_GRACE}s of its ${TIMEOUT}s deadline; killed. Fall back to plain-text questions." >&2
    else
      echo "Timed out after ${TIMEOUT}s waiting for the user; session killed. Fall back to plain-text questions." >&2
    fi
    return 4
  fi
  [ -n "$fired" ] && rm -f "$fired"
  if [ "$code" -eq 0 ]; then
    return 0
  fi
  # 4 is the engine's own "deadline passed" code, and it means no output was
  # written -- the same outcome this script reports as 4.
  if [ "$NATIVE_TIMEOUT" -eq 1 ] && [ "$code" -eq 4 ]; then
    echo "Timed out after ${TIMEOUT}s waiting for the user; no answer was committed. Fall back to plain-text questions." >&2
    return 4
  fi
  echo "schemaui exited with code $code; no answer was committed. Fall back to plain-text questions." >&2
  return 5
}

code=0
run_session "$PORT" || code=$?
if [ "$code" -eq 7 ] && [ "$PORT" -ne 0 ]; then
  echo "Port $PORT unavailable; retrying with a random free port." >&2
  code=0
  run_session 0 || code=$?
fi
[ "$code" -eq 7 ] && code=5

if [ "$code" -eq 0 ]; then
  [ -f "$OUTPUT" ] || { echo "answer file missing: $OUTPUT" >&2; exit 5; }
  [ "$STDOUT_ECHO" -eq 1 ] || cat "$OUTPUT"
  echo "SCHEMAUI_RESULT=$OUTPUT"
fi
exit "$code"
