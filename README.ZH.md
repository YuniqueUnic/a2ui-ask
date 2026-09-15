# a2ui-ask

> **给 AI agent 一个真正的界面 —— 把结构化问题变成浏览器表单。**

当 Claude Code、Codex、Cursor 或任何 agent 需要你选选项、填结构化配置
时，`a2ui-ask` 会弹出一张**真正的浏览器表单**——带校验、带默认值、带多
选——而不是刷屏的纯文本提问。你的答案会落盘成带时间戳的 JSON 文件，你 和 agent
之后都能随时回顾。

[English](./README.md) | [中文文档](./README.ZH.md)

## 为什么需要它

Agent 的工具调用跑在**没有 TTY** 的子进程里——终端提示符根本渲染不出 来，agent
会卡在一个没人看得到的问题上干等。而聊天里喊出来的答案，刷过去 就没了，无法审计。

`a2ui-ask` 两个问题一起解决：

1. **用浏览器表单，不用终端。** Agent 在本地拉起一个 Web UI(以
   [schemaui](https://github.com/YuniqueUnic/schemaui) 为引擎),绑定
   `0.0.0.0`,桌面、手机、SSH 隧道、IDE 端口转发都能访问。
2. **答案写文件，不只打 stdout。** 答案持久化到
   `.schemaui/answers/<主题>-<时间戳>.json`——每个决策都有审计轨迹。

```text
Agent 进程                      你的浏览器 (任何设备)
┌──────────────┐               ┌──────────────────┐
│ 生成 schema  │  1. 拉起      │  桌面 / 手机     │
│              │─────────────► │  (局域网可达)    │
│              │  ask.py       │                  │
│ 2. 在聊天里  │               │  http://<ip>     │
│ 告诉你 URL   │──────────────►│  :8787           │
│              │               │                  │
│              │  3. 你填表    │  实时校验        │
│ 4. 读答案    │◄──────────────│  Save & Exit     │
│   文件       │  JSON 落盘    │                  │
│ 5. 继续干活  │               │                  │
└──────────────┘               └──────────────────┘
```

## 安装

前置条件：`schemaui` 二进制 (表单引擎)。

```bash
cargo binstall schemaui-cli   # 预编译二进制;或 cargo install schemaui-cli
brew install YuniqueUnic/schemaui/schemaui   # macOS/Linux
```

然后三选一安装 skill:

**方式一：一行安装 (推荐，走 [skills.sh](https://skills.sh))**

```bash
npx skills add YuniqueUnic/a2ui-ask
```

**方式二：让 AI 自己装**

对任意 Agent(Claude Code / Codex / Cursor 等) 说一句：

> 请帮我查找并自动安装 https://github.com/YuniqueUnic/a2ui-ask 这个 skill,clone
> 到对应的 skills 目录并接入。

**方式三：手动 clone**

```bash
# 全局(所有项目可用)
git clone https://github.com/YuniqueUnic/a2ui-ask.git ~/.claude/skills/a2ui-ask
# 或按项目安装
git clone https://github.com/YuniqueUnic/a2ui-ask.git .claude/skills/a2ui-ask
```

Codex / zcode 用户：把 [`prompts/ask.prompt.md`](./prompts/ask.prompt.md)
里现成的约定块粘贴到你的 `AGENTS.md`。

## 5 分钟快速上手

在本仓库的 clone 里、且 `schemaui` 已在 PATH 上：

```bash
python3 scripts/ask.py \
  --schema examples/env-schema.json \
  --config examples/env-defaults.json \
  --title "部署配置确认"
```

1. 脚本打印 `SCHEMAUI_URL=http://127.0.0.1:8787/` 并自动打开浏览器。
2. 你在表单里改 (实时校验),点 **Save & Exit**。
3. 答案 JSON 打印到 stdout，同时持久化到 `.schemaui/answers/`。

这就是完整闭环。之后 agent 每次需要做决策都会跑同一条命令——你看到的
是表单，而不是连环追问。

Windows / PowerShell 7+:`pwsh scripts/ask.ps1 -Schema … -Title …`。没有 Python
的 macOS/Linux:`bash scripts/ask.sh --schema …`。

## Agent 从 SKILL.md 学到什么

- **好好提问** —— 先翻代码库再开口;一个决策簇一张表单;每个问题都带推 荐答案 (写进
  `default`);标题和描述用*你的*语言书写。
- **处处留逃生口** —— 每个选择都带「其他」选项 + 自由文本补充字段，你不
  会被迫塞进错误选项。
- **全控件速查表** —— 文本、数值、布尔、单选/多选、oneOf 组合、嵌套对
  象、记录列表、键值映射。

## 示例

[`examples/`](./examples/) 里可直接运行的表单 (每个都带 `.defaults.json`
推荐答案):

| 示例                                                                                | 场景                                              |
| ----------------------------------------------------------------------------------- | ------------------------------------------------- |
| [`env-schema.json`](./examples/env-schema.json)                                     | 最小 4 字段部署表单 —— 首次冒烟测试               |
| [`feature-brief.schema.json`](./examples/feature-brief.schema.json)                 | 11 问需求简报，覆盖全部控件类型 (英文)              |
| [`invoice-reimbursement.schema.json`](./examples/invoice-reimbursement.schema.json) | 办公：发票报销处理 (中文，每个选择带「其他」逃生口)  |
| [`ecommerce-main-image.schema.json`](./examples/ecommerce-main-image.schema.json)   | 设计：电商主图 —— 尺寸、字号、颜色、渐变背景 (中文) |
| [`seo-diagnosis.schema.json`](./examples/seo-diagnosis.schema.json)                 | SEO 排查：站点、问题、关键词、竞品 (中文)           |

## 脚本契约

```text
ask.py --schema PATH|- [--config PATH] [--title T] [--description D]
       [--topic SLUG] [--output PATH] [--host 0.0.0.0] [--port 8787]
       [--timeout 300] [--open|--no-open] [--stdout-echo] [--force]
```

stdout 按序打印 (即时 flush):`SCHEMAUI_URL=…`、`SCHEMAUI_LAN_URL=…`(通
配绑定时)、`SCHEMAUI_ANSWER=…`,随后是答案 JSON，最后是
`SCHEMAUI_RESULT=<路径>`。退出码：`0` 成功 · `2` 用法错误 · `3` 找不到 schemaui ·
`4` 超时 · `5` 取消/失败 · `6` 输入非法——agent 在任何非零退
出时回退纯文本提问。环境变量 `SCHEMAUI_BIN` 可覆盖引擎二进制查找。

## 开发

```bash
# 单测 + e2e(e2e 直接驱动真实 schemaui 的 HTTP API,不需要浏览器)
SCHEMAUI_BIN=$(command -v schemaui) python3 -m pytest tests/
# pwsh 在 PATH 上(或设置 PWSH_BIN)时会自动加跑 PowerShell e2e
```

## 许可证

MIT —— 见 [LICENSE](./LICENSE)。
