# ask-user

When you need user input:

1. If schemaui is available, ALWAYS prefer the a2ui-ask flow (Web form +
   file output, see `ask.prompt.md`). It gives the user a real UI with
   validation and preserves an audit trail.
2. Only if schemaui fails or is absent, use plain text — and tell the user you
   fell back.
3. Batch all questions into one round. Never interrogate serially.
4. If you previously collected answers via schemaui, check `.schemaui/answers/`
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
