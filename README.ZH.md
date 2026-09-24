# a2ui-ask

> **给 AI agent 一个真正的界面 —— 把结构化问题变成浏览器表单。**

当 Claude Code、Codex、Cursor 或任何 agent 需要你选选项、填结构化配置
时，`a2ui-ask` 会弹出一张**真正的浏览器表单**——带校验、带默认值、带多
选——而不是刷屏的纯文本提问。你的答案会落盘成带时间戳的 JSON 文件，你 和 agent
之后都能随时回顾。

[English](./README.md) | [中文文档](./README.ZH.md)

![a2ui-ask form UI — schema navigation, form editor, and live JSON preview](./docs/web-ui.png)

引擎能画的所有控件——滑块、带刻度的范围滑块、分段控件、单选组、开关、
自定义取色器、条件字段——全部由 schema 提示驱动，skill 也会明确要求 agent 主动
用起来。图形走同一套提示：问题和选项都可以带 **Mermaid 图、内联 SVG 或 Markdown
说明**（`x-content` / `x-options`），答案本身也可以是一张可编辑的
实时预览图（`x-control: "mermaid"`）。完整清单见
[`schemaui` 控件画廊](https://github.com/YuniqueUnic/schemaui/blob/main/examples/controls-gallery.schema.json)
与
[富内容画廊](https://github.com/YuniqueUnic/schemaui/blob/main/examples/rich-content.schema.json)；
[`examples/web-research-brief.schema.json`](./examples/web-research-brief.schema.json)
是把这些控件全部用上的一份中文范例。

<table>
  <tr>
    <td><img src="./docs/controls-gallery.png" alt="控件画廊：滑块、范围、分段、单选、取色器等全部控件" /></td>
  </tr>
  <tr>
    <td><img src="./docs/rich-options.png" alt="选项配图：每个部署拓扑选项自带一张 Mermaid 图" /></td>
  </tr>
  <tr>
    <td><img src="./docs/mermaid-editor.png" alt="Mermaid 编辑器：左侧源码、右侧实时预览" /></td>
  </tr>
</table>

## 为什么需要它

Agent 的工具调用跑在**没有 TTY** 的子进程里——终端提示符根本渲染不出 来，agent
会卡在一个没人看得到的问题上干等。而聊天里喊出来的答案，刷过去
就没了，无法审计。

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

前置条件：`schemaui` 二进制（表单引擎，
[YuniqueUnic/schemaui](https://github.com/YuniqueUnic/schemaui))。自动安装脚
本会检测平台并下载预编译二进制：

```bash
bash scripts/install.sh      # macOS / Linux / FreeBSD
pwsh scripts/install.ps1     # Windows / PowerShell 7+
```

脚本优先从 GitHub 下载，**在国内访问不了 github.com 时自动回退到
[Gitee 镜像](https://gitee.com/Credhat/schemaui)**（tag 与文件名跟 GitHub 保持一
致）。也可以用 `--source github|gitee`（sh）/ `-Source github|gitee`（ps1）强制
指定来源：

```bash
bash scripts/install.sh --source gitee
```

其它渠道（brew、scoop、winget、cargo、手动下载）见
[`install.md`](./install.md)。注意 brew / scoop / winget 的清单里写死了 GitHub
下载地址，国内访问不了时请改用上面的 `--source gitee`，或 `cargo install`。

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

- **好好提问** —— 先翻代码库再开口;一个决策簇一张表单;每个问题都带推 荐答案
  (写进 `default`);标题和描述用*你的*语言书写。
- **处处留逃生口** —— 每个选择都带「其他」选项 + 自由文本补充字段，你不
  会被迫塞进错误选项;补充框只在你真的选了「其他」之后才出现，长段回答给
  的是多行输入框而不是单行。
- **给每个答案配对的控件** —— 滑块、带刻度的滑块、双柄范围、取色器、分段控件、
  单选组、复选框、条件字段，外加文本、数值、单选/多选、oneOf 组合、嵌套对
  象、记录列表、键值映射。
- **能看图就别读字** —— 选项差在「形状」上时（拓扑、发布策略、数据模型）， agent
  给每个选项配一张图，你认图选择;节点级 `x-content` 用图或一段富文本
  解释字段背景;`mermaid` 控件让答案本身就是一张可编辑、实时预览的图。
- **访谈纪律内置** —— 开放式设计需要深度访谈时，skill 优先使用你已安装的
  grilling 类 skill，都没有时回退到内置的
  [`skills/grill-with-docs`](./skills/grill-with-docs/SKILL.md)：一次一问、
  每问带推荐答案、每个问题都以项目文档为依据。

- **主题随项目走** —— 一个纯 CSS 文件覆盖 Web UI 的设计 token
  （`--color-*`、`--radius-*`，亮暗两套），用 `--theme` 传入，引擎在
  `/api/v1/theme.css` 分层提供服务;外部设计系统按「一条注释一条映射」 翻译成
  schemaui 的 token。要彻底自定义前端时，可用 `--frontend` 托管 自己的
  `index.html`，对接纯 REST 契约。 grilling 类 skill，都没有时回退到内置的
  [`skills/grill-with-docs`](./skills/grill-with-docs/SKILL.md)：一次一问、
  每问带推荐答案、每个问题都以项目文档为依据。

## 示例

[`examples/`](./examples/) 里可直接运行的表单 (每个都带 `.defaults.json`
推荐答案):

| 示例                                                                                    | 场景                                                |
| --------------------------------------------------------------------------------------- | --------------------------------------------------- |
| [`env-schema.json`](./examples/env-schema.json)                                         | 最小 4 字段部署表单 —— 首次冒烟测试                 |
| [`web-research-brief.schema.json`](./examples/web-research-brief.schema.json)           | 调研：联网调研任务确认 —— 用上画廊全部控件 (中文)   |
| [`feature-brief.schema.json`](./examples/feature-brief.schema.json)                     | 12 问需求简报，覆盖全部控件类型 (英文)              |
| [`invoice-reimbursement.schema.json`](./examples/invoice-reimbursement.schema.json)     | 办公：发票报销处理 (中文，每个选择带「其他」逃生口) |
| [`ecommerce-main-image.schema.json`](./examples/ecommerce-main-image.schema.json)       | 设计：电商主图 —— 尺寸、字号、颜色、渐变背景 (中文) |
| [`seo-diagnosis.schema.json`](./examples/seo-diagnosis.schema.json)                     | SEO 排查：站点、问题、关键词、竞品 (中文)           |
| [`deployment-architecture.schema.json`](./examples/deployment-architecture.schema.json) | 架构选型：每个选项自带一张图 (中文，图形界面参考例) |

## 脚本契约

```text
ask.py --schema PATH|- [--config PATH] [--title T] [--description D]
       [--topic SLUG] [--output PATH] [--host 0.0.0.0] [--port 8787]
       [--timeout 300] [--open|--no-open] [--stdout-echo] [--force]
```

stdout 按序打印 (即时 flush):`SCHEMAUI_URL=…`、`SCHEMAUI_LAN_URL=…`(通
配绑定时)、`SCHEMAUI_ANSWER=…`,随后是答案 JSON，最后是
`SCHEMAUI_RESULT=<路径>`。退出码：`0` 成功 · `2` 用法错误 · `3` 找不到 schemaui
· `4` 超时 · `5` 取消/失败 · `6` 输入非法——agent 在任何非零退
出时回退纯文本提问。环境变量 `SCHEMAUI_BIN` 可覆盖引擎二进制查找。

## 开发

```bash
# 单测 + e2e(e2e 直接驱动真实 schemaui 的 HTTP API,不需要浏览器)
SCHEMAUI_BIN=$(command -v schemaui) python3 -m pytest tests/
# pwsh 在 PATH 上(或设置 PWSH_BIN)时会自动加跑 PowerShell e2e
```

## 链接

- [linux.do](https://linux.do)

## 许可证

MIT —— 见 [LICENSE](./LICENSE)。
