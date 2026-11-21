# Controls and figures

The control picker in [SKILL.md](../SKILL.md#control-picker) says which control
fits which answer. This page gives the snippet for each, the figure surfaces,
and the examples to copy from. The engine's own reference,
[schemaui `docs/en/control-hints.md`](https://github.com/YuniqueUnic/schemaui/blob/main/docs/en/control-hints.md),
is the authority on hint semantics; read it when this page and the engine
disagree.

Every snippet is one entry under `properties`. Remember the rule from SKILL.md:
a field with a recommended `default` is also listed in its parent's `required`.

## Choices

```jsonc
// 2–4 short labels: segmented buttons
"tier": { "type": "string", "enum": ["S", "M", "L"], "default": "M", "x-control": "segmented" }

// options that need a full line each: radio group
"rollout": {
  "type": "string",
  "enum": ["一次性全量切换", "按 10% → 50% → 100% 灰度", "其他"],
  "default": "按 10% → 50% → 100% 灰度",
  "x-control": "radio"
}

// a long list: leave it a dropdown
"region": { "type": "string", "enum": ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"] }

// several of a set: checkbox list
"platforms": {
  "type": "array",
  "items": { "type": "string", "enum": ["macos", "linux", "windows", "其他"] },
  "uniqueItems": true,
  "default": ["macos", "linux"]
}
```

Multi-select escape hatch: gate `<field>_custom` with
`{"field": "platforms", "op": "contains", "value": "其他"}`.

## Booleans

A boolean renders as a switch. Use `"x-control": "checkbox"` when it reads as
one tick among several ("include tests", "include docs"), and keep the switch
when it flips a mode ("enable cache").

## Numbers

```jsonc
// a value on a scale; the slider reads its track from minimum/maximum
"sample_rate": { "type": "number", "minimum": 0, "maximum": 1, "default": 0.1, "x-control": "slider" }

// named stops under the track
"effort": {
  "type": "integer", "minimum": 0, "maximum": 100, "default": 50, "x-control": "slider",
  "x-slider-marks": [{ "value": 0, "label": "最省" }, { "value": 50, "label": "均衡" }, { "value": 100, "label": "最全" }]
}

// a window with two ends; bounds sit on the array, not on the items
"work_hours": {
  "type": "array", "items": { "type": "integer" },
  "minItems": 2, "maxItems": 2, "minimum": 0, "maximum": 24,
  "default": [9, 18], "x-control": "range"
}
```

`multipleOf` becomes the slider step. Without it, integers step by 1 and a
`number` gets about a hundred stops across its span. Bounds on a plain number
field only show the valid range; they do not turn it into a slider.

## Text, colour, diagrams

```jsonc
"goal": { "type": "string", "x-multiline": true }        // paragraph; same as "x-control": "textarea"
"brand_color": { "type": "string", "default": "#2563eb", "x-control": "color" }
"flow": { "type": "string", "x-control": "mermaid", "default": "flowchart LR\n  A --> B" }
```

Use `mermaid` only when the answer is a diagram, such as a flow for the user to
correct. It is not decoration for a config answer.

## Structure

```jsonc
// a variant with its own settings: the user picks a branch, then fills it in
"storage": {
  "oneOf": [
    { "title": "PostgreSQL", "type": "object", "properties": { "url": { "type": "string" } }, "required": ["url"] },
    { "title": "SQLite", "type": "object", "properties": { "path": { "type": "string", "default": "./app.db" } }, "required": ["path"] }
  ]
}

// a list of records: list view plus a per-entry editor
"endpoints": { "type": "array", "items": { "type": "object", "properties": { "path": { "type": "string" }, "method": { "enum": ["GET", "POST"] } } } }

// free key/value pairs; propertyNames constrains the keys
"labels": { "type": "object", "additionalProperties": { "type": "string" }, "propertyNames": { "pattern": "^[a-z][a-z0-9_]*$" } }
```

## Conditional fields

`x-visible-when` hides a field until a sibling in the same object matches:
`equals` compares the whole value, `contains` tests membership in an array. Use
it for escape hatches and for anything that applies only sometimes
(`has_changes` → `change_notes`, `cache.enabled` → `cache.ttl_seconds`).

Hiding is presentation only. A hidden field keeps any value it already has,
including a pre-filled default, and that value lands in the answer file, so
readers check the gate before using it. Never make a hidden field `required`
without a valid `default`: the user could not see it to fix a validation error.

## Figures

The engine renders three kinds of content, `mermaid`, `svg` (sanitised) and
`markdown` (sanitised), in three places:

1. **On the field**: `"x-content": {"type": "mermaid", "source": "…"}` shows a
   figure above the control. Use it for context a sentence cannot carry, such as
   the request path a timeout applies to.
2. **On each option**: `"x-options"` lines up with `enum` by index. Each entry
   may carry `label`, `description` and `content`; plain options get `{}`.
   Options that mean "none" carry no figure. `radio` shows the figure under the
   label; a dropdown shows it inline. `segmented` cannot show figures.

   ```jsonc
   "topology": {
     "type": "string",
     "enum": ["single", "active-passive", "其他"],
     "default": "active-passive",
     "x-control": "radio",
     "x-options": [
       { "label": "单实例", "content": { "type": "mermaid", "source": "flowchart LR; LB-->A" } },
       { "label": "主备", "description": "故障时切到备节点", "content": { "type": "mermaid", "source": "flowchart LR; LB-->A; A-.->B" } },
       {}
     ]
   }
   ```

3. **As the value**: `"x-control": "mermaid"`, described above.

A figure explains; it is never the value. The answer file still receives the
enum string.

## Examples to copy from

Each schema in [`examples/`](../examples/) has a `.defaults.json` with
recommended answers; run one with
`python3 scripts/ask.py --schema examples/<name>.schema.json --config examples/<name>.defaults.json`.

| Example                               | Shows                                                                                                                              |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `web-research-brief.schema.json`      | the full reference (中文): every control, escape hatches, conditional fields, `oneOf`, records, key/value, figures, mermaid editor |
| `deployment-architecture.schema.json` | an architecture choice where every option carries a diagram (中文)                                                                 |
| `feature-brief.schema.json`           | a 12-question requirements brief with every control type (English)                                                                 |
| `invoice-reimbursement.schema.json`   | escape hatches on every select (中文)                                                                                              |
| `ecommerce-main-image.schema.json`    | sizes, fonts, colours, `oneOf` backgrounds (中文)                                                                                  |
| `seo-diagnosis.schema.json`           | site, issues, keywords, competitors (中文)                                                                                         |
| `env-schema.json`                     | the minimal four-field smoke test                                                                                                  |

schemaui's own galleries put every hint value and figure surface side by side:
[`controls-gallery.schema.json`](https://github.com/YuniqueUnic/schemaui/blob/main/examples/controls-gallery.schema.json)
and
[`rich-content.schema.json`](https://github.com/YuniqueUnic/schemaui/blob/main/examples/rich-content.schema.json).
