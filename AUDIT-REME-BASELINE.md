# 四工具公共组件分歧审计（以 reme-helper 为基准）

> 用户口径（2026-09-19）：解决分歧时**以 reme-helper 为标准**，除非有更好的兼容方式
> （那可以连 reme-helper 一起优化）。
>
> 判定口径（STANDARDS B4 两条前提）：允许不一致只有两种情形——**业务冲突**（前提是**双方都有**该功能）
> 或**更好方案**（须给可验证理由）；两者都附带义务：**评估模板能否吸收该差异**。
> **"没有功能"不构成冲突，那是「缺失」，必须补齐**；`TEMPLATE-LOCAL-OVERRIDE` 是留痕，不是豁免。

本文件是审计结论的**本仓留档**。`ALIGNMENT.md` 属 `my-diy-tool-template` 仓库（非本仓职责范围），
合并由模板守护者执行；内容以下表为准。

## 一、判定表

| # | 分歧点 | 分类 | 依据（可验证） | 谁改 | 模板能否吸收（结论+理由） |
|---|---|---|---|---|---|
| 1 | i18n **状态表示法** | **一致** | 模板 i18n 2.1.1 `__init__` 不复制状态（`from . import i18n` + PEP 562 `__getattr__`）并加 `current_lang()`；l-s2t/dsh 均 2.1.1 | 无（l-s2t `main.py:310/375` 建议改用 `current_lang()`，非阻塞） | **已吸收**：reme 的原则（状态用参数/访问器，不做外部可读可变全局） |
| 2 | i18n **形态**（中文即键 + `pairs.json` + 片段替换 ↔ 键名 + `zh/en.json`） | **业务冲突**（非"更好方案"） | reme `--lang-audit` 实测 **826 条**词对；模板 README / STANDARDS §E4 明示重形态适用百条级；轻形态工具各自门禁全绿 | reme 保留（已 OVERRIDE 申报） | **部分已吸收**（状态原则，见 #1）。**形态差异不吸收**：① 拷贝式模板下，每个工具都会背上中文即键表 + 片段引擎 + AST 全树扫描，而轻形态工具没有这个数据量；② §E4 已把轻/重定义为**数据格式分叉**，合并等于取消该分叉；③ `pairs.json`（`[zh,en]` 对）与模板 `zh/en.json`（键值表）**schema 不同**，合表需改四工具词表。**可吸收的替代**：把 reme 的 AST 覆盖率审计做成**可选门禁件** |
| 3 | **ocx 无 i18n** | **缺失**（T1 成立） | `opencodex-helper` 远端 = `https://github.com/KenneLu/opencodex-helper.git`（公开）；`src/template/` 无 i18n；`main.py` 中文文案 **115 条（去重 108）** | ocx 必须补齐 | 模板 `template/i18n` 2.1.1 已在；无需吸收 |
| 4 | 托盘**菜单开着时的重建推迟** | **缺失** | `grep -c "MenuSignature\|menu_is_open"`：dsh = **0**、ocx = **0**（l-s2t 用模板件；reme 有内联等价） | dsh/ocx 必须补齐 | **已吸收**：模板 `tray_kit.MenuSignature` 即 reme 机制的接口化 |
| 5 | 退出确认 + 清理勾选 | **一致** | 四家同语义；三家直接调 `tray_kit.confirm_quit_dialog`；模板 2.0.2 已含 i18n 参数化 | reme 可选迁移去重（内联 duplicated，低优先） | **已吸收** |
| 6 | 服务唯一性 / 接入 / **有界清理** | **缺失**（ocx 另有**违规**） | 四家均未消费 `service_link`（reme 文件夹在但全仓库 0 import；dsh/ocx 无模块）；**ocx `main.py:238 kill_target_procs` 按命令行签名击杀，违 G4.2-3** | 四家补齐；ocx 违规单独登记、最急 | 模板模块已在；无需吸收 |
| 7 | 路径与数据区 / 日志 | **一致** | 四方 `paths` 1.1.3、`log_kit` 1.0.2；env 名统一 `*_DATA_DIR` / `*_CONFIG` | — | 已吸收 |
| 8 | **autostart** | **缺失（reme 侧）** | 模板 1.1.1 在；reme 内联（`APP_ID` 键 + `sync_autostart_path`）且**无稳定安装位、无 `migrate_autostart` 自愈**；l-s2t/dsh/ocx 已采纳 | reme 必须补齐 | 模板已在（G4.1 明示其形态更优）；无需吸收。**迁移注意**：`APP_ID`→`APP_NAME` 键名变更会让存量自启项失联，须自带迁移 |
| 9 | **icons** | **缺失** | 模板 `icons` 2.0.0 在；reme/dsh/ocx 无 `src/template/icons/`；l-s2t 为 `src/icons.py` 未包化 | 各工具补齐 | 模板已在；无需吸收 |
| 10 | **update_helper** | **缺失** | 模板 1.0.1 在；reme 内联 bespoke（bat + `_backup` + `update.log`，含 sha256 校验）；l-s2t 用 `updater.py` 未采纳 | reme 补；l-s2t 收敛 | 模板 `target_dir=INSTALL_DIR` 已覆盖 l-s2t 形态；**reme 的 bat+备份策略是否吸收进模板待评估** |

**统计**：一致 3 · 缺失 6 · 业务冲突 1 · 更好方案 0。

## 二、状态表示法专节（模块级可变全局 × 外部读取）

| 模块.全局 | 外部读取点 | 风险 | 处置 |
|---|---|---|---|
| `i18n.LANG`（轻形态） | **l-s2t `main.py:310/375`**；dsh 无外部读 | 2.1.1 前：`from .i18n import *` 把 `LANG` 拷成**死副本** → 切语言菜单签名不变、**静默不刷新**（已实证）；2.1.1 后经 `__getattr__` 实时 | **A 照 reme 原则**：l-s2t 两处改用 `current_lang()` |
| `update_helper.UPDATE_READY` / `PENDING_CMD` | dsh/ocx `main.py` 经 `update_helper.X` 读 | 低：模块属性查找实时，**不是副本** | 可保留；若要严守原则，加 accessor（低优先） |
| `log_kit._logger` / `tray_kit._MUTEX_HANDLE` | 无 | 低：私有 + 函数管理 | 保留 |
| `paths.*` / `appconfig.*` | 多处 | 无：常量不可变 | 保留 |
| reme i18n | **无任何模块级可变全局** | 结构性免疫 | 作为标准 |

## 三、缺口行动清单

| 工具 | 缺口 |
|---|---|
| reme | `autostart`、`icons`、`update_helper` 采纳；`service_link` 接线 |
| dsh | `MenuSignature`；`service_link`；`icons` |
| ocx | **i18n（T1）**；`MenuSignature`；`service_link`（+ 签名击杀违规）；`icons` |
| l-s2t | `icons` 包化采纳（`src/icons.py` → `template/icons/`） |

## 四、reme 侧缺口的工作量 / 风险评估（本轮不做）

| 缺口项 | 工作量 | 风险 | 关键点 |
|---|---|---|---|
| `autostart` | 中 | 高（用户可见"开机自启"） | 键名迁移 + 稳定安装位是前置（G4.1 未决）；裸换会静默断链 |
| `icons` | 高 | 中 | 需拆分运行态着色与构建期 `ICON_DRAW`，保留 15 档任务栏帧表；13 处测试引用跟随 |
| `update_helper` | 高 | 高（自更新关键路径） | 现链为 bat 替换 + `_backup` + `update.log`，与模板"apply.cmd + PENDING_CMD"不同；换链须重跑零中断更新回归 |
| `service_link` 接线 | 中 | 中 | ADOPTED 优雅关闭分支（REVIEW #8）；需 mock 回调 + `_DATA_DIR` 隔离测试 |

## 五、模板侧吸收评估（义务项汇总）

需模板侧动作的仅 2 条：
1. i18n 的 **AST 覆盖率审计脚本** → 作为可选门禁件；
2. reme 更新链 **bat+备份策略**的接口化评估（若模板 `apply.cmd` 已覆盖则无需吸收）。

其余 14 处**模板均已具备**，属工具侧"补采纳"，不是"改模板"。
