# 把 Codex 与 DSH 接到 ReMe（接入 Agent 文档）

> **怎么用这份文档**：在 reme-helper 里点「复制接入文档」，把复制到的**全文粘贴给一个能读写本机文件的 AI Agent**，
> 它就能按本文完成接入。也可以在 reme-helper 里点「阅读接入文档」先看一遍。
> 文中 `<...>` 是占位符，执行前替换成本机真实值（见下方变量表；ReMe 端口与 workspace 在复制时已自动填好）。

本文只讲「把客户端接入 ReMe」这一件事，与具体 skill 或第三方工具无关。
所有步骤都在真实机器上跑通过；请按本文实现，不要自行设计替代方案。

---

## 0. 变量表

| 占位符 | 含义 | 取值来源 |
|---|---|---|
| `<REME_PORT>` | ReMe HTTP 服务端口 | reme-helper 配置，默认 `2333` |
| `<REME_WORKSPACE>` | ReMe 记忆目录（含 `daily/ digest/ session/`） | reme-helper 里的 ReMe 目录下 `workspace` |
| `<DSH_HOME>` | DSH 主目录 | Windows 默认 `%USERPROFILE%\.dsh` |
| `<DSH_PROFILE>` | 要接入的 profile | Web 界面用 `web` |
| `<CODEX_HOME>` | Codex 主目录 | Windows 默认 `%USERPROFILE%\.codex` |
| `<SRC_DIR>` | 临时源码目录 | 自选 |
| `<REMOTE_PORT>` | 虚拟机侧隧道端口 | reme-helper 的 VM 目标设置，例如 `22333` |
| `<VM_HOST>` `<VM_USER>` | 虚拟机地址与用户名 | 你的环境 |
| `<VM_CODEX_HOME>` | 虚拟机里的 Codex 主目录 | 例如 `/home/<VM_USER>/.codex` |

**前置条件**：ReMe 已由 reme-helper 启动（完整模式 + LLM + embedding），
`POST http://127.0.0.1:<REME_PORT>/health_check` 返回 `healthy: true`。
ReMe **只监听回环地址**且不使用 API Key —— 这决定了「跨机器必须走隧道」以及「所有客户端指向同一个 workspace」。

---

## 1. 做完之后你会得到什么

| # | 能力 | 实现方 |
|---|---|---|
| 1 | DSH 对话**每 5 轮自动**写入 ReMe，新会话自动注入记忆使用指引 | ReMe 官方 DSH 插件 |
| 2 | DSH 会话内可按需检索长期记忆 | 同上（只读工具 `reme_search`） |
| 3 | DSH 会话内可**读写**记忆（新建/修改记忆节点） | DSH 自带官方 MCP 客户端 + ReMe MCP |
| 4 | Codex（Windows 与虚拟机内的 VSCode 扩展）可检索与写入记忆 | ReMe MCP + Codex 的 MCP 客户端 |
| 5 | Codex **每轮结束自动**把新增对话交给 ReMe | Codex 官方 lifecycle hook + 本文附录 A 的捕获脚本 |
| 6 | 记忆整理（daily→digest）只由 reme-helper 启动的那一份 ReMe 执行 | 配置（关掉客户端侧调度） |

---

## 2. 官方能力对照（先读，理解本方案为何这样设计）

| Agent | ReMe 官方接入方式 | 官方自带「自动记录对话」 |
|---|---|---|
| DeepSeek Harness | 官方插件 `@agentscope-ai/reme-dsh-plugin` | ✅ 有，零自写代码 |
| Claude Code | MCP + skill + **Stop hook**（ReMe 仓库自带 `integrations/claude_code/reme/hooks/`） | ✅ 有 |
| OpenClaw / Hermes / QwenPaw | 官方插件 / provider / Python API | ✅ 有 |
| **Codex（含虚拟机内的 VSCode 扩展）** | **仅一个 skill** | ❌ **没有** |

**结论**：Codex 是目前唯一「官方给了 skill、但没给自动捕获」的宿主。ReMe 文档原话是
*「自动捕获需要显式接入宿主生命周期」*。所以 Codex 的自动记录需要一段宿主侧 hook，
**它与 ReMe 官方给 Claude Code 发布的 hook 是同一套设计**（见 §3.4），不是自定义方案；
Codex 的 lifecycle hooks 是 Codex 官方功能（`features.hooks`，默认开启）。

**唯一需要绕过的上游问题**：ReMe 的 DSH 插件在包管理源上的旧组合包 `@agentscope-ai/reme@0.1.2`
与 DSH 0.1.2 线不兼容 —— 它 import 了 `@deepseek-ai/dsh-settings` 运行时并未导出的 `settingsNamespace`
（上游打包不一致）；而新的专用包尚未发布到包管理源。因此按官方推荐的源码构建路径安装（§3.2）。

---

## 3. Windows 端

### 3.1 Codex：先接记忆工具（MCP）

在 `<CODEX_HOME>\config.toml` 追加：

```toml
[mcp_servers.reme]
url = "http://127.0.0.1:<REME_PORT>/mcp"
```

重启 Codex 后验证：`codex mcp list` 显示 `reme … enabled`。
让 Codex 用 `reme` 的 `search` 工具检索一个已知记忆节点（例如问它「用 reme 的记忆检索 xxx 并列出文件路径」），
能看到 `mcp_tool_call server=reme tool=search` 及其返回即成功。

**注意**：Codex 的 MCP 工具调用受 approval 管控。`approval_policy = "never"` 会**直接拒绝**
（报 `MCP tool call requires approval, but approval policy is never`）。交互式会话会弹批准；
自动化运行加 `--approve-for-me`。

### 3.2 DSH：安装官方插件（源码构建）

```powershell
git clone --depth 1 https://github.com/agentscope-ai/ReMe <SRC_DIR>\ReMe-src
cd <SRC_DIR>\ReMe-src\integrations\dsh
npm ci --ignore-scripts
node node_modules\typescript\bin\tsc -p tsconfig.json
node scripts\build-client.mjs            # 生成 dist\client.js；需要允许 esbuild 启动子进程
```

把构建产物装到 profile 下（**必须放在 profile 目录内**，否则宿主 peer 包解析不到，会报
`ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-llm`）：

```powershell
$dst = '<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\dsh-reme-plugin'
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item dist,cordis.patch.yml,package.json,README.md,README_ZH.md $dst -Recurse -Force
dsh plugin --profile <DSH_PROFILE> add $dst --ignore-scripts
```

在 `<DSH_HOME>\profiles\<DSH_PROFILE>\cordis.patch.yml` 追加：

```yaml
- id: reme-memory
  config:
    - id: reme-memory-runtime
      name: "@agentscope-ai/reme-dsh-plugin"
      config:
        endpoint: http://127.0.0.1:<REME_PORT>
        language: zh            # 记忆指引语言，可改 en
        timezone: Asia/Shanghai
        autoMemoryEnabled: true
        autoMemoryInterval: 5   # 每多少轮提交一次
        autoDreamEnabled: false # 记忆整理只留给 reme-helper 那一份
        rootAgentsOnly: true
```

### 3.3 DSH：挂官方 MCP 客户端，补齐「写记忆」能力

官方插件**只注册只读工具 `reme_search`**，写入只发生在后台自动记忆。会话内需要主动落盘时，
在同一份 `cordis.patch.yml` 里再插入一段：

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

然后**重启 DSH Web**（浏览器再 Ctrl+Shift+R 强刷）。

**验证**：
- 新会话里出现 `reme-memory` 的上下文注入块（元数据 `plugin=reme-memory`、`form=instructions`）；
- 工具表里同时有插件自带的 `reme_search` 与 MCP 的 `mcp__reme__<tool>`（`search`/`read`/`write`/`edit`/…）；
- 聊满 `autoMemoryInterval` 轮后，`<REME_WORKSPACE>\session\dialog\` 出现 `dsh-*.jsonl`、`daily\<日期>\` 出现便签。

**上下文与费用影响（实测）**：MCP 工具会全部注册进每次请求。以 ReMe 默认暴露（官方全开）为例：
30 个工具使请求工具块从 53,535 → 65,201 字符（+11,137 ≈ 2.8k tokens）。
这些工具落在稳定前缀里、走**缓存价**（DeepSeek V4 Flash 类模型：输入 $0.14/M、缓存 $0.0028/M，
缓存价约为输入价的 1/50），因此**每请求增量的钱可以忽略**；
粗算公式：`增量 ≈ 2,942 tokens × 请求次数 × 缓存单价`。
MCP 的真实代价不在钱，而在**模型注意力**（工具越多，工具选择越容易出错），
以及能力面：官方全开会把 `delete`/`move`/`reindex`/`auto_dream` 一并交给 agent。
若想收窄，用 reme-helper 的「MCP 工具暴露」逐项开关；收窄不影响后台自动记忆与定时整理。

### 3.4 Codex：自动记录（本文最关键的一步）

**参考实现**：ReMe 官方 Claude Code hook —— `integrations/claude_code/reme/hooks/hooks.json`
与 `hooks/auto_memory.py`。官方那份做的是：绑定 **`Stop` 事件** → 脚本从 stdin 取 `session_id` →
**先脱离进程（double-fork）立刻返回，绝不阻塞停止** → 由脱离出来的进程调用 ReMe 的记忆记录任务。

我们的 Codex 版**沿用同一设计**，只有一处必要差异：ReMe 没有 Codex 的对话解析器
（它有 Claude Code 专用的 `auto_memory_cc`，但没有 `auto_memory_codex`），
所以捕获脚本要自己解析 Codex 的 rollout 文件，再交给**通用**的 `auto_memory` 任务。

**第一步**：把**附录 A** 的捕获脚本原样写到 `<CODEX_HOME>\reme-bridge\capture.mjs`
（reme-helper 的「复制接入文档」会把附录 A 一并附在文末；若你只拿到文件，则见上一级目录的 `capture.mjs`（`doc/capture.mjs`））。

它做五件事：读 rollout → 过滤注入样板与内部线程 → 组装 ReMe 的消息结构 →
按 rollout 记水位线做增量幂等 → `POST /auto_memory`。
其中两条是硬约束（都来自 Codex hook 的文档行为，违反会**静默失败**）：

- hook 本体必须**毫秒返回**：`Stop` 事件要求退出码 0 时 stdout 是合法 JSON，且后台 `async` hook 会在会话结束时被取消。
  所以 hook 只做「解析事件里的 `transcript_path` → 分离一个常驻 worker → 输出 `{}` → 退出」。
- 并发会话不能丢记录：用队列文件 + 锁重试 + 失败回队。

**第二步**：写端点配置 `<CODEX_HOME>\reme-bridge\config.json`：

```json
{ "endpoint": "http://127.0.0.1:<REME_PORT>" }
```

**第三步**：新建 `<CODEX_HOME>\hooks.json`（**纯新增文件，不要改 config.toml 里的 notify**）：

```jsonc
{
  "hooks": {
    "Stop": [
      { "hooks": [ {
        "type": "command",
        "command": "node \"$HOME/.codex/reme-bridge/capture.mjs\" --hook",
        "commandWindows": "node \"<CODEX_HOME>\\reme-bridge\\capture.mjs\" --hook",
        "timeout": 30,
        "statusMessage": "ReMe: capturing this turn"
      } ] }
    ]
  }
}
```

**第四步（必须人工做一次）**：在 Codex 里执行 `/hooks`，审核并**信任**这个 hook。
未信任的 hook 会被 Codex **静默跳过**（不报错，日志里什么都没有）。

**验证**：随便聊一轮后，`<CODEX_HOME>\reme-bridge\capture.log` 出现
`hook event=Stop … queued+drain` 与 `worker submitted session=codex-…`；
`<REME_WORKSPACE>\session\dialog\` 出现 `codex-*.jsonl`。
（ReMe 会自行判断对话是否有长期价值：寒暄之类只留 transcript、不建便签，属正常。）

**边界**：不要既让 agent 手动调用记忆记录、又让 hook 捕获，否则同一段对话会被写两遍。
建议在 `<CODEX_HOME>\AGENTS.md` 写明：**不要手动调用 `auto_memory` / `auto_dream`**。

### 3.5 记忆整理归属（只允许一份）

`POST /app_config` 的 `jobs` 中应只有**一个** `dream_cron`（如 `0 23 * * *`，由 reme-helper 写入）；
`auto_dream`/`auto_memory` 是按需任务，不是调度器。
客户端侧：DSH 插件 `autoDreamEnabled: false`；Codex 不建任何定时任务；不要手动调用 `auto_dream`。

---

## 4. 虚拟机（Ubuntu）端：先隧穿，再同款接入

### 4.1 为什么必须隧穿

ReMe 只监听回环地址，虚拟机无法直连 Windows 的 `<REME_PORT>`。
reme-helper 的做法是在 Windows 上向虚拟机建立 **SSH 反向隧道**：
虚拟机的 `127.0.0.1:<REMOTE_PORT>` → Windows 的 `127.0.0.1:<REME_PORT>`。
（reme-helper 的托盘菜单「VM 目标」里添加目标、配置端口后随 ReMe 一起启停。）

在虚拟机里验证：

```bash
ss -ltn | grep <REMOTE_PORT>
python3 -c "import json,urllib.request;r=urllib.request.Request('http://127.0.0.1:<REMOTE_PORT>/version',data=b'{}',headers={'Content-Type':'application/json'});print(json.loads(urllib.request.urlopen(r,timeout=20).read())['answer'])"
```

### 4.2 虚拟机侧配置（与 Windows 同款，端点换成隧道端口）

1. `<VM_CODEX_HOME>/config.toml` 追加：

```toml
[mcp_servers.reme]
url = "http://127.0.0.1:<REMOTE_PORT>/mcp"
```

2. 拷贝捕获脚本到 `<VM_CODEX_HOME>/reme-bridge/capture.mjs`（与 Windows 同一份，Linux 的 node 18+ 可直接运行）。
3. 写 `<VM_CODEX_HOME>/reme-bridge/config.json`：

```json
{ "endpoint": "http://127.0.0.1:<REMOTE_PORT>" }
```

4. 拷贝 `hooks.json` 到 `<VM_CODEX_HOME>/hooks.json`（同一份文件即可：`command` 用 `$HOME` 供 Linux，
   `commandWindows` 供 Windows）。
5. 在虚拟机里的 Codex 中同样执行一次 `/hooks` 信任。

**验证**（虚拟机的 codex 通常不在 PATH，VSCode 扩展自带，例如 `/usr/lib/chatgpt/resources/codex`）：

```bash
CX=/usr/lib/chatgpt/resources/codex
$CX mcp list | grep reme
$CX doctor | grep -E 'parse|MCP servers'
$CX exec --skip-git-repo-check --approve-for-me "随便说一句" < /dev/null
tail -5 <VM_CODEX_HOME>/reme-bridge/capture.log
```

`< /dev/null` 不可省：非交互执行时 stdin 是不关闭的管道，`codex exec` 会一直等它而卡住。

### 4.3 虚拟机上不该存在的东西

- `notify` 若指向 Windows 路径（例如 `C:\...\codex-computer-use.exe`），在 Linux 上永不生效，
  且 `doctor` 不报错 —— 应删除或替换为虚拟机本地命令。
- 客户端侧的整理调度：`crontab -l`、`systemctl --user list-timers` 不应有 ReMe 相关项。

---

## 5. 故障排查（按「会静默出错」排序）

| 现象 | 原因 | 处置 |
|---|---|---|
| `worker error … fetch failed` | 端点写错（虚拟机上的 ReMe 在隧道端口，不是 `<REME_PORT>`） | 改 `reme-bridge/config.json`，再 `node capture.mjs --drain` |
| `capture.log` 一直没有内容 | hook 未信任 | 在 Codex 里执行 `/hooks` 信任 |
| `validation error for Msg`（HTTP 200 但 `success:false`） | 消息缺 `name` 字段 | 用附录 A 的脚本，勿自改消息结构 |
| 记录丢失 / `worker skipped` | 旧实现并发时丢记录 | 用附录 A 的脚本（队列 + 锁重试），并 `--drain` 补回 |
| 同一对话两份便签 | agent 手动记录 + hook 捕获重复 | 在 `AGENTS.md` 写明不要手动调用 `auto_memory` |
| 记忆里出现审批 JSON / 环境样板 | rollout 里的内部线程与注入文本未过滤 | 用附录 A 的脚本（已按来源与前缀过滤） |
| 插件报 `settingsNamespace` | 装了包管理源上的旧组合包 | 按 §3.2 源码构建 |
| 插件报 `ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-llm` | 插件没放在 profile 目录内 | 移到 `<DSH_HOME>\profiles\<DSH_PROFILE>\local-plugins\` |
| MCP 调用被拒 `requires approval` | `approval_policy = "never"` | 交互式批准；自动化用 `--approve-for-me` |
| MCP 工具没出现在 DSH 里 | MCP 客户端没连上（`failOnStartupError: false` 不阻塞启动） | 确认 ReMe 在跑、`url` 正确；重启 DSH Web |

## 6. 做完怎么确认（逐条核对）

1. `POST /health_check` → `healthy: true`，四个组件 `is_started: true`
2. DSH 新会话有 `reme-memory` 注入块；工具表里有 `reme_search` 与 `mcp__reme__*`
3. DSH 聊满 `autoMemoryInterval` 轮 → `<REME_WORKSPACE>\session\dialog\dsh-*.jsonl` 出现
4. `codex mcp list` → `reme enabled`
5. Codex 聊一轮 → `capture.log` 有 `worker submitted`；ReMe 侧出现 `codex-*.jsonl`
6. 虚拟机：`ss -ltn | grep <REMOTE_PORT>` 有监听；`$CX mcp list` 里 reme enabled；虚拟机会话能在 Windows 侧检索到
7. `POST /app_config` → 只有一个 `dream_cron`；客户端无定时任务

## 7. 一键跑通（新机器按此顺序）

| 步骤 | 做什么 | 见 |
|---|---|---|
| 1 | reme-helper：装好并启动 ReMe（完整模式 + LLM + embedding）；确认 `/health_check` 正常；记下端口与 workspace | §0 |
| 2 | DSH 官方插件：源码构建 → 拷进 profile 的 `local-plugins` → `dsh plugin add` → 在 `cordis.patch.yml` 写 `reme-memory` 段 | §3.2 |
| 3 | DSH 的 MCP 写能力：同一 patch 文件里 insert `mcp-reme` 段 | §3.3 |
| 4 | **重启 DSH Web**，浏览器 Ctrl+Shift+R | §3.3 |
| 5 | Codex 记忆工具：`config.toml` 加 `[mcp_servers.reme]` | §3.1 |
| 6 | Codex 自动捕获：写 `capture.mjs` → 写 `reme-bridge/config.json` → 新建 `hooks.json` → 在 Codex 里 `/hooks` 信任 | §3.4 |
| 7 | 虚拟机：开隧穿 → 虚拟机的 `config.toml` / `hooks.json` / `reme-bridge/config.json`（端点写 `<REMOTE_PORT>`）→ 在虚拟机的 Codex 里 `/hooks` 信任 | §4 |
| 8 | 逐条核对第 6 节 | §6 |

**两个硬依赖**：第 2 步必须在第 4 步（重启）之前完成；第 6/7 步的 `/hooks` 信任是人工动作，
未信任时 hook 静默跳过。

## 8. 回退

| 停用什么 | 操作 |
|---|---|
| Codex 自动捕获 | 删除 `<CODEX_HOME>\hooks.json`（Windows 与虚拟机各一份） |
| DSH 记忆插件 | `dsh plugin --profile <DSH_PROFILE> remove @agentscope-ai/reme-dsh-plugin` 后重启 |
| DSH 的 MCP 写能力 | 删掉 `cordis.patch.yml` 里的 `- insert: mcp-reme` 段后重启 |
| Codex 记忆工具 | 删除 `config.toml` 里的 `[mcp_servers.reme]` |

---

## 附录 A：Codex 捕获脚本（`capture.mjs`）

> reme-helper 的「复制接入文档」会把脚本全文附在这里，粘贴给 AI 即可一次拿到"文档 + 脚本"。
> 如果你是在文件系统里看到这份文档，脚本在上一级目录的 `capture.mjs`（`doc/capture.mjs`）。
> 落地路径：`<CODEX_HOME>\reme-bridge\capture.mjs`（**原样写入，不要改动消息结构**）。
