# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/template/appconfig/appconfig.py | TEMPLATE-VER: 1.0.0
# TEMPLATE-LOCAL-OVERRIDE: VERSION 不入此文件（单一事实源在 main.py，D15/D16）；
#   W6 起 ICON_DRAW 启用（绘制挪构建侧 src/icon_pipeline.py，运行时零绘制）。
"""reme-helper 参数区（T1：拷贝后唯一允许修改的文件）。"""
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
# 目标版本 default.yaml 的 job 表与依赖 pin（如 agentscope==2.0.7.post1）。上游一发新版
# 就引导用户升，等于让"生成配置 / 白名单"跑在未验证的组合上。
#
# 单点定义：安装提示词、升级提示词、检查更新的四象限判定、界面提示全部读这里；换适配
# 版本只改这一行。升级目标**恒为**它，PyPI 上更新的版本永远不会成为升级目标。
SUPPORTED_REME_VERSION = "0.4.1.11"

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

