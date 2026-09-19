# ask-user

When you need user input:

1. If schemaui is available, ALWAYS prefer the a2ui-ask flow (Web form + file
   output, see `ask.prompt.md`). It gives the user a real UI with validation and
   preserves an audit trail.
2. In that form, give each answer the control it deserves instead of a plain
   text box — slider, two-handle range, colour picker, segmented control, radio
   group, checkbox, `x-visible-when` for anything conditional. The worked
   reference covering every control is
   `examples/web-research-brief.schema.json`; `SKILL.md` says when each fits.
3. If schemaui is absent, install it before giving up — `scripts/install.sh` /
   `install.ps1` run unattended and need no toolchain, and `--source gitee` /
   `-Source gitee` pulls from the Gitee mirror when github.com is unreachable
   (the common case in mainland China). Only if that fails too, use plain text —
   and tell the user you fell back.
4. Batch all questions into one round. Never interrogate serially.
5. If you previously collected answers via schemaui, check `.schemaui/answers/`
   before asking again — the user may have already answered this. Reuse prior
   answers as defaults.

Plain-text format when schemaui is unavailable:

```text
Please answer the following (reply as JSON):
1. Target environment (dev/staging/prod):
2. Replica count (1-10):
3. Enable TLS (true/false):
```

Example reply:

```json
{ "environment": "staging", "replicas": 3, "enable_tls": true }
```

After receiving the reply, save it to
`.schemaui/answers/<topic>-manual-<YYYYMMDD-HHMMSS>.json` so manual answers
share the same audit trail as form answers.
