# a2ui-ask

Paste this block into `AGENTS.md` (Codex, zcode) or any agent that does not load
skills. The full guide is `SKILL.md` in the a2ui-ask checkout
(https://github.com/YuniqueUnic/a2ui-ask/blob/main/SKILL.md); read it before the
first form.

When the user must pick among options or fill in structured config, ask through
a browser form, not chat:

1. Write a draft-07 JSON Schema. Give every question a recommended `default`
   **and** list it in the parent's `required`, or the form will not pre-fill it.
   Explain the recommendation in `description`, never in option labels. Write in
   the user's language. Add `其他`/`other` to every enum with an optional
   `<field>_custom` text field gated by `x-visible-when`. Use the richer
   controls (`x-control`: `segmented`, `radio`, `slider`, `range`, `color`,
   `checkbox`, `mermaid`; `x-multiline`; figures via `x-content` and
   `x-options`) as `SKILL.md` describes.
2. Run
   `python3 <a2ui-ask>/scripts/ask.py --schema - --topic <slug> --title "…" --timeout 600`
   with the schema on stdin (`ask.sh` / `ask.ps1` take the same flags). Never
   use a terminal prompt: you have no TTY.
3. In the same message, tell the user the printed `SCHEMAUI_URL`, the time
   budget, and that answers go to `.schemaui/answers/`.
4. Block until the script exits. Exit 0: read the answer file it names. Exit 6:
   fix the schema from the error and rerun. Exit 3: offer
   `bash <a2ui-ask>/scripts/install.sh` (`--source gitee` behind a blocked
   github.com). Other exits: ask the same questions in one plain-text message,
   take a JSON reply, and save it to
   `.schemaui/answers/<topic>-manual-<YYYYMMDD-HHMMSS>.json`.
5. Before asking, check the code and `.schemaui/answers/`; pass a relevant past
   answer as `--config`.
