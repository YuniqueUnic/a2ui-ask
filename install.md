# Installing the schemaui engine

`a2ui-ask` renders forms through the `schemaui` binary (from
[`schemaui-cli`](https://github.com/YuniqueUnic/schemaui)). Everything below
ends with a working `schemaui` on your `PATH` — pick whichever channel fits.

## Fastest: the auto-installer (recommended for agents)

These scripts detect your OS/architecture, resolve the latest `schemaui-cli`
release, download the prebuilt binary, and verify the result. An agent can run
them unattended the moment it hits exit code 3 (`schemaui not found`):

```bash
# macOS / Linux / FreeBSD
bash scripts/install.sh

# Windows (PowerShell 7+)
pwsh scripts/install.ps1
```

Both support a dry run that prints the detected platform, asset name, and
download URL without touching the system:

```bash
bash scripts/install.sh --dry-run
pwsh scripts/install.ps1 -DryRun
```

Options: `--method auto|download|brew|cargo` (sh) /
`-Method auto|download|scoop|cargo` (ps1), `--source auto|github|gitee` /
`-Source auto|github|gitee`, `--dir DIR` / `-Dir DIR` to change the install
location (default `~/.local/bin` / `%LOCALAPPDATA%\Programs\schemaui\bin`).

### Where the binary comes from

GitHub first, then the [Gitee mirror](https://gitee.com/Credhat/schemaui). The
mirror carries the same tags and the same release asset names, and the schemaui
repo's `cd.yml` mirrors every new release into it, so the two stay equivalent.
That fallback is what makes the installer usable from mainland China, where
github.com is unreliable:

```bash
bash scripts/install.sh                  # GitHub, then the mirror (default)
bash scripts/install.sh --source gitee   # skip GitHub entirely
bash scripts/install.sh --source github  # no mirror
pwsh scripts/install.ps1 -Source gitee
```

Only the prebuilt-download path has a mirror. The brew, scoop and winget
manifests hardcode GitHub download URLs of their own, so on a blocked network
prefer `--source gitee` or `cargo install schemaui-cli`.

## Package managers

```bash
# Homebrew (macOS / Linux)
brew install YuniqueUnic/schemaui/schemaui

# Scoop (Windows)
scoop install https://raw.githubusercontent.com/YuniqueUnic/schemaui/main/packaging/scoop/schemaui-cli.json

# winget (Windows, from the repo's manifests)
winget install --manifest <clone>/packaging/winget
```

All three resolve their download URLs against github.com, so they need it to be
reachable. When it is not, use the auto-installer with `--source gitee` instead.

## Cargo

```bash
cargo binstall schemaui-cli   # prebuilt binary, fast
cargo install schemaui-cli    # build from source
```

## Direct download

Grab the archive for your platform from the
[latest schemaui-cli release](https://github.com/YuniqueUnic/schemaui/releases)
(assets are named `schemaui-<target-triple>.tar.gz`, Windows also `.zip`). The
same file is on the mirror at
[gitee.com/Credhat/schemaui](https://gitee.com/Credhat/schemaui/releases) under
the same tag and name — swap the host and keep the path:

```
https://github.com/YuniqueUnic/schemaui/releases/download/<tag>/<asset>
https://gitee.com/Credhat/schemaui/releases/download/<tag>/<asset>
```

| Platform            | Asset                                                    |
| ------------------- | -------------------------------------------------------- |
| macOS Apple Silicon | `schemaui-aarch64-apple-darwin.tar.gz`                   |
| macOS Intel         | `schemaui-x86_64-apple-darwin.tar.gz`                    |
| Linux x64           | `schemaui-x86_64-unknown-linux-gnu.tar.gz` (or `-musl`)  |
| Linux ARM64         | `schemaui-aarch64-unknown-linux-gnu.tar.gz` (or `-musl`) |
| Windows x64         | `schemaui-x86_64-pc-windows-msvc.zip`                    |
| Windows ARM64       | `schemaui-aarch64-pc-windows-msvc.zip`                   |
| FreeBSD x64         | `schemaui-x86_64-unknown-freebsd.tar.gz`                 |

Extract, place `schemaui` / `schemaui.exe` on your `PATH`, done.

## Verify

```bash
schemaui --help
# smoke test a form:
schemaui web --schema examples/env-schema.json --port 8787 -o answer.json
```

## Notes for agents

- `scripts/ask.py` (and the sh/ps1 twins) exit with code **3** when the binary
  is missing. Offer to run the auto-installer, then retry the form.
- If an install stalls or fails, do not just retry it: re-run with the mirror
  pinned (`--source gitee` / `-Source gitee`). An unreachable github.com is the
  likeliest cause and the mirror is the fix.
- If the binary lives somewhere unusual, point the scripts at it with
  `SCHEMAUI_BIN=/path/to/schemaui`.
- The scripts only need the `web` subcommand, but the `x-visible-when` and
  `x-multiline` hints the skill relies on need `schemaui-cli` **≥ 0.7.7**
  (`schemaui` ≥ 0.13.0). Older engines ignore unknown `x-` keywords: the form
  still runs, it just shows every field and single-line inputs. If a form looks
  unstyled that way, the engine is the thing to upgrade.
