#!/usr/bin/env bash
# Install the schemaui engine (schemaui-cli) — auto-detecting installer.
#
# Strategy order (auto mode):
#   1. schemaui already on PATH        -> report and exit 0
#   2. prebuilt binary from GitHub releases (fast, no toolchain needed)
#   3. the same asset from the Gitee mirror, when GitHub is unreachable
#   4. cargo binstall schemaui-cli     -> prebuilt via cargo
#   5. cargo install schemaui-cli      -> build from source
#
# Usage:
#   bash install.sh [--dry-run] [--method auto|download|brew|cargo]
#                   [--source auto|github|gitee] [--dir DIR]
#
# Env overrides:
#   SCHEMAUI_INSTALL_DIR   install directory (default: ~/.local/bin)
#   http_proxy/https_proxy honored by curl for the download step.
set -euo pipefail

DRY_RUN=0
METHOD=auto
SOURCE=auto
INSTALL_DIR="${SCHEMAUI_INSTALL_DIR:-$HOME/.local/bin}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --method) METHOD="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,17p' "$0"
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say()  { echo "[a2ui-ask install] $*"; }
fail() { echo "[a2ui-ask install] ERROR: $*" >&2; exit 1; }

case "$SOURCE" in
  auto|github|gitee) ;;
  *) fail "unknown source: $SOURCE (expected auto, github or gitee)" ;;
esac

# --- 0. already installed? -------------------------------------------------
if command -v schemaui >/dev/null 2>&1; then
  say "schemaui is already installed: $(command -v schemaui)"
  exit 0
fi

# --- 1. detect platform ----------------------------------------------------
os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
  Darwin) target_os="apple-darwin" ;;
  Linux)
    if ldd --version 2>&1 | grep -qi musl; then
      target_os="unknown-linux-musl"
    else
      target_os="unknown-linux-gnu"
    fi ;;
  FreeBSD) target_os="unknown-freebsd" ;;
  *) fail "unsupported OS: $os (on Windows use scripts/install.ps1)" ;;
esac
case "$arch" in
  x86_64|amd64) target_arch="x86_64" ;;
  arm64|aarch64) target_arch="aarch64" ;;
  *) fail "unsupported architecture: $arch" ;;
esac
TARGET="${target_arch}-${target_os}"
ASSET="schemaui-${TARGET}.tar.gz"
say "detected platform: $TARGET"

# --- 2. resolve the download URL(s) ----------------------------------------
# The repo publishes both library (schemaui-v*) and CLI (schemaui-cli-v*)
# releases; the prebuilt binaries live on the CLI ones.
#
# GitHub is tried first and the Gitee mirror second, because github.com is
# unreliable from mainland China and gitee.com/Credhat/schemaui mirrors the same
# tags under the same asset names. --source pins a single one instead.
GITHUB_REPO="YuniqueUnic/schemaui"
GITEE_REPO="Credhat/schemaui"

# Newest schemaui-cli tag in a releases feed, chosen by version rather than by
# the order the API returned it: Gitee does not list releases newest-first.
newest_cli_tag() {
  command -v curl >/dev/null 2>&1 || return 1
  curl -fsL --max-time 20 "$1" 2>/dev/null \
    | grep -oE 'schemaui-cli-v[0-9]+\.[0-9]+\.[0-9]+' \
    | sed 's/^schemaui-cli-v//' \
    | sort -t. -k1,1n -k2,2n -k3,3n \
    | tail -1 \
    | sed 's/^/schemaui-cli-v/'
}

github_url() {
  local tag
  tag="$(newest_cli_tag "https://api.github.com/repos/${GITHUB_REPO}/releases?per_page=100")" || true
  if [ -n "$tag" ]; then
    echo "https://github.com/${GITHUB_REPO}/releases/download/${tag}/${ASSET}"
  else
    # GitHub's own shortcut for the newest release; needs no API call.
    echo "https://github.com/${GITHUB_REPO}/releases/latest/download/${ASSET}"
  fi
}

gitee_url() {
  local tag
  tag="$(newest_cli_tag "https://gitee.com/api/v5/repos/${GITEE_REPO}/releases?per_page=100")" || true
  # Gitee has no /releases/latest/download shortcut, so a tag we could not
  # resolve leaves nothing to fall back to.
  [ -n "$tag" ] || return 1
  echo "https://gitee.com/${GITEE_REPO}/releases/download/${tag}/${ASSET}"
}

candidate_urls() {
  case "$SOURCE" in
    github) github_url ;;
    gitee) gitee_url ;;
    auto) github_url; gitee_url || true ;;
  esac
}

URLS="$(candidate_urls || true)"
[ -n "$URLS" ] || fail "could not resolve a download URL for $ASSET (is curl installed?)"
say "asset: $ASSET"
while read -r url; do say "url:   $url"; done <<EOF
$URLS
EOF

if [ "$DRY_RUN" -eq 1 ]; then
  say "dry-run: would install schemaui ($TARGET) into $INSTALL_DIR via method=$METHOD"
  exit 0
fi

# --- 3. install ------------------------------------------------------------
install_download() {
  command -v curl >/dev/null 2>&1 || return 1
  command -v tar  >/dev/null 2>&1 || return 1
  local url tmp bin
  tmp="$(mktemp -d -t a2ui-ask-install.XXXXXX)"
  trap 'rm -rf "$tmp"' RETURN
  # Every candidate is a different host serving the same asset, so the first
  # one that yields a runnable binary wins.
  for url in $URLS; do
    say "downloading prebuilt binary from ${url%%/releases/*}…"
    if curl -fsL --retry 2 --connect-timeout 20 -o "$tmp/$ASSET" "$url" \
      && tar -xzf "$tmp/$ASSET" -C "$tmp"; then
      bin="$(find "$tmp" -name schemaui -type f -not -name '*.tar.gz' | head -1)"
      if [ -n "$bin" ]; then
        mkdir -p "$INSTALL_DIR"
        cp "$bin" "$INSTALL_DIR/schemaui"
        chmod +x "$INSTALL_DIR/schemaui"
        return 0
      fi
    fi
    say "  ${url%%/releases/*} did not work"
  done
  return 1
}

install_brew() {
  command -v brew >/dev/null 2>&1 || return 1
  brew install YuniqueUnic/schemaui/schemaui
}

install_cargo() {
  if command -v cargo-binstall >/dev/null 2>&1; then
    cargo binstall schemaui-cli --no-confirm
  elif command -v cargo >/dev/null 2>&1; then
    cargo install schemaui-cli
  else
    return 1
  fi
}

case "$METHOD" in
  download) install_download || fail "download method failed" ;;
  brew)     install_brew     || fail "brew method failed (is Homebrew installed?)" ;;
  cargo)    install_cargo    || fail "cargo method failed (is Rust installed?)" ;;
  auto)
    install_download || install_brew || install_cargo \
      || fail "all methods failed. See install.md for manual options." ;;
  *) fail "unknown method: $METHOD" ;;
esac

# --- 4. verify -------------------------------------------------------------
if command -v schemaui >/dev/null 2>&1; then
  say "installed: $(command -v schemaui)"
elif [ -x "$INSTALL_DIR/schemaui" ]; then
  say "installed to $INSTALL_DIR/schemaui"
  case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *) say "NOTE: $INSTALL_DIR is not on your PATH — add it, e.g.:"
       say "  export PATH=\"$INSTALL_DIR:\$PATH\"" ;;
  esac
else
  fail "installation finished but schemaui is not runnable"
fi
say "done. Try: schemaui web --schema <schema.json> --port 8787 -o answer.json"
