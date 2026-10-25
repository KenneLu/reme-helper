# 把 Agent 接到 ReMe（给 AI 的接入规格）

> **怎么用这份文档**：在 reme-helper 里点「复制接入文档」，把复制到的**全文粘贴给一个能读写本机文件的 AI Agent**，
> 它会**先探测本机环境、报告"哪几端适用"**，你确认后再逐端接入、逐端验收。也可以在 reme-helper 里点「阅读接入文档」先看一遍。
> 你只装了 Codex 就只做 Codex；没有第二台 Linux 机器就不做跨机那两端 —— **不要为了凑齐清单去装东西**。
> 文中 `<...>` 是占位符，执行前替换成本机真实值（见下方变量表；ReMe 端口与 workspace 在复制时已自动填好）。
> 标着**不变量**的句子是踩坑换来的，照做；其余实现细节可以因地制宜，但不要另起一套方案。

本文只讲「把客户端接入 ReMe」这一件事，与具体 skill 或第三方工具无关。

---

## 0. 变量表

| 占位符 | 含义 | 取值来源 |
|---|---|---|
| `<REME_PORT>` | ReMe 在本机的 HTTP 服务端口 | reme-helper 配置，默认 `2333` |
| `<REME_WORKSPACE>` | ReMe 记忆目录（含 `daily/ digest/ session/`） | reme-helper 里 ReMe 目录下的 `workspace` |
| `<CODEX_HOME>` | Codex 主目录 | Windows 默认 `%USERPROFILE%\.codex`，Linux 默认 `~/.codex` |
| `<CLAUDE_HOME>` | Claude Code 主目录 | Windows 默认 `%USERPROFILE%\.claude`，Linux 默认 `~/.claude` |
| `<ZCODE_HOME>` | ZCode 主目录（原生 CLI 那份，装了才用） | Windows 默认 `%USERPROFILE%\.zcode`，Linux 默认 `~/.zcode` |
| `<DSH_HOME>` `<DSH_PROFILE>` | DSH 主目录与 profile（装了 DSH 才用） | Windows 默认 `%USERPROFILE%\.dsh`，Web 界面用 `web` |
| `<SRC_DIR>` | 临时源码目录（DSH 源码构建用） | 自选 |
| `<VM_HOST>` `<VM_USER>` | 第二台 Linux 机器的地址与用户名（没有就跳过） | 你的环境 |
| `<REMOTE_PORT>` | Linux 机器侧的隧道端口 | reme-helper 的 VM 目标设置，例如 `22333` |

**前置条件按你要的能力定，不必全部满足**：

| 想要的能力 | 需要的前提 |
|---|---|
| 记忆召回（关键词、文件级检索） | ReMe 在跑即可，**不需要任何模型** |
| 语义召回（近义、改写、中英混搜） | 额外需要 embedding；不配则退化成关键词检索，会漏 |
| 每轮自动记录 | **需要 LLM** —— 提炼记忆是模型干的活；没配 LLM 时不要接自动记录 |
| 记忆整理（daily→digest） | 需要 LLM，且只由 reme-helper 启动的那一份 ReMe 做 |

无论哪一档，都先用 `POST http://127.0.0.1:<REME_PORT>/health_check` 确认 `healthy: true`。
ReMe **只监听回环地址、不使用 API Key** —— 这两点决定了「跨机器必须走隧道」，也决定了「所有客户端指向同一个 workspace」。

---

## 1. 第一步：探测，不要先动手

先把下面几件事查清，**输出一张表给用户确认**，再开始改任何文件：

1. ReMe 在跑吗？健康检查通过吗？端口与 workspace 各是什么？
2. 本机装了哪些宿主、各自在哪：Codex、Claude Code、DSH（可能一个都没装）。
3. 有没有第二台 Linux 机器？reme-helper 里是否配了 VM 目标？在那台机器上 `ss -ltn` 能看到隧道端口在监听吗？

输出格式：

| 端 | 是否适用 | 将采用的通路（见 §3） | 需要用户人工做的动作 |
|---|---|---|---|

**只有用户确认后**才继续往下做。适用与否由探测结果决定，不由本文的清单决定。

---

## 2. 要做到什么（各端一致）

每一端都要有两个能力：

- **召回**：会话里能检索长期记忆 —— 走 MCP。
- **自动记录**：每轮对话结束，把**新增**内容交回 ReMe，无需人工干预。

**不变量**（每一端都必须这样，不要自创）：

1. **记录走 REST，不走 MCP**：`POST <端点>/auto_memory`，一个请求、无握手；MCP 只服务于召回。
2. **消息形状固定**：`{ id, name, role, content:[{type:"text",text}], created_at }`，其中 `name` 必须等于 `role`；
   `session_id` 在工具 schema 里没标必填，但**运行时必需**（不填报 `Error: session_id is required`）。
3. **钩子只做锚点**：解析路径 → 拉起分离进程 → 立刻返回。提交由分离进程完成。
   会话结束时未完成的钩子会被取消，钩子里直接提交等于丢记录。
4. **幂等靠确定性 id**：id 由「会话短哈希 + 序号」生成，重发同一批由服务端按 id 去重 —— 这是"失败可安全重试"的基础。
5. **记忆整理全局只留一份**：只由 reme-helper 启动的那个 ReMe 做；客户端不要另开定时整理，也不要手动调用 `auto_dream`。
6. **端点写"本侧实际监听的那个口"**：同机写本机端口，跨机写隧道端口。写错的表现是 `fetch failed` / `Connection refused`。
7. **成功的凭据是产物，不是日志**：日志里的 `ok` 只说明这次调用返回了，对不存在的会话也会 `ok`。真凭据见 §6。
8. **水位线键必须规范化**：状态按「对话文件绝对路径」记账，斜杠方向要统一成一种写法
   （Windows 上钩子与手动调用拿到的可能是 `C:\` 与 `C:/` 两种），否则同一份文件裂成两条水位线互相打回——
   服务端按 id 去重能兜住产物不重复，但水位线永远合不拢。

---

## 3. 决策表：每一端走哪条通路

| 端 | 与 ReMe 同机 | 与 ReMe 跨机 |
|---|---|---|
| **Codex** | 捕获桥（见 §4） | **同一套捕获桥**，只换端点 |
| **Claude Code** | 官方插件 | **必须换成捕获桥** |
| **ZCode**（原生路线，装了才做） | 捕获桥（附录 C） | 同一套捕获桥，只换端点 |
| **DSH**（装了才做） | 官方插件 | 官方插件，只换端点 |

判断依据，必须知道，否则会做错：

- **官方 Claude Code 方案隐含"Claude Code 与 ReMe 同机"**：它的钩子只把 `session_id` 交给 ReMe，由 ReMe 去读自己磁盘上的
  对话文件（`~/.claude/projects/*/<session_id>.jsonl`）。跨机时读不到，返回"无消息"，而钩子日志仍然显示正常 —— **完全静默**。
- **官方 Claude Code 方案只在 Linux/macOS 上真正异步**：它靠 `fork()` 脱离进程；Windows 没有 `fork`，会**退化成同步执行**，
  而钩子超时只有 30 秒，记录会被砍掉。所以 **Windows 上也不能直接用官方版**：
  - 想与 VM 统一语义、只维护一套实现 → 同样走捕获桥（附录 B）。
  - 想少写代码、接受与 Codex 侧两套实现 → 用打过"真正异步"补丁的官方插件（用 `pythonw.exe` + `DETACHED_PROCESS`
    重新拉起自己后立即返回，钩子命令写 `pythonw` 的绝对路径，不依赖 PATH）。
- **Codex 官方没有自动记录**：官方只给 skill / MCP（文档原话是"自动捕获需要显式接入宿主生命周期"）。
  捕获桥是我们补的那一层胶水；机制本身（宿主生命周期钩子）是 Codex 官方功能，不是 hack。
- **ZCode 原生会话既没有 `~/.claude/projects` 转录，也不读 `~/.claude/settings.json`**：对话记录在自己的
  rollout（`<ZCODE_HOME>/cli/rollout/model-io-sess_<id>.jsonl`），钩子配置在 `<ZCODE_HOME>/cli/config.json`
  ——官方 Claude Code 钩子对它完全不生效，必须走捕获桥。

### Claude Code 记忆后端策略（接入前必须问用户，Windows 与 Linux 机制一致）

Claude Code 内核**自带一套记忆系统**，且**默认开启**：按项目存放在
`<CLAUDE_HOME>/projects/<项目目录>/memory/`（含 `MEMORY.md` 索引与 `.consolidate-lock` 整理锁），
由官方开关 `autoMemoryEnabled` / `autoDreamEnabled`（settings.json 顶层键）治理，另可设 `autoMemoryDirectory`。
接入 ReMe **不会自动关掉它**——不处理就会双记忆并存。先向用户说明两个选项，确认后再继续：

| | 只用 ReMe（推荐） | 双记忆共存 |
|---|---|---|
| 做法 | 关闭内建两开关 + 清理已有 memory 缓存（流程见 §5） | 什么都不用做 |
| 作用域 | ReMe 全机共享（同机所有端、跨机经隧道共用一个 workspace） | 内建记忆**按项目隔离**（`projects/<项目>/memory/`），换项目即失效 |
| 整理 | ReMe 的 dream 统一沉淀 digest | 内建 auto-dream 另行整理（实测常有"只写不整理"的堆积） |
| 代价 | 无 | 同一事实双写；两套记忆同时注入上下文，摊薄注意力；clear-code 等约定"单一记忆后端"的工具契约被破坏 |
| 还原 | 随时可还原（见 §8） | — |

选定"只用 ReMe"后执行 §5 的关闭小流程；用户选共存则跳过，**不要代做**。
注意 `~/.claude/rules/`（每会话强制注入）与内建 auto-memory 是**两套独立机制**——关闭后者不影响前者。

---

## 4. 通用捕获桥（唯一需要写代码的地方）

一句话：**客户端本地读对话文件 → 算出新增 → 内联成 ReMe 能吃的消息 → REST 提交；失败入队，下一轮重试。**

五个要素，缺一个就会静默出错：

1. **本地读**：读宿主自己写的对话文件（Codex 的 rollout、Claude Code 的 transcript），不要让服务端去读。
2. **水位线**：按"对话文件绝对路径"记已提交条数，只发新增，**只取最前面的 N 条**（oldest-first），未发的留给下一轮；
   只有提交成功才推进，且只推进实际发出的条数。写回前重新读盘取 `max` —— **水位线只增不减**，
   否则手工提交与钩子 worker 并发时两者各读旧值、各写回，后写者胜，水位线被打回，已入库内容被反复重发。
3. **确定性 id**：`<前缀>-<会话短哈希>-<序号>`，序号是这条消息在水位线中的位置。重发天然幂等。
4. **钩子分离 + 文件锁**：钩子毫秒返回；实际提交由分离进程做；**锁要覆盖所有提交入口**
   （钩子 worker、单会话手动提交、全量回补），否则两条路径必然抢写。陈旧锁按时间回收。
5. **失败入队**：提交失败就把任务写回队列文件，下一轮重试 —— 隧道断了、ReMe 重启了，连上之后自动补。

**消息渲染规则**（各端共用，照这个来）：

| 输入 | 处理 |
|---|---|
| 用户/助手文本 | 保留；多块用换行连接 |
| 工具调用 | `[tool <名称>(<入参，截断 200 字符>)]` |
| 工具结果 | `[tool_result <摘要，截断 200 字符>]` |
| 模型内部推理（thinking） | 丢弃 |
| 子代理/内部线程（如 `isSidechain`、Codex 的内部 thread） | 丢弃 |
| 整条只含宿主注入的样板（`<system-reminder>`、`<local-command-*>`、`<environment_context>` 之类） | 丢弃 |
| 时间戳 | 取原始行的时间戳写进 `created_at` |

**移植到某个宿主只需改四处**：对话文件目录、文件匹配规则、解析器、噪音前缀。
这四处之外的基础设施（端点解析、水位线、锁、队列、分离进程、REST 提交）各端共用：

| 端 | 对话文件位置 | 匹配规则 | 额外过滤 |
| --- | --- | --- | --- |
| Codex | `<CODEX_HOME>/sessions/<年>/<月>/<日>/rollout-*.jsonl` | 文件名以 `rollout-` 开头；会话 id 取 `session_meta` 行 | 内部子线程、审批/环境样板 |
| Claude Code | `<CLAUDE_HOME>/projects/<项目目录>/<会话id>.jsonl` | 每行一条 JSON；会话 id 即文件名 | `isSidechain`、注入模板、thinking |
| ZCode | `<ZCODE_HOME>/cli/rollout/model-io-sess_*.jsonl` | 文件名以 `model-io-sess_` 开头；会话 id 取文件名去掉 `model-io-` 前缀 | 辅助调用（`querySource≠main_turn`）、system 角色、注入模板、reasoning 块 |

**ZCode rollout 格式要点**（解析器照此实现，不要另猜）：

- 每行一条模型 I/O 记录：`{ querySource, sessionId, turnId, attempt, startedAt, completedAt, request, response }`。
- 消息在 `request.messages`，三种存法：`full`（全量，offset=0）、`delta`（自 `messageOffset` 起的增量）、
  `tail`（丢掉头部 `messageOffset` 条的尾部窗口）。三种都用**绝对下标 = `messageOffset` + j** 定位，
  逐行覆盖写入即可重建完整对话；历史被改写时以最新行为准。
- **只吃 `querySource = "main_turn"` 的行**：`session_title` 等辅助调用的消息坐标系与主对话完全不同，混进来必错。
- 每行还带一条 `response`（模型本轮回复：`text` + `toolCalls:[{id,name,input}]`）。它要等**下一行**才进历史
  ——扫完整个文件后必须把最后一行的 `response` 补到对话末尾，否则每轮漏最后一条助手消息。
- 消息条目 `role ∈ system|user|assistant|tool`；assistant 的 content 块只有 `text`（保留）与 `reasoning`（丢弃）；
  `tool_calls` 是扁平的 `{id,name,input}`，不是 OpenAI 的 function 嵌套。
- **ReMe 的 Msg 只收 `user/assistant/system`**：独立的 `role:"tool"` 结果条目必须映射成 `user` 角色内联
  `[tool_result …]` 文本，原样提交会报 `validation error for Msg`。

**端点解析优先级**（各端一致）：环境变量 `REME_URL` > **宿主自己那份配置** > 默认本机端口。
Codex 侧读捕获脚本目录下的 `config.json`；Claude Code 侧读插件自带的 `.mcp.json`（去掉 `/mcp` 后缀）。
**注意**：Claude Code 侧必须优先读插件 `.mcp.json`，不要读注册在客户端里的 MCP 配置 —— 两者可能不一致，
踩过的现象是钩子死连默认端口而 `curl` 隧道端口却是好的。

---

## 5. 分端接线清单

| 端 | 钩子挂在哪 | 端点写在哪 | 需要人工做什么 |
|---|---|---|---|
| Codex（同机） | `<CODEX_HOME>/hooks.json` 的 `Stop` | `<CODEX_HOME>/reme-bridge/config.json` | 在 Codex 里执行一次 `/hooks` **审核并信任**（未信任会被静默跳过） |
| Codex（跨机） | 同上（**同一份文件**：`command` 用 `$HOME` 供 Linux，`commandWindows` 用绝对路径供 Windows） | 同上，值改成 `http://127.0.0.1:<REMOTE_PORT>` | 同上，在那台机器的 Codex 里再做一次 |
| Claude Code（跨机） | `<CLAUDE_HOME>/settings.json` 的 `Stop`，指向捕获桥脚本 | 插件自带 `.mcp.json`（**改写成隧道端口**）+ `~/.claude.json` 的 `reme` MCP 注册，**两处必须一致** | 无（用户级 settings 里的钩子直接生效） |
| Claude Code（同机，走官方） | 同上，指向官方钩子（Windows 需打异步补丁，见 §3） | 插件 `.mcp.json` = 本机端口 | 无 |
| ZCode | `<ZCODE_HOME>/cli/config.json` 顶层 `hooks` 的 `Stop`，指向捕获桥脚本 | 脚本同目录 `config.json`（`mcpServers.reme.url`） | 无（对新会话生效；**必须显式 `"enabled": true`**——配置型钩子默认禁用） |
| DSH | 官方插件自管（无需钩子） | 插件配置里的 `endpoint` | 重启 DSH Web 并强刷浏览器 |

召回用的 MCP 注册：

```toml
# <CODEX_HOME>/config.toml
[mcp_servers.reme]
url = "http://127.0.0.1:<REME_PORT>/mcp"   # 跨机那台改成隧道端口
```

Claude Code 侧写 `~/.claude.json` 的 `mcpServers.reme`：`{ "type": "http", "url": "http://127.0.0.1:<端口>/mcp" }`。

其余固定动作：

- **不要既让 agent 手动调用记忆记录、又让钩子捕获**，否则同一段对话会被写两遍。在 `<CODEX_HOME>/AGENTS.md` 写明：
  **不要手动调用 `auto_memory` / `auto_dream`**。
- **不要新增任何客户端侧定时任务**：`crontab -l`、`systemctl --user list-timers`、Windows 计划任务里都不应有 ReMe 相关项。
- 跨机那台机器上，若 `notify` 指向另一台机器的路径（例如 Windows 的 `C:\...`），在 Linux 上永不生效且 `doctor` 不报错 —— 删掉或换成本机命令。
- Codex 的 MCP 工具调用受 approval 管控：`approval_policy = "never"` 会**直接拒绝**（报 `MCP tool call requires approval`）。
  交互式会话会弹批准；自动化运行加 `--approve-for-me`。

### Claude Code「只用 ReMe」关闭内建记忆（用户在 §3 选定后执行）

> 顺序不可换：**先备份 → 再看内容 → 再关 → 再删**。删掉的东西靠三重留存兜底
> （tar 备份 + 关键条目 `cat` 进会话输出 + 本会话结束时被 ReMe 钩子捕获入库）。

1. **前置确认**：没有其他活动 Claude Code 会话（`pgrep -af claude`；VSCode Remote 里常驻的会话先关）。
2. **备份**：`settings.json` 复制为 `.bak-<时间戳>`；把每个项目的 `memory/` 打成 tar 包并 `tar -tzf` 验证完整性。
3. **留存**：逐个 `cat` memory/ 下的条目进会话输出；其中 ReMe 已覆盖的注明出处，ReMe 未覆盖的**逐字迁入 ReMe**
   （daily 笔记或让用户拍板去向），不要静默删除独有内容。
4. **关开关**：`~/.claude/settings.json` **顶层**新增 `"autoMemoryEnabled": false` 与 `"autoDreamEnabled": false`，
   其余键（尤其 `hooks`——捕获链路在里面——与 `env`）一个字符都不动；改完用 `python3 -c "import json,…"` 校验 JSON。
5. **删缓存**：`rm -rf` 各项目的 `memory/` 目录，`find <CLAUDE_HOME>/projects -maxdepth 2 -type d -name memory` 应无输出。
6. **验收**：两键为 `false`；`hooks` 各键完好（Stop 下捕获钩子还在）；`rules/`、`skills/` 未被误伤。
7. **告知用户**：配置只对**新会话**生效，改动前已开的会话要关掉重开；若将来弃用 ReMe，按 §8 还原。

---

## 6. 验收：看产物，不看日志

逐端核对，全部要真凭据：

1. `POST /health_check` → `healthy: true`。
2. 每端聊一轮后，`<REME_WORKSPACE>/session/` 下出现本端对应的存档：
   Codex 与本方案的 Claude Code 落 `dialog/`（`codex-*.jsonl` 或 `<会话id>.jsonl`）；
   走官方插件的 Claude Code 落 `claude_code/<会话id>.jsonl`（保留原始条目）。
3. `<REME_WORKSPACE>/daily/<对话实际发生那天>/` 下出现便签（日期是对话那天，不是今天）。
   ReMe 会自行判断有无长期价值：寒暄之类只留存档、不建便签，属正常。
4. 跨机那端：在 ReMe 所在机器的记忆里能检索到另一台机器上聊过的内容。
5. 幂等：同一轮再提交一次 → 报告"无新增"，水位线不动、便签不重复。
6. 对账：`POST /app_config` 的 `jobs` 里只有一个 `dream_cron`；各客户端无定时任务。

**不算凭据的**：钩子日志里的 `ok`、`worker submitted`、HTTP 200 但 `success:false`。

命令行自查（Codex 侧；虚拟机里的 codex 通常不在 PATH，VSCode 扩展自带的例如 `/usr/lib/chatgpt/resources/codex`）：

```bash
CX=<codex 可执行文件>
$CX mcp list | grep reme
$CX exec --skip-git-repo-check --approve-for-me "随便说一句" < /dev/null
tail -5 <CODEX_HOME>/reme-bridge/capture.log
```

`< /dev/null` 不可省：非交互执行时 stdin 是不关闭的管道，`codex exec` 会一直等它而卡住。

---

## 7. 会静默失败的坑（按危险程度排序）

| 现象 | 原因 | 处置 |
|---|---|---|
| 钩子日志正常，但零产物 | 服务端读不到对话文件（跨机），或钩子未分离进程被会话结束取消 | 走捕获桥（§4） |
| `fetch failed` / `Connection refused` | 端点写错（跨机必须写隧道端口，不是本机默认端口） | 改端点，再手动补一次 |
| 钩子一直没反应 | Codex 的钩子未被信任 | 在 Codex 里执行 `/hooks` 信任 |
| ZCode 钩子一直不触发 | 配置型钩子默认禁用，或钩子错挂在 `~/.claude/settings.json`（ZCode 不读它） | `<ZCODE_HOME>/cli/config.json` 顶层设 `"hooks": { "enabled": true, … }` |
| HTTP 200 但 `success:false`、`validation error for Msg` | 消息缺 `name` 字段（必须等于 `role`） | 按 §2 的消息形状 |
| `validation error for Msg role`（ZCode） | `role:"tool"` 的结果条目按原角色提交了 | 映射成 `user` + `[tool_result …]`（见 §4） |
| 同一段对话两份便签 | agent 手动记录 + 钩子捕获重复 | 在 `AGENTS.md` 里禁止手动调用 |
| 同一事实两份记忆、上下文重复注入 | Claude Code 内建记忆未关，与 ReMe 并存 | 按 §3 问用户选定策略；只用 ReMe 时按 §5 关闭内建记忆 |
| 记忆里出现审批 JSON、环境样板 | 内部线程与注入文本未过滤 | 按 §4 的渲染规则 |
| 已入库内容被反复重发 | 水位线被并发打回 | 水位线只增不减 + 锁覆盖全部提交入口 |
| 已入库内容反复重发且水位线合不拢（ZCode） | 手动与钩子提交的路径斜杠方向不同，水位线裂成两条 | 键统一规范化（见不变量 8） |
| Windows 上官方 Claude Code 钩子超时 | 无 `fork` 退化成同步，超过 30 秒被砍 | 打异步补丁，或改用捕获桥 |
| DSH 插件报 `settingsNamespace` | 装了包管理源上的旧组合包 | 按 §9 源码构建 |
| DSH 插件报 `ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-llm` | 插件没放在 profile 目录内 | 移到 `<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\` |
| DSH 里看不到 `mcp__reme__*` 工具 | MCP 客户端没连上（`failOnStartupError: false` 不阻塞启动） | 确认 ReMe 在跑、`url` 正确；重启 DSH Web |

---

## 8. 回退

| 停用什么 | 操作 |
|---|---|
| Codex 自动记录 | 删掉 `<CODEX_HOME>/hooks.json`（每台机器各一份） |
| Claude Code 自动记录 | 删掉 `<CLAUDE_HOME>/settings.json` 里对应的 `Stop` 条目 |
| Claude Code 记忆工具 | 删掉 MCP 注册里的 `reme` |
| Codex 记忆工具 | 删掉 `config.toml` 里的 `[mcp_servers.reme]` |
| DSH 记忆插件 | `dsh plugin --profile <DSH_PROFILE> remove @agentscope-ai/reme-dsh-plugin` 后重启 |
| **弃用 ReMe、恢复 Claude Code 内建记忆** | 按接入时的备份还原：settings 备份复制回去（或把 `autoMemoryEnabled`/`autoDreamEnabled` 改回 `true`/删除——默认即开启），再把当时的 memory 缓存 tar 包解回 `projects/<项目目录>/`。**只对新会话生效**。ReMe 侧的 daily/digest/session 数据仍在 workspace 里，不会被这次还原删除 |

改动前对每个被修改的文件留 `.bak-<时间戳>` 备份。

---

## 9. 可选端：DSH（装了才做）

**Windows 侧安装（源码构建）**：包管理源上的旧组合包 `@agentscope-ai/reme@0.1.2` 与本机 DSH 版本不兼容
（它 import 了 `@deepseek-ai/dsh-settings` 运行时并未导出的 `settingsNamespace`，属上游打包不一致）；
新的专用包尚未发布到包管理源，因此按官方推荐的源码构建路径安装：

```powershell
git clone --depth 1 https://github.com/agentscope-ai/ReMe <SRC_DIR>\ReMe-src
cd <SRC_DIR>\ReMe-src\integrations\dsh
npm ci --ignore-scripts
node node_modules\typescript\bin\tsc -p tsconfig.json
node scripts\build-client.mjs            # 生成 dist\client.js；需要允许 esbuild 启动子进程
```

把构建产物装到 profile 下（**必须放在 profile 目录内**，否则宿主 peer 包解析不到，会报 `ERR_MODULE_NOT_FOUND`）：

```powershell
$dst = '<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\dsh-reme-plugin'
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item dist,cordis.patch.yml,package.json,README.md,README_ZH.md $dst -Recurse -Force
dsh plugin --profile <DSH_PROFILE> add $dst --ignore-scripts
```

在 `<DSH_HOME>\profiles\<DSH_PROFILE>\cordis.patch.yml` 追加 `reme-memory` 段：

```yaml
- id: reme-memory
  config:
    - id: reme-memory-runtime
      name: "@agentscope-ai/reme-dsh-plugin"
      config:
        endpoint: http://127.0.0.1:<REME_PORT>   # 跨机那台改成隧道端口
        language: zh            # 记忆指引语言，可改 en
        timezone: Asia/Shanghai
        autoMemoryEnabled: true
        autoMemoryInterval: 5   # 每多少轮提交一次
        autoDreamEnabled: false # 记忆整理只留给 reme-helper 那一份
        rootAgentsOnly: true
```

官方插件**只注册只读工具 `reme_search`**；会话内需要主动写记忆时，在同一份 `cordis.patch.yml` 里再插一段：

```yaml
- insert:
    - id: mcp-reme
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: streamable-http
        serverName: reme
        url: http://127.0.0.1:<REME_PORT>/mcp
        toolCallTimeoutMs: 60000
        failOnStartupError: false      # ReMe 没起也不阻塞 DSH 启动
        reconnect:
          enabled: true
```

然后**重启 DSH Web**（浏览器再强刷）。验证：新会话里出现 `reme-memory` 的上下文注入块；工具表里同时有
`reme_search` 与 `mcp__reme__<tool>`；聊满 `autoMemoryInterval` 轮后 `session/dialog/` 出现 `dsh-*.jsonl`。

**成本与能力面**：MCP 工具会全部注册进每次请求。这些工具落在稳定前缀里、走缓存价，**每请求增量的钱可以忽略**；
真正的代价是模型注意力（工具越多，工具选择越容易出错）与能力面（官方全开时 `delete`/`move`/`reindex`/`auto_dream`
也会交给 agent）。想收窄就用 reme-helper 的「MCP 工具暴露」逐项开关，收窄不影响后台自动记忆与定时整理。

---

## 附录：捕获脚本

三份脚本的全文由 reme-helper 在**复制时**自动附在下面，本文件里不重复维护，避免两处内容漂移。

### 附录 A：Codex 捕获脚本（`capture.mjs`）

落地 `<CODEX_HOME>/reme-bridge/capture.mjs`（**原样写入，不要改动消息结构**）。
同机与跨机是**同一份**脚本，只有 `config.json` 里的端点不同。

<!--APPENDIX A-->

### 附录 B：Claude Code 捕获脚本（`capture_cc.mjs`）

落地 `<CLAUDE_HOME>/plugins/reme-claude/hooks/capture_cc.mjs`（同机改走捕获桥时同理）；
运行时状态（水位线 / 锁 / 队列 / 日志）写在**脚本同级的 `bridge/` 目录**，与 Codex 侧完全隔离。
与附录 A 同构，只换了 §4 说的那四处。

<!--APPENDIX B-->

### 附录 C：ZCode 捕获脚本（`capture_zcode.mjs`）

落地 `<ZCODE_HOME>/cli/reme-bridge/capture_zcode.mjs`（同机与跨机同一份，只有 `config.json` 里的端点不同）。
运行时状态（水位线 / 锁 / 队列 / 日志）写在**脚本同级的 `bridge/` 目录**，与 Codex / Claude Code 侧完全隔离。
与附录 A 同构，只换了 §4 说的那四处；rollout 的格式见 §4 的「ZCode rollout 格式要点」。

<!--APPENDIX C-->
