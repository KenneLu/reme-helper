# -*- coding: utf-8 -*-
"""reme-helper 参数卡：kit 出厂默认值由 template.appconfig 提供，本文件覆盖工具差异。

本文件由工具自持（在 src/template 借条之外），template.appconfig 运行时
`try: import app_params` 读取覆盖；未写的键保留 kit 出厂默认值。
VERSION 不入卡：单一事实源在 src/main.py（scripts/build.bat / release.bat 读取）。
"""
APP_ID = "reme-helper"
APP_NAME = "ReMe 助手"
# W4（autostart 1.2.0）：Run 键名沿用存量 APP_ID（D3 方案 A——APP_NAME 是中文展示名，
# 注册表键名须 ASCII；历史键即 reme-helper，改名 = 断链）。
AUTOSTART_KEY = APP_ID

REPO_OWNER = "KenneLu"
REPO_NAME = "reme-helper"
EXE_NAME = "reme-helper.exe"

# 本助手**适配**的 ReMe 版本（用户 2026-09-19 定：不再跟随 PyPI 最新）。
#
# 为什么固定：助手要生成三份配置、内省思考强度档位、核对 MCP 工具白名单——这些都依赖
# 目标版本 default.yaml 的 job 表与依赖 pin（当前 pin 对应 agentscope==2.0.10）。上游
# 一发新版就引导用户升，等于让"生成配置 / 白名单"跑在未验证的组合上。
#
# 单点定义：安装提示词、升级提示词、检查更新的四象限判定、界面提示全部读这里；换适配
# 版本只改这一行。升级目标**恒为**它，PyPI 上更新的版本永远不会成为升级目标。
#
# 专有键：kit 参数卡（template/appconfig/appconfig.py）不覆盖本键——kit 是通用共享库，
# 不知道任何工具的目标版本；本键只属于 reme-helper，故由本卡持有。main.py 经
# `from app_params import SUPPORTED_REME_VERSION` 取用（单一真源），冻结环境同样生效。
#
# 推进历史：0.4.1.13（1.2.8）适配了 job 改名 `proactive` → `proactive_read`、新增
# `list_tags`、`proactive_refresh` 的 `enable_serve: false` 判定与 agentscope==2.0.9 pin。
# 2026-10-27 发布的 0.4.2.1 已逐字复核：job 表完全一致（无新增/删除/改名），仅增量字段
# 变化（`watch_mode: awatch`、`auto_memory.request_id`、`daily_list` 日期范围/分页、
# `search.min_score` 描述、注释掉的 `as_decision_model`），故 EXPOSE 白名单逻辑无需改动，
# pin 推进到 0.4.2.1；0.4.2.1 的 pyproject 把 agentscope 钉到 2.0.10（main.py 的
# AGENTSCOPE_PIN_FALLBACK 同步）。
SUPPORTED_REME_VERSION = "0.4.2.1"

# W6 状态贴图：4 形态全量图（D6）。绘制器在构建侧 src/icon_pipeline.py（与 main.py
# 归一后零共享——运行时 tray_icons 只按档加载，包内零绘制代码）。
import icon_pipeline as _ip
ICON_DRAW = _ip.make_taskbar_icon
ICON_ASSET = None   # 手工资产派生不启用（B 方案：全代码绘制）
ICON_STATE_ARTISTS = {
    "ok": lambda base: _ip.make_icon(True, False, 256),
    "ok_tunnel": lambda base: _ip.make_icon(True, True, 256),
    "down": lambda base: _ip.make_icon(False, False, 256),
    "down_tunnel": lambda base: _ip.make_icon(False, True, 256),
}
