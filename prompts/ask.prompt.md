# a2ui-ask

When you need the user to choose among options or fill in structured config, do
NOT ask in plain text. Spawn a schemaui Web form and write the result to a file.

## Critical constraints

- NEVER use TUI mode. Your process is not attached to the user's terminal; a TUI
  renders nowhere and blocks forever.
- ALWAYS use Web mode with `--host 0.0.0.0` so the form is reachable from
  localhost, LAN, SSH tunnels, and port-forwards.
- ALWAYS write output to a FILE under `.schemaui/answers/`, not just stdout.
  Files are reviewable by you and the user later.
- ALWAYS tell the user the URL and the answer file path in your response text,
  BEFORE or IN THE SAME TURN as the tool call.
- `-o` is greedy: it swallows every following token. Put every other flag BEFORE
  `-o`, and pass extra destinations space-separated in the same `-o`
  (`-o answer.json -`). Never repeat `-o`.

## Ask well (grill-me discipline, form edition)

- If the codebase, git history, or `.schemaui/answers/` can answer the question,
  answer it yourself — the form is for decisions only the user can make.
- Batch one decision cluster per form; never spawn ten forms for ten questions,
  and never interrogate serially in chat.
- Put your recommended answer in each field's `default` so the user confirms
  with one click; say what you recommended and why in chat.
- Question-type cheat sheet (single/multi select, oneOf composition, key/value
  maps, …): see `SKILL.md` and the 11-question showcase
  `examples/feature-brief.schema.json`.

## Preferred path: the helper script

This skill ships `scripts/ask.py` (plus `ask.sh` and `ask.ps1` twins for
shell-only and Windows/PowerShell environments) which handles binding,
browser wakeup, URL printing, timeout, and the file contract for you:

```bash
python3 scripts/ask.py \
  --schema .schemaui/schemas/<topic>-<timestamp>.json \
  --config .schemaui/schemas/<topic>-defaults.json \
  --title "<short question summary>" \
  --description "<one-line context>" \
  --timeout 300
```

The script prints `SCHEMAUI_URL=…`, `SCHEMAUI_LAN_URL=…` (wildcard binds), and
`SCHEMAUI_ANSWER=…` on stdout, opens the user's browser (pass `--no-open` on
remote/headless runs), blocks until Save & Exit, then prints the answer JSON.
Exit codes: `0` ok · `3` schemaui missing · `4` timeout · `5` cancelled/failed ·
`6` bad input. Any non-zero exit → fall back to plain text and say so.

You can also pipe the schema in instead of writing it first; the script persists
it under `.schemaui/schemas/` for the audit trail:

```bash
cat schema.json | python3 scripts/ask.py \
  --schema - --topic deploy-config --title "Deployment Config"
```

## Manual path: raw CLI

1. Generate a draft-07 JSON Schema for your question:
   - top-level `type: object`
   - each field: `title`, `description`, `default`
   - enums via `"enum": [...]`, numeric bounds via `minimum` / `maximum`
   - nesting via nested `properties`

2. Save both schema and answer under a shared `<topic>-<YYYYMMDD-HHMMSS>` name:

   ```bash
   mkdir -p .schemaui/schemas .schemaui/answers
   # .schemaui/schemas/deploy-config-20260916-101500.json
   # .schemaui/answers/deploy-config-20260916-101500.json
   ```

3. Decide whether to add stdout echo (add `-` as a second `-o` destination):
   - add it if your runtime shows tool output to the user in real time AND the
     JSON is small (< 50 lines)
   - skip it if output is buffered, the JSON is large, or you are in a pipeline
   - default when unsure: file-only (safer)

4. Tell the user in your response text: "I've prepared a form at
   http://\<host\>:8787 — please open it in your browser. I'll wait. Your
   answers will be saved to `.schemaui/answers/<file>.json`." Use `localhost`
   when you run on the user's machine, otherwise your LAN IP or hostname.

5. Run the blocking command (all flags before `-o`):

   ```bash
   schemaui web \
     --host 0.0.0.0 --port 8787 \
     --schema .schemaui/schemas/<topic>-<timestamp>.json \
     --config .schemaui/schemas/<topic>-defaults.json \
     --title "<short question summary>" \
     --description "<one-line context>" \
     --force \
     -o .schemaui/answers/<topic>-<timestamp>.json
   ```

   Optional stdout echo: append `-` after the answer path
   (`-o .schemaui/answers/<file>.json -`).

   The server announces `<title> schemaui UI available at http://<addr>/` on
   stderr. If port 8787 is busy the command fails fast; retry once with
   `--port 0`, parse the `http://…` line from stderr, and relay that URL.

6. On exit 0, read the answer file and continue the original task, citing field
   paths: "Per your selection
   (`.schemaui/answers/deploy-config-20260916-101500.json`):
   `runtime.port = 8080`".

7. Do NOT delete schema or answer files — they are the audit trail. Add
   `.schemaui/` to `.gitignore` unless answers should be committed.

## Timeout

Cap the wait at 5 minutes when your runtime allows it. On timeout: kill the
process, fall back to text questions, tell the user.

## Fallback (never hard-fail)

Switch to plain-text questioning AND tell the user you fell back when any of
these happen: schemaui binary not found, schema validation fails, non-zero exit
/ user cancelled, timeout.

## Sensitive input

For secrets (tokens, passwords) use `--host 127.0.0.1` instead, and tell remote
users to tunnel first: `ssh -L 8787:localhost:8787 <host>`.

## Past answers

Before asking, check `.schemaui/answers/` — the user may have already answered
something similar. Reuse a prior answer as defaults via `--config`.
