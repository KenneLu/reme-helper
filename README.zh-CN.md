# reme-helper

[English](README.md) | 简体中文

把 ReMe 配好、把 Agent 接上，让多台机器共用同一份记忆。

**一个面向 [ReMe](https://github.com/agentscope-ai/ReMe) 的 Windows 托盘应用。** 它用窗口代替手写来生成 ReMe 的配置，运行服务，
并把 Agent 客户端——Windows 上的 Codex、虚拟机里的 Codex、DeepSeek Harness——接到同一个 ReMe 实例、同一份 workspace 上。

## 功能

### 配置

ReMe 的行为来自 YAML：哪些 job 开、按什么计划跑、用哪个模型与 Embedding 端点。本工具用窗口把这些配置写出来，
并且**先校验再落盘**——改动失败会回滚。

- **三种模式** —— 基础 / 全功能 / 自定义。模式由生成文件的内容推导，不会和实际运行的东西不一致。
- **Job 白名单** —— 写入 `service.jobs`，并逐项核对你这份 ReMe 里真实存在的 job（名字不存在会让 ReMe 启动失败）。
- **LLM 与 Embedding** —— 端点、模型、Key、token 预算、思考强度、Embedding 维度、整理计划。Key 进 `.env`，其余进生成的配置。
- **连接测试** —— 发一个真实请求，验证模型能按要求输出结构化 JSON（`auto_memory` / `auto_dream` 依赖它）；
  Embedding 测试要求近义句相似度高于无关句。

### 运行

启动、停止、重启 ReMe 服务，以及查看它是否健康，都在托盘里。

### VM 隧道

命名的 SSH 反向隧道目标，各自独立的 VM 端口，让 VM 访问同一个 ReMe 实例。掉线会自动接回；你停掉的不再被拉起。托盘可选择20秒至1小时的状态刷新间隔（默认5分钟），连接/断开会发事件通知，黄色点同步表示至少一条隧道在线。

## 接入的客户端

| 客户端 | 接入方式 |
|---|---|
| Codex（Windows） | MCP server 配置 + 一个自动记录对话的生命周期 hook |
| Codex（虚拟机内） | 同上，走反向隧道，端点指向隧道端口 |
| DeepSeek Harness | ReMe 官方 DSH 插件，另加 MCP 客户端配置以获得写记忆能力 |

三者的一步步做法随应用分发——可以在窗口里阅读，也可以复制（会自动附上 Codex 捕获脚本）后整份交给一个能改本机文件的 Agent。

## 安装

1. 从 [Releases](../../releases) 下载 `reme-helper-<版本>-windows-x64.zip`，解压到任意目录。
2. 运行 `reme-helper.exe`。它常驻托盘，双击图标打开控制台。
3. 如果没检测到 ReMe：点 **复制安装提示词** 交给 Agent 安装，然后指定 ReMe 目录——或点 **扫描** 自动查找。
4. 填好 LLM 与 Embedding 端点，点 **测试**，再点 **验证并保存**。
5. 接入 Agent 客户端：点 **阅读接入文档**（或 **复制接入文档**）照着做。

以后要更新，用托盘菜单里的 **检查 ReMe 助手更新**。它会原地替换，并把上一版留在
`%LOCALAPPDATA%\reme-helper\_backup`。
应用每次启动也会在后台检查一次；只有发现新版才通知，不会自动安装。

> [!IMPORTANT]
> Agent 要能用记忆，ReMe 必须在运行。本工具负责这件事，但它不安装 ReMe 本身——那是安装提示词与 **扫描** 的用途。

## 三种模式

| 模式 | 配置文件 | 开启的能力 |
|---|---|---|
| 基础模式 | `config/app.yaml` | Markdown 读写、BM25、Wikilink、Studio、MCP、索引维护；不调用模型 |
| 全功能模式 | `config/app-full.yaml` | ReMe 官方默认全开：Auto Memory、Auto Resource、Auto Dream、内部 Chat；需要 LLM 凭据 |
| 自定义模式 | `config/app-custom.yaml` | 逐项选择：自动记忆、Claude Code 入口、资料处理、Dream、Proactive、Chat、Embedding、FAISS、Studio、MCP |

切换模式只换能力集——地址、模型、Key、各项参数属于公共设置，不会被清空。在固定预设下改动某一项能力会转为自定义模式，并且只应用这一项改动。

## Skill 安装

Skill 只从一个位置读取。把 skill 装到 `~/.agents/skills/<名字>/`，Codex、DeepSeek Harness 以及遵循同一约定的其他 Agent 都能用；
**不要再往 `~/.codex/skills/` 复制一份**，那会让同一个 skill 被加载两次：

```text
~/.agents/skills/<名字>/SKILL.md      用户级规范位置
```

本应用本身不是 skill，解压 zip 即可使用，无需额外安装。

## 配置与数据

应用写出的东西全部在 `%LOCALAPPDATA%\reme-helper\` 下，不在你解压出来的那个目录里：

```text
config.json    窗口写出来的设置
log/           应用自己的日志，1MB 滚动、保留 3 份备份
_backup/       原地更新时留下的上一个版本
```

逐字段的参考见 [doc/zh/configuration.md](doc/zh/configuration.md)。记忆数据仍在 ReMe 的 workspace——删除 reme-helper
不会删除记忆。退出工具会停止由它启动的 ReMe 进程与 SSH 隧道。

## 故障排查

- **进程在运行，但托盘图标暂时没有出现**：Windows Explorer 偶尔会延迟清理旧图标。助手会在后台自动重试约 5 分钟；前三次重试仍失败时会显示说明对话框。日志位于 `%LOCALAPPDATA%\reme-helper\log\reme-helper.log`，可搜索 `tray: registration`。
- **需要无界面退出**：运行 `reme-helper.exe --quit`。它与托盘菜单的“退出”走同一套清理路径。
- **更新后需要回退**：上一版保存在 `%LOCALAPPDATA%\reme-helper\_backup`；退出当前实例后即可恢复。

## 开发

```bat
build.bat          :: 测试 + 图标 + 打包 + 校验，然后启动新版本
build.bat release  :: 同上，另加打包版 --release 门禁
build.bat norun    :: 只构建，不启动
release.bat        :: 打 v<版本> 标签并推送，由 CI 产出 zip
```

`src/` 是应用源码，`tests/` 是测试脚本（全部是构建门禁），`scripts/` 是构建脚本与发布配置生成器，`doc/` 是应用运行时读取的文档。
版本号只写在 `src/main.py` 的 `VERSION` 里——应用、发布目录名、git 标签都从它来；**推一个 `v*` 标签就是发布**。
历次改动见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE) © 2026 KenneLu
