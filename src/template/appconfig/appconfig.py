# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/template/appconfig/appconfig.py | TEMPLATE-VER: 1.0.0
# TEMPLATE-LOCAL-OVERRIDE: VERSION 不入此文件（单一事实源在 main.py，D15/D16）；
#   ICON_DRAW 不启用（图标绘制留在 main.py，运行态着色与构建期静态不同构，W-f 申报）。
"""reme-helper 参数区（T1：拷贝后唯一允许修改的文件）。"""
APP_ID = "reme-helper"
APP_NAME = "ReMe 助手"

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
