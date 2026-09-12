# 配置参考（中文）

[English](../en/configuration.md) | 简体中文

面向使用者的入口文档见 [README](../../README.zh-CN.md)，历次更新记录见 [CHANGELOG](../../CHANGELOG.md)，
把 Codex / DSH 接入 ReMe 的步骤见 [接入文档](setup.md)。
本文是**技术细节参考**：字段、变量名、约束与校验规则。应用内「打开指引（文件在哪）」里的控制台说明
讲的是同一批内容的操作口径，两边保持一致。

> 文中出现的 `H:\Tools\ReMe` 只是**默认值示例**：第一次运行可以在设置窗口里改，或用「扫描…」自动探测。

## 三种模式

| 模式 | 配置文件 | 用途 |
|---|---|---|
| 基础模式 | `<ReMe>\config\app.yaml` | 不调用模型；保留 Markdown 读写、BM25、Wikilink、Studio、MCP 和索引维护 |
| 全功能模式 | `<ReMe>\config\app-full.yaml` | 继承 ReMe 官方 default 全开；需要 LLM 凭据；包含 Auto Memory、Auto Resource、Auto Dream 和内部 Chat |
| 自定义模式 | `<ReMe>\config\app-custom.yaml` | 按设置窗口逐项选择自动记忆、Claude Code 入口、资料处理、Dream、Proactive、Chat、Embedding、FAISS、Studio 和 MCP |

前两项是**固定预设**（对应两个不由本工具生成的配置文件）。设置窗口里的规则：

- **模式由配置内容推导，而不是声明**：草稿一旦与某个预设完全一致，模式会自动切换成该预设（Toast 提示），因此「当前模式」永远如实反映内容；
- **切换模式只换「能力集」，你填的数据一律保留**：地址、模型名、Key、维度、调过的参数都会跟着走（这些属于账号级配置，在任何模式下都通用），所以从基础切到全功能或自定义不会清空你已填的内容；
- **模式身份只看能力项**：在固定预设下改动能力项（功能开关 / 后台 Job）会转为**自定义**，且**只应用这一项**（基线＝你当时的起点）并 Toast 提示；
- **公共设置不改变模式**：地址、模型、Key、token 预算、思考强度、Embedding 维度、整理参数、MCP 允许列表在哪个模式下都成立，随便调，模式不变；
- 点击「当前已选模式」不做任何事；
- 状态条显示**基线**（基础模式 / 全功能模式 / 已保存配置）：「回到基线」就是回到这个起点。

ReMe 未运行时，切换模式只保存选择，不会自动启动。ReMe 运行中切换模式会先弹出二次确认；确认后验证新配置、停止旧服务并启动新服务，新服务失败会尝试恢复旧模式。

## 语言与主题

- 控制台右上角或托盘切换；深色模式选择会被记住（深色下用 `clam` 主题，因为 Windows 原生主题忽略颜色设置；浅色与深色现在共用同一个 ttk 引擎，避免切换时控件高度不一致导致整页位移）。
- 中英对照表在 `i18n.py`，一行一条；未收录的文案自动回退中文。
- 窗口标题与托盘提示跟着语言走（英文下形如 `ReMe Helper <版本> · Console`，版本号取自 `src/main.py` 的 `VERSION`）；`APP_ID` 不动，所以托盘窗口类名与开机自启注册表项与语言无关。

## 托盘菜单

- 只读状态区：ReMe 状态、当前模式、VM 隧道数量；
- **ReMe 控制台…**（**默认项，双击托盘图标即打开**；模式的切换与微调都在这里，托盘不再提供可点击的模式项）；
- 启动、停止、重启 ReMe；
- 打开 ReMe Studio、workspace，以及**「打开指引（文件在哪）…」**——「路径与入口」小窗口，列出 ReMe 目录 / workspace / 当前配置 / 官方 default / `.env`（凭据）/ 日志目录 / 控制台说明 / 接入文档，每行可以「打开」或「复制路径」；
- 启动／停止全部 VM 隧道；通过「VM 目标」子菜单添加、编辑、删除和启停多个目标，并重新扫描本机 SSH 密钥；
- 开机自启、启动工具时启动 ReMe、ReMe 启动后启动隧道。

## LLM、Embedding 与记忆管道

设置窗口按区块组织，保存时一起写盘。

**LLM 与模型**

- Base URL、模型（可手动输入，也可点「刷新模型」从端点的 `/v1/models` 拉取候选）；
- API Key 使用掩码输入，留空表示不修改已有值；
- `max_tokens`、`thinking_enable`、**思考强度**（`reasoning_effort`，与 Codex 一致的六档）会注入生成的配置（`components.as_llm.default.parameters`）；
- 「测试连接」发一个**带 JSON 要求的真实请求**，验证两件事：① 对话接口可用；② **能按要求输出结构化 JSON**（auto_memory / auto_dream 依赖它）。若连通但 `content` 为空（内容全在 `reasoning_content`），会明确提示「思考型模型占满预算，auto_dream 会写出空内容」；输出不是 JSON 也会判为不通过；
- **测试前先自检凭据**：Base URL / 模型名 / API Key 任一未填就**不发起请求**，直接点名缺哪个（例如「缺少 LLM_API_KEY，未发起测试」），避免把「没填 Key」误判成「接口不通」；
- 输入框的值在**离开输入框时即收入草稿**，之后再点其它选项不会覆盖已填内容。

**Embedding（语义检索）**

- 独立的地址 / 模型 / API Key / 维度；模型与维度写入生成的配置（`components.as_embedding`），凭据写入 `.env` 的 `EMBEDDING_*`；
- 「测试 Embedding」做三件真实检查：① 端点确实提供 embedding（不是 404）；② 返回维度与配置一致；③ **语义排序正常**——用「猫喜欢吃鱼 / 小猫爱吃鱼 / 今天股市大涨」三条样本，要求近义对的相似度**高于**无关对。通过时提示会写明「近义 0.83 > 无关 0.19，维度 1024」；端点不接受 `dimensions` 参数会自动重试并注明；
- 未通过测试也可以保存，但保存时会再确认一次并提示「启用后不会生效」；真正生效需要：测试通过 → 重建索引（`scope=embedding`）→ 搜索结果显示向量命中。

**记忆管道（成本与质量闸门）**

- 扫描天数、单次最多沉淀、整理计划都是**档位下拉**（1/2/3/7 天、3/5/10 个、每天 23:00/03:00/12:00 + 自定义 cron），避免手填语法错误；
- 实时效果预览：下次整理时间、扫描范围（用真实 workspace 统计的 daily 文件数与字符量）、调用上界（1 次抽取 + 每个 unit 一次整理）、产出位置；
- 「立即整理一次」在后台调用 ReMe 的 `auto_dream`（会调用模型并修改 workspace）；「重建索引」调用 `reindex`，未启用 Embedding 时 scope 只提供 `all` / `bm25`；
- 区块顶部的**「启用自动记忆与整理」**开关同时开关 Auto Memory 与 Auto Dream（两者不一致时显示「部分启用」），需要 LLM 就绪；
- 两个按钮各自标注依赖并在不满足时禁用：**立即整理**需要 Auto Dream 已启用 + LLM 就绪 + 服务运行中（会花 token）；**重建索引**不调用模型，只需服务运行中。

**MCP 工具暴露**

- 勾选「自定义允许列表」后写入 `service.jobs`；`write` / `edit` 决定 Agent 能否精确写入记忆，`auto_memory` / `auto_dream` 允许 Agent 主动触发整理。不勾选则沿用 ReMe 默认（暴露全部非流式 Job）；
- 列表按当前模式与已启用能力逐项门控：该配置里不存在的 job 会被禁用（写进配置会让 ReMe 启动时直接失败）。

**保存行为**

- `验证并保存` **不再自动关闭窗口**：保存成功后窗口保持打开，基线、状态条与「未保存改动」计数立即刷新，并弹出 Toast 与提示框说明本次结果（含「服务已按新配置重启」），可继续调整；
- 保存失败会回滚 `config.json`、`.env` 与运行中的服务模式，窗口保持打开便于就地修正。

## 凭据与环境变量

- 完整模式和启用 LLM 功能的自定义模式要求 `<ReMe>\.env`（或当前环境）提供 `LLM_API_KEY` 与 `LLM_BASE_URL`；本地 Ollama 后端例外。配置窗口可以创建本地 `.env` 模板；
- `.env` 与保存值不一致时**以 `.env` 为准**（ReMe 真正读的是它）：界面会按 `.env` 校正并提示校正了哪几项，保存后再写回 `config.json`；
- 工具不会显示密钥正文，只检查是否存在非空值；「导出配置」时密钥类字段会被脱敏（`api_key` / `token` 等显示成 `***`）。

## ReMe 目录探测

- 默认 `<盘符>\Tools\ReMe`，可手动选择，也可点「扫描…」自动探测（本机常见目录、`REME_ROOT`、各盘 `Tools\ReMe`、`~/ReMe`、`%LOCALAPPDATA%\Programs\ReMe` 等）；判定标准是「存在 `venv\Scripts\python.exe` 且同目录有 `reme.exe` 或 `reme` 包」；
- 目录不可用时区块 1 显示橙色提示：扫描到候选就提示「点扫描采用」，什么都没有则给出安装步骤，并提供 **`复制安装提示词`**（一段可直接发给 DSH / Codex 的安装指令，含建 venv、`pip install "reme-ai[core]"`、`reme start service.backend=http`、健康检查与回报要求）与 **`打开官方文档`**；
- 切换根目录前会检查 `venv\Scripts\reme.exe`、配置与版本；版本检查直接用 ReMe 的虚拟环境读包元数据，**不要求 ReMe 正在运行**；
- **端点字段会从 `.env` 回填**：若 `config.json` 里 LLM / Embedding 的地址或模型为空而 `.env` 有值，打开窗口时会自动补全并 Toast 说明。

## VM 隧道

示例目标为 `ubuntu@192.168.1.100`：

```text
VM 127.0.0.1:22333  ── ssh -R ──▶  Windows 127.0.0.1:2333
```

每个目标可独立设置名称、用户、主机（IP 或 `~/.ssh/config` 别名）、SSH 端口、VM 映射端口、私钥路径和启用状态；留空私钥路径时由 OpenSSH 使用默认密钥；不同 VM 可用各自的映射端口。

工具优先使用 Windows 已有 SSH 密钥，**不生成密钥、不修改防火墙**。VM 里的客户端连接 `http://127.0.0.1:<映射端口>/mcp`。

掉线的隧道会由健康检查自动接回；你手动停掉的隧道不会被自动拉起——工具记着你要的是哪一种。

## 数据边界

- 工具自己的配置在 exe 旁边；日志在用户数据目录（`%LOCALAPPDATA%\reme-helper\log\reme-helper.log`，1MB 滚动、保留 3 份备份）。ReMe 数据仍在 ReMe 的 workspace，**卸载或删除 reme-helper 不会删除记忆**；
- 退出工具会停止由本次工具启动或接管的 ReMe 进程与 SSH 隧道；
- 发布包里的 `config.json` 是出厂模板（不含任何开发机信息），由 `make_release_config.py` 生成；你自己的 `config.json` 永远不会被打进发布包（已 gitignore）。

## 构建与发布

```bat
build.bat            :: 测试 + 图标 + PyInstaller + 校验
build.bat release    :: 同上，再加打包版 --release 自检
build.bat run        :: 构建成功后直接启动
build.bat clean --force
```

产物在 `release\reme-helper-<版本>\`；构建中间物在 `.cache\`（PyInstaller 的 dist/work/spec 与按需创建的 venv）。
构建脚本按「先本地约定的解释器、再 PATH 上的 `python`」的顺序挑解释器（约定的路径在 `scripts/build.bat` 顶部，按自己机器改一行即可）；找不到 PyInstaller 会自动建一个隔离 venv 并装 `requirements.txt`，所以干净机器（或 CI）只要有 Python 即可。
