# The engine underneath

`scripts/ask.py` and its twins wrap `schemaui web`. They pick the port, open the
browser, enforce the timeout, write the answer file, and map failures to the
exit codes in [SKILL.md](../SKILL.md#exit-codes). Reach for this page only when
the scripts cannot run, or when you need theming or a custom frontend.

## Script contract

```text
ask.py --schema PATH|- [--config PATH] [--title T] [--description D]
       [--topic SLUG] [--output PATH] [--host 0.0.0.0] [--port 8787]
       [--timeout 300] [--open|--no-open] [--stdout-echo] [--force]
       [--theme CSS]
```

Stdout, flushed in this order: `SCHEMAUI_URL=…`, `SCHEMAUI_LAN_URL=…` (only for
wildcard binds), `SCHEMAUI_ANSWER=…`, the answer JSON, then
`SCHEMAUI_RESULT=<path>`. The engine's own messages go to stderr. `SCHEMAUI_BIN`
overrides where the script looks for the engine. A busy port is retried once on
a random free port; a schema the engine rejects is not retried and exits 6.

## Raw CLI

```bash
mkdir -p .schemaui/schemas .schemaui/answers
schemaui web \
  --host 0.0.0.0 --port 8787 \
  --schema .schemaui/schemas/<topic>-<timestamp>.json \
  --config <defaults.json> \
  --title "<question summary>" \
  --timeout 300 \
  --force \
  -o .schemaui/answers/<topic>-<timestamp>.json
```

- **Put `-o` last.** It takes every token after it as a destination; add stdout
  with `-o <file> -` only when the answer is small and your runtime shows tool
  output live.
- **Read stderr for the URL and deadline.** The engine prints
  `<title> schemaui UI available at http://<addr>/`, then
  `Session closes automatically in <budget>` when `--timeout` is set.
- **Port 8787 busy:** stderr says `failed to bind … Address already in use`;
  rerun with `--port 0` and read the URL line.
- **Exit codes:** 0 saved, 4 deadline reached with nothing written, 1 any error,
  including a rejected schema (the message names the field). `--timeout 0` means
  no deadline.
- **Never use `schemaui tui`** from an agent: there is no terminal to draw on.

## Theming

The web UI is built on design tokens, and a plain stylesheet overrides them. No
build step and no `!important` are needed. Pass it with the script's
`--theme PATH` (raw CLI: `--web-theme PATH`); the engine serves it at
`/api/v1/theme.css` on top of its own styles. The script probes the engine
first; a build without `--web-theme` skips the stylesheet with a note instead of
failing.

Tokens worth overriding (the Tailwind v4 `@theme` block in schemaui's
`web/ui/src/styles/globals.css`): `--color-primary`,
`--color-primary-foreground`, `--color-background`, `--color-muted`,
`--color-ring`, `--color-destructive`, `--color-border`, the `--color-chart-*`
set, and the `--radius-*` scale. Override them under `.dark { … }` as well, or
dark mode keeps the default accent. A worked theme to copy:
[`examples/themes/midnight.css`](https://github.com/YuniqueUnic/schemaui/blob/main/examples/themes/midnight.css).

To match a project's design system, map its variables onto these tokens in the
stylesheet, one commented line per mapping (for example the design system's
`--xx-accent` → `--color-primary`).

## Custom frontends

Rarely what was asked; use one only when CSS cannot express the request. The
engine speaks a plain REST contract (`GET /api/v1/session`,
`POST /api/v1/save|exit|validate|preview|render`) and serves any directory with
an `index.html` via `--frontend DIR`. The minimal scaffold is schemaui's
[`examples/frontend/`](https://github.com/YuniqueUnic/schemaui/blob/main/examples/frontend/README.md).
