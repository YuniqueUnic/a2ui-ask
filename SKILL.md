---
name: a2ui-ask
description: >
  When the user must choose among options or fill in structured config, spawn
  a browser form (powered by schemaui Web UI, bound to 0.0.0.0), open the
  user's browser, and write the result to .schemaui/answers/. Never use a
  terminal/TUI prompt — the agent process has no TTY attachment. Trigger
  phrases: "give me a form", "ask me via form", "configure", "pick a deploy
  environment", "I need to choose", "a2ui", "给我个表单", "配置一下",
  "用表单问我", "问我几个问题".
---

# a2ui-ask — collect user input via a browser form (file output)

Interactive UI for AI agents: turn structured questions into browser forms. The
rendering engine is the `schemaui` binary (`schemaui web`) from
[YuniqueUnic/schemaui](https://github.com/YuniqueUnic/schemaui); this skill
wraps it with scripts that handle binding, browser wakeup, timeout, and the
file-output contract.

## Prerequisite: the schemaui engine

Check for the binary first: `command -v schemaui` (or just run the ask script —
it exits with code 3 when the engine is missing).

If missing, offer to install it — you can do this yourself, unattended:

```bash
bash scripts/install.sh        # macOS / Linux / FreeBSD: auto-detect & install
pwsh scripts/install.ps1       # Windows / PowerShell 7+
```

Both default to a prebuilt-binary download (no toolchain needed) and support
`--dry-run` / `-DryRun` to preview. Full channel list (brew, scoop, winget,
cargo, manual): see `install.md` in this repository.

## Non-negotiables

1. Web form only, via `schemaui web`. Terminal prompts are forbidden — your
   process has no TTY, so a TUI renders nowhere and blocks forever.
2. Bind `0.0.0.0` so the form is reachable from localhost, LAN, SSH tunnels, and
   port-forwards.
3. Output to a FILE under `.schemaui/answers/` — stdout-only is forbidden.
4. Tell the user the URL and the answer file path in your response, in the same
   turn as the tool call.
5. Block on the subprocess; read the answer file when it exits.
6. Fall back to plain text on any failure — never abort the task.
7. `-o` is greedy: every other flag goes BEFORE `-o`; extra destinations are
   space-separated in the same `-o` (`-o answer.json -`), never repeated.

## Asking well (grill-me discipline, form edition)

- **Explore before asking.** If the codebase, git history, or
  `.schemaui/answers/` can answer the question, answer it yourself. The form is
  for decisions only the user can make.
- **One form per decision cluster.** Batch the questions of one topic (e.g.
  "deployment config") into a single form; do not spawn ten forms for ten
  questions, and do not interrogate serially in chat either.
- **Every question ships a recommended answer.** Put your recommendation in the
  field's `default` so the user can confirm with one click instead of typing.
  Say in chat what you recommended and why.
- **Keep the recommendation out of the option label.** `default` is the one place
  the recommendation lives; the label is what lands in the answer file. Suffixing
  options with `（推荐）` / `(recommended)` duplicates the hint and then leaks it
  into the data, so every downstream consumer has to strip it. Explain the
  recommendation in the field's `description` instead ("推荐 X：因为…"), where it
  stays readable without contaminating the value.
- **Speak the user's language.** Write every `title` and `description` in the
  language the user is chatting in, and say in the description what the answer
  changes downstream ("drives whether we need rate limiting").
- **Always leave an escape hatch, and keep it out of the way.** Your options and
  defaults are guesses, so every select gets an `其他`/`other` option plus a
  sibling `<field>_custom` text input. Gate that input with `x-visible-when` so
  it only shows up once the user actually picks the escape option — a
  permanently visible empty box reads as a question they still owe you an answer
  to:

  ```json
  "delivery_form": { "enum": ["单个 HTML 文件", "其他"], "default": "单个 HTML 文件" },
  "delivery_form_custom": {
    "type": "string",
    "title": "交付形式 · 自定义说明",
    "description": "选了「其他」时填写:你想要的交付形式。",
    "x-visible-when": { "field": "delivery_form", "op": "equals", "value": "其他" }
  }
  ```

  Use `"op": "contains"` when the controlling field is a multi-select (the
  option list has to *contain* the escape value). The rule must name a sibling
  of the same object: a typo is rejected when the form loads rather than hiding
  the field forever. The controlling field's `default` must not be the escape
  value, or the input would be visible from the start.

## Question type → schema cheat sheet

| You need              | Schema shape                                                              | Renders as                       |
| --------------------- | ------------------------------------------------------------------------- | -------------------------------- |
| short text input      | `{"type": "string", "minLength": …, "pattern": …}`                        | inline text field                |
| long text input       | `{"type": "string", "x-multiline": true}`                                 | multi-line text area             |
| number                | `{"type": "integer", "minimum": …, "maximum": …}`                         | numeric field with guards        |
| number on a scale     | `{"type": "…", "minimum": …, "maximum": …, "x-control": "slider"}`        | slider with a live readout       |
| slider with labels    | slider + `"x-slider-marks": [{"value": …, "label": …}, …]`                | slider with labelled stops       |
| two-number interval   | `{"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "minimum": …, "maximum": …, "x-control": "range"}` | two-handle range slider |
| colour                | `{"type": "string", "x-control": "color"}`                                | colour picker, not a text box    |
| few short options     | `{"type": "string", "enum": [...], "x-control": "segmented"}`             | inline segmented control         |
| few verbose options   | `{"type": "string", "enum": [...], "x-control": "radio"}`                 | stacked radio group              |
| yes/no                | `{"type": "boolean"}`                                                     | toggle                           |
| single select         | `{"type": "string", "enum": [...]}`                                       | popup selector                   |
| multi select          | `{"type": "array", "items": {"enum": [...]}, "uniqueItems": true}`        | checkbox list (one per option)   |
| select + escape hatch | `enum: [..., "其他"]` plus a sibling `"<field>_custom"` carrying `x-visible-when` | selector, then a text field once 「其他」 is picked |
| conditional field     | `"x-visible-when": {"field": <sibling>, "op": "equals"\|"contains", "value": …}` | hidden until the sibling matches |
| pick-one-with-config  | `{"oneOf": [{"title": "A", …}, {"title": "B", …}]}`                       | variant chooser + subform        |
| grouped fields        | `{"type": "object", "properties": {…}}`                                   | nested section                   |
| list of records       | `{"type": "array", "items": {"type": "object", "properties": {…}}}`       | list + per-entry overlay         |
| free-form key/value   | `{"type": "object", "additionalProperties": {"type": "string"}}`          | key/value editor                 |

`x-visible-when` is not only for escape hatches: use it whenever a question only
applies conditionally (`has_changes` → `change_notes`, `cache.enabled` →
`cache.ttl_seconds`). `x-multiline` is for anything you would expect the user to
write more than one line into — a goal, a description, a change log.

`x-control` is a *request*, and bounds stay validation keywords: a slider needs
`minimum`/`maximum` on the value, and a hint the engine cannot honour (or does
not know) falls back to that shape's default control rather than failing. Ask
for a control when the default is genuinely worse — a percentage the user
drags, a two-end window, a colour — not for every number on the form.

Slider/range/colour/segmented/radio hints need a newer engine than the two text
hints alone. `schemaui` ≥ 0.14 / `schemaui-cli` ≥ 0.8 draws them; an older
engine ignores unknown `x-` keywords, so the form still runs — it just shows
plain inputs everywhere.

Read `examples/feature-brief.schema.json` (English, every control type) and
`examples/invoice-reimbursement.schema.json` (Chinese, escape hatches on every
select) before generating your own. The engine's own gallery,
[`schemaui/examples/controls-gallery.schema.json`](https://github.com/YuniqueUnic/schemaui/blob/main/examples/controls-gallery.schema.json),
shows every hint value side by side.

## Steps

1. Generate a draft-07 JSON Schema for the question (top-level `type: object`;
   per-field `title` / `description` / `default`; `enum`, `minimum` / `maximum`,
   nested `properties` as needed — see the cheat sheet). A form with an `其他`
   option and no `x-visible-when` on its companion field, or a paragraph-length
   answer squeezed into a one-line input, is an unfinished form.

2. Run the helper script from this skill's directory — it spawns the server,
   prints the URL, opens the user's browser, and writes the answer file. The
   timeout is handed to the engine, which counts it down on screen and ends the
   session itself:

   ```bash
   cat > /tmp/question.json <<'EOF'
   { "...": "your generated schema" }
   EOF
   python3 scripts/ask.py \
     --schema /tmp/question.json \
     --topic <topic> \
     --title "<question summary>" \
     --description "<one-line context>" \
     --timeout 300
   ```

   No Python? Use the twin for your platform — same flags, same stdout contract:
   `bash scripts/ask.sh --schema …` (macOS/Linux) or
   `pwsh scripts/ask.ps1 -Schema …` (Windows / PowerShell 7+).

   Prefer piping the schema straight in (`--schema -`) when you just generated
   it — the script persists it under `.schemaui/schemas/<topic>-<ts>.json` for
   the audit trail.

3. In your response text, relay what the script prints:

   > Form ready at http://localhost:8787 — I'll wait for you to fill it in. Your
   > answers will be saved to `.schemaui/answers/<file>.json`.

   Say how long they have. The form shows a live countdown next to its title and
   turns amber, then red, as the deadline nears — but the user has not seen it
   yet when they read your message, so name the budget (`--timeout 300` → "about
   5 minutes") and note that the form closes itself when it runs out. Raise
   `--timeout` for a long form rather than letting it expire mid-fill: nothing
   is saved on timeout, by design.

   On remote/headless runs pass `--no-open` and relay `SCHEMAUI_LAN_URL` (or the
   forwarded URL) instead of opening a browser locally.

4. The script blocks until the user clicks **Save & Exit**. On exit 0 it prints
   the answer JSON and `SCHEMAUI_RESULT=<path>`. Read the answer file and
   continue the task, citing field paths:

   > Per `.schemaui/answers/deploy-config-20260916-101500.json`:
   > `environment = staging`, `replicas = 3`.

   Honor the escape hatches: when a field's value is `其他`/`other`, the real
   answer is in the sibling `<field>_custom` — use that, not the literal
   "other".

## Exit codes and fallback

| Code | Meaning              | Your action                                                                                 |
| ---- | -------------------- | ------------------------------------------------------------------------------------------- |
| 0    | answer written       | read the file, continue                                                                     |
| 3    | schemaui not found   | offer to run `scripts/install.sh` / `install.ps1`, then retry; else fall back to plain text |
| 4    | timeout (default 5m) | the form showed a countdown and closed itself; nothing was saved. Fall back to plain text, tell the user |
| 5    | cancelled / failed   | fall back to plain text, tell the user                                                      |
| 6    | bad schema/config    | fix the schema or fall back, tell the user                                                  |

Never hard-fail the task because a question could not be asked.

## Raw CLI (when the scripts are unavailable)

```bash
mkdir -p .schemaui/schemas .schemaui/answers
schemaui web \
  --host 0.0.0.0 --port 8787 \
  --schema .schemaui/schemas/<topic>-<timestamp>.json \
  --title "<question summary>" \
  --timeout 300 \
  --force \
  -o .schemaui/answers/<topic>-<timestamp>.json
```

The server announces `<title> schemaui UI available at http://<addr>/` on
stderr, followed by `Session closes automatically in <budget>` when a
`--timeout` was given — that second line is how you learn the deadline without
parsing the UI. Port 8787 busy → retry once with `--port 0` and parse the
`http://…` line from stderr. A session that hits its deadline exits **4** and
writes nothing; drop `--timeout` (or pass `0`) for no deadline at all. Optional
stdout echo: append `-` after the answer path (`-o <file> -`) — only when your
runtime shows tool output live and the JSON is small; default is file-only.

## Sensitive input

Use `--host 127.0.0.1` and tell remote users to tunnel first:
`ssh -L 8787:localhost:8787 <host>`.

## Past answers

Before asking, check `.schemaui/answers/` — the user may have already answered
something similar. Reuse a prior answer as defaults via `--config`.

## Examples

Five runnable forms live in `examples/` (each with a `.defaults.json` carrying
the recommended answers):

| Example                             | Scenario                                                                             |
| ----------------------------------- | ------------------------------------------------------------------------------------ |
| `env-schema.json`                   | minimal 4-field deploy form — first smoke test                                       |
| `feature-brief.schema.json`         | 12-question requirements brief, every control type + both hints (EN)                 |
| `invoice-reimbursement.schema.json` | office: invoice & expense reimbursement (中文, escape hatches)                       |
| `ecommerce-main-image.schema.json`  | design: e-commerce hero image specs — sizes, fonts, colors, oneOf backgrounds (中文) |
| `seo-diagnosis.schema.json`         | SEO triage: site, issues, keywords, competitors (中文)                               |

```bash
python3 scripts/ask.py \
  --schema examples/invoice-reimbursement.schema.json \
  --config examples/invoice-reimbursement.defaults.json \
  --title "发票报销处理"
```
