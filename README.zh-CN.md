# reme-helper

[English](README.md) | 简体中文

把 ReMe 配好、把 Agent 接上，让多台机器共用同一份记忆。

**一个面向 [ReMe](https://github.com/agentscope-ai/ReMe) 的 Windows 托盘应用。** 它负责选择并生成 ReMe 的配置、运行服务，
以及把 Agent 客户端——Windows 上的 Codex、虚拟机里的 Codex、DeepSeek Harness——接到同一个 ReMe 实例、同一份 workspace 上。

## 它配置什么

ReMe 的行为来自 YAML：哪些 job 开、按什么计划跑、用哪个模型与 Embedding 端点。本工具用窗口把这些配置写出来，不必手改文件。

- **三种模式** —— 基础 / 全功能 / 自定义。模式由生成文件的内容推导，不会和实际运行的东西不一致。
- **Job 白名单** —— 写入 `service.jobs`，并逐项核对你这份 ReMe 里真实存在的 job（名字不存在会让 ReMe 启动失败）。
- **LLM 与 Embedding** —— 端点、模型、Key、token 预算、思考强度、Embedding 维度、整理计划。Key 进 `.env`，其余进生成的配置。
- **连接测试** —— 发一个真实请求，验证模型能按要求输出结构化 JSON（`auto_memory` / `auto_dream` 依赖它）；Embedding 测试要求近义句相似度高于无关句。
- **服务控制** —— 启动、停止、重启、查看状态，都在托盘里。
- **VM 隧道** —— 命名的 SSH 反向隧道目标，各自独立的 VM 端口，让 VM 访问同一个 ReMe 实例。掉线会自动接回；你停掉的不再被拉起。
- **生成的配置先校验再落盘**，改动失败会回滚。

## 它接入什么

| 客户端 | 接入方式 |
|---|---|
| Codex（Windows） | MCP server 配置 + 一个自动记录对话的生命周期 hook |
| Codex（虚拟机内） | 同上，走反向隧道，端点指向隧道端口 |
| DeepSeek Harness | ReMe 官方 DSH 插件，另加 MCP 客户端配置以获得写记忆能力 |

三者的一步步做法随应用分发——可以在窗口里阅读，也可以复制（会自动附上 Codex 捕获脚本）后整份交给一个能改本机文件的 Agent。

## 开始使用

1. 从 [Releases](../../releases) 下载 `reme-helper-<版本>-windows-x64.zip`，解压到任意目录。
2. 运行 `reme-helper-<版本>.exe`。它常驻托盘，双击图标打开控制台。
3. 如果没检测到 ReMe：点 **复制安装提示词** 交给 Agent 安装，然后指定 ReMe 目录——或点 **扫描** 自动查找。
4. 填好 LLM 与 Embedding 端点，点 **测试**，再点 **验证并保存**。
5. 接入 Agent 客户端：点 **阅读接入文档**（或 **复制接入文档**）照着做。

> [!IMPORTANT]
> Agent 要能用记忆，ReMe 必须在运行。本工具负责这件事，但它不安装 ReMe 本身——那是安装提示词与 **扫描** 的用途。

## Skill 安装

Skill 只从一个位置读取。把 skill 装到 `~/.agents/skills/<名字>/`，Codex、DeepSeek Harness 以及遵循同一约定的其他 Agent 都能用；
**不要再往 `~/.codex/skills/` 复制一份**，那会让同一个 skill 被加载两次：

```text
~/.agents/skills/<名字>/SKILL.md      用户级规范位置
```

本应用本身不是 skill，解压 zip 即可使用，无需额外安装。

## 三种模式

| 模式 | 配置文件 | 开启的能力 |
|---|---|---|
| 基础模式 | `config/app.yaml` | Markdown 读写、BM25、Wikilink、Studio、MCP、索引维护；不调用模型 |
| 全功能模式 | `config/app-full.yaml` | ReMe 官方默认全开：Auto Memory、Auto Resource、Auto Dream、内部 Chat；需要 LLM 凭据 |
| 自定义模式 | `config/app-custom.yaml` | 逐项选择：自动记忆、Claude Code 入口、资料处理、Dream、Proactive、Chat、Embedding、FAISS、Studio、MCP |

切换模式只换能力集——地址、模型、Key、各项参数属于公共设置，不会被清空。在固定预设下改动某一项能力会转为自定义模式，并且只应用这一项改动。

## 仓库结构

```
src/          应用源码（main.py、i18n.py、guide.py）
tests/        测试脚本——全部是构建门禁；conftest.py 负责把 src/ 加进 sys.path
scripts/      build.bat（真正的构建脚本）与 make_release_config.py
doc/          文档，按语言分：doc/zh/ 与 doc/en/ 下各有 setup.md（接入）与 configuration.md（配置参考）；
              doc/capture.mjs 是 Codex 捕获脚本。
              运行时由应用读取这个目录，所以它会随发布包一起分发。
.github/      CI：每次推送跑测试；打 v* 标签时构建并发布
build.bat     薄包装 → scripts/build.bat
release.bat   打 v<版本> 标签并推送 → 由 CI 构建发布
```

运行期产物既不进源码目录，也不进发布包：

```
log/                       跑一次留下的诊断（smoke / ui-check / release / lang-audit）
                           与 log/tests/<套件>.log——都是跑完即弃
.cache/                    PyInstaller 中间物、按需创建的构建 venv、spec 文件
release/reme-helper-<版本>/  构建出来的发布包（发布 zip 就是这个目录）
%LOCALAPPDATA%/reme-helper/log/reme-helper.log   应用自己的日志，1MB 滚动、保留 3 份备份
                                                 ——属于用户数据，不在包里
```

## 从源码构建

```bat
build.bat                  :: 测试 + 图标 + 打包 + 校验，然后启动新版本
build.bat release          :: 同上，另加打包版 --release 门禁
build.bat norun            :: 只构建，不启动
build.bat clean --force    :: 清掉构建缓存与已构建的发布目录
release.bat                :: 打 v<版本> 标签并推送，由 CI 产出 zip
```

版本号只写在 `src/main.py` 的 `VERSION` 里——应用、发布目录名、git 标签都从它来。构建时若还有任何 `reme-helper*.exe` 在运行会直接拒绝（文件被占用、两个托盘抢一份配置）；每个测试脚本都是门禁；产物写到 `release/reme-helper-<版本>/`。找不到 PyInstaller 时会在 `.cache/venv` 建一个隔离环境并安装 `requirements.txt`，所以干净机器只要有 Python 就能构建。

每次构建都会对**冻结后的产物**做校验：`--smoke`（配置形状、生成的配置、随包文档）、`--ui-check`（设置窗口真的建得出来）、`--make-icon`（排除 numpy 与 PIL 编解码器后托盘图标仍能生成）；带 `release` 时再加 `--release`（冻结环境、出厂配置干净、图标与托盘菜单能构造、此刻没有别的实例在跑）。

## 数据边界

应用的配置在 exe 旁边，日志在用户数据目录。记忆数据仍在 ReMe 的 workspace——删除 reme-helper 不会删除记忆。退出工具会停止由它启动的 ReMe 进程与 SSH 隧道。发布包里的配置由出厂默认值生成，并由 `scripts/make_release_config.py` 按白名单校验：以后谁往默认值里加了个人数据，构建会直接失败，而不是悄悄发出去。

## 许可证

[MIT](LICENSE) © 2026 KenneLu

更新记录：[CHANGELOG.md](CHANGELOG.md) · 配置参考：[doc/zh/configuration.md](doc/zh/configuration.md)
