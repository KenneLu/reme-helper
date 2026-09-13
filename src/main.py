#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReMe helper: Windows tray process, mode, configuration, and VM tunnel manager."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import messagebox as _raw_messagebox
import i18n
import guide

import psutil
import pystray
import yaml
from PIL import Image, ImageDraw, ImageFont


APP_NAME = "ReMe 助手"
APP_ID = "reme-helper"
VERSION = "1.0.14"
# 四个位置，别混在一起：
#   APP_DIR     运行时目录——打包后是 exe 所在目录，开发时是本文件所在的 src/。
#               **只放程序本身**：用户数据（配置、日志）都不在这儿。
#   RUN_DIR     分发包目录——打包态是 exe 旁边，开发态是仓库根。静态资源（doc/、图标）
#               与「跑一次就丢」的诊断输出（smoke / ui-check / release / lang-audit）走这里。
#   APP_LOG_DIR 应用自己的日志，属于用户数据：%LOCALAPPDATA%\reme-helper\log\。
#               放包里的后果很实际——应用正在跑时日志被占用，构建就没法把 release 目录
#               清干净（实测 rmdir 直接失败），发布包里会一直挂着一个 log/。
#   CONFIG_PATH 机器相关的可写状态，也属于用户数据：%LOCALAPPDATA%\reme-helper\config.json。
#               理由与日志一样，外加更要紧的一条：**原地更新要能整目录替换**，配置若住在
#               exe 旁边，updater 就得为它写例外。
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PACKAGE_DIR = APP_DIR if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
RUN_DIR = APP_DIR if getattr(sys, "frozen", False) else PACKAGE_DIR
LOCAL_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
                      or Path.home() / ".local" / "share") / APP_ID
# config.json 以前住在 APP_DIR；旧位置只在首次播种/迁移时读一次（见 seed_config）。
LEGACY_CONFIG_PATH = APP_DIR / "config.json"
# REME_HELPER_CONFIG 是显式覆盖，给测试与便携用：打包自检靠它去读发布包里的**出厂模板**，
# 否则它会读到开发机上的活配置（那样 --release 的断言必然失败）。
CONFIG_PATH = (Path(os.environ["REME_HELPER_CONFIG"]).expanduser()
               if os.environ.get("REME_HELPER_CONFIG")
               else LOCAL_DATA_DIR / "config.json")
# 诊断输出跟着「这次运行的那个包」走：构建脚本就在 %RELEASE_DIR%\log\ 里读它、清它。
DIAG_LOG_DIR = RUN_DIR / "log"
RUN_LOG_DIR = DIAG_LOG_DIR
APP_LOG_DIR = LOCAL_DATA_DIR / "log"
LOG_DIR = APP_LOG_DIR
LOG_PATH = LOG_DIR / "reme-helper.log"
# `--quit` 的请求文件：`reme-helper --quit` 写它，运行中的实例在 quit_watch_loop 里发现后
# 删掉它并走正常的退出路径。用文件而不是命名事件：零 Win32 句柄管理，且天然幂等。
QUIT_REQUEST_PATH = LOCAL_DATA_DIR / "quit.request"
# exe 与窗口共用的图标：由 --make-icon 用托盘那套画法生成，构建时喂给 PyInstaller。
ICON_PATH = RUN_DIR / f"{APP_ID}.ico"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_REME_ROOT = r"H:\Tools\ReMe"
MODE_NAMES = {"minimal": "基础模式", "full": "全功能模式", "custom": "自定义模式"}
MODE_ORDER = ("minimal", "full", "custom")
MODE_SUBTITLE = {
    "minimal": "不调用模型；手动写记忆，关键词检索",
    "full": "自动整理记忆；需在【LLM 与模型】填 Key",
    "custom": "按需挑选能力（官方默认 + 你的选择）",
}
MODE_NOTE = "前两项是固定预设：改动其中任意一项，会自动转为自定义模式（可撤销）。"
CRON_PRESETS = (
    ("0 23 * * *", "每天 23:00（默认）"),
    ("0 3 * * *", "每天 03:00"),
    ("0 12 * * *", "每天 12:00"),
)
SCAN_DAY_CHOICES = (1, 2, 3, 7)
MAX_UNIT_CHOICES = (3, 5, 10)
# reasoning_effort 的档位（值发给模型，标签给人看）。
# 合法集合不是照抄某个客户端，而是由「ReMe 实际用的 agentscope 模型类」决定：
# openai 收 none/minimal/low/medium/high/xhigh，deepseek 只收 high/max，
# anthropic 收 low/medium/high/xhigh/max，xai 只收 low/medium/high。
# 这里只列「界面上可能出现的档位」；具体出现哪几个由能力层算（见 effort_options）。
# ultra 不在任何 backend 的集合里，已移除。
EFFORT_CHOICES = (
    ("", "不设置"),
    ("none", "关闭"),
    ("minimal", "最小"),
    ("low", "低"),
    ("medium", "中"),
    ("high", "高"),
    ("xhigh", "极高"),
    ("max", "最大"),
)
EFFORT_LABELS = {value: label for value, label in EFFORT_CHOICES}
EFFORT_VALUES = {label: value for value, label in EFFORT_CHOICES}

# effort_options() 的原因码 → 给用户看的一句话。写在界面上，让人知道档位是怎么来的。
EFFORT_REASON_NOTES = {
    "backend_none": "该后台没有 reasoning_effort 参数，无需设置。",
    "backend_only": "端点未提供模型能力信息，这里按本机 ReMe 的合法集合显示。",
    "model_declared": "端点声明该模型支持：",
}
# 端点声明只是参考：实测那份元数据两个方向都会错，所以不能拿它禁用档位
EFFORT_DECLARED_SUFFIX = "（仅供参考；可选项以本机 ReMe 的合法集合为准）"
GLOSSARY = {
    "LLM": "负责“写与整理记忆”的模型：把对话提炼成卡片、把卡片沉淀成长期记忆。需要在【LLM 与模型】里填地址与 API Key。",
    "Embedding": "负责“按意思找”的检索模型：忘了原词也能搜到（搜“打包没反应”能命中“构建卡死”）。与 LLM 分开配置，通常不是同一个服务。",
    "token": "模型的计费单位，约等于字数。开启带模型的能力后，按实际用量计费。",
    "cron": "定时表达式，五个字段依次是 分 时 日 月 周。例如 0 23 * * * 表示每天 23:00。",
    "effort": "思考强度（reasoning_effort）：档位越高，模型在回答前思考得越久，也越费 token。"
              "可选档位不是照抄某个客户端：先取本机 ReMe 使用的 agentscope 模型类接受的集合，"
              "再与该模型声明的档位取交集；写出集合外的值会让服务在启动时直接失败。"
              "不确定时保持“不设置”。",
    "scan_days": "扫描范围：从今天往回数 N 个 daily 目录，ReMe 官方默认 2 天。\n"
                 "先说结论：调大 ≠ 记得更准，越大越慢越贵。\n"
                 "机制：内容没变的日记本来就不会被抽取（按 mtime 比对），整个窗口都没变化时这次整理直接跳过、不花钱；"
                 "但窗口越大，只要其中任意一天有变化，这次抽取就要把窗口里所有变化一起读进去——输入更大、更慢更贵，"
                 "还会把早已沉淀过的旧内容再提一遍。\n"
                 "建议：日常保持 2；刚补录了一批旧日记、或连着几天没开机时临时调到 3–7，扫完调回 2。",
    "max_units": "一次整理最多产出几个长期节点（unit），ReMe 官方默认 5。\n"
                 "先说结论：调大 ≠ 记忆更好，只是把一次运行拉长、账单变高。\n"
                 "机制：每个 unit 都要单独调一次模型把它融合进 digest，所以一次整理的费用与耗时 ≈ 1 次抽取 + N 次融合"
                 "（N 是实际产出的 unit 数，上限就是这里）；写得多也意味着更次要的内容会被一起沉淀进去。\n"
                 "建议：日常 3–5；首次补历史可以临时调到 10，补完调回 5。",
}
CRON_RE = re.compile(r"^\s*\S+(\s+\S+){4}\s*$")
# ---------------- MCP 暴露允许列表 ----------------
# 白名单里的名字必须**逐字**等于 ReMe 真实注册的 job 名。base_service.add_jobs() 会先做
# self.jobs.difference(app.context.jobs)，有一个对不上就 raise KeyError，服务直接起不来；
# 加不进去的 job 则是 raise TypeError。而官方的「功能名」和「job 名」并不一致——功能叫
# proactive_read，对应的 job 叫 proactive——所以这里绝不手抄名单：候选一律由
# servable_job_names() 从官方 default.yaml 推导，写盘前再按这份配置真正产出的 job 表过滤。
EXPOSE_JOB_GROUPS = (
    ("记忆读写", ("read", "write", "edit", "save", "load", "daily_write", "read_image",
                  "frontmatter_read", "frontmatter_update", "frontmatter_delete")),
    ("检索与浏览", ("search", "node_search", "traverse", "graph_snapshot",
                    "list", "stat", "daily_list")),
    ("索引与维护", ("reindex", "daily_reindex", "move", "delete")),
    ("自动记忆", ("auto_memory", "auto_memory_cc", "auto_dream", "auto_resource",
                  "proactive", "chat")),
    ("服务信息", ("health_check", "status", "version", "help", "app_config")),
)
EXPOSE_JOB_LABELS = {
    "read": "read（读一个记忆文件）",
    "write": "write（新建记忆文件）",
    "edit": "edit（精确替换记忆内容）",
    "save": "save（整份覆盖保存）",
    "load": "load（整份载入文件）",
    "daily_write": "daily_write（写当天的卡片）",
    "read_image": "read_image（读图片，需视觉模型）",
    "frontmatter_read": "frontmatter_read（读文件头字段）",
    "frontmatter_update": "frontmatter_update（改文件头字段）",
    "frontmatter_delete": "frontmatter_delete（删文件头字段）",
    "search": "search（关键词 / 语义检索）",
    "node_search": "node_search（按节点检索）",
    "traverse": "traverse（沿关系图遍历）",
    "graph_snapshot": "graph_snapshot（导出关系图快照）",
    "list": "list（列目录）",
    "stat": "stat（看文件元信息）",
    "daily_list": "daily_list（列 daily 卡片）",
    "reindex": "reindex（重建检索索引）",
    "daily_reindex": "daily_reindex（重建 daily 索引）",
    "move": "move（移动记忆文件）",
    "delete": "delete（删除记忆文件）",
    "auto_memory": "auto_memory（把对话提炼成记忆）",
    "auto_memory_cc": "auto_memory_cc（从 Claude Code 会话提炼）",
    "auto_dream": "auto_dream（立刻整理成长期记忆）",
    "auto_resource": "auto_resource（把资料转成卡片）",
    "proactive": "proactive（读当天的兴趣主题）",
    "chat": "chat（对话，仅 HTTP / SSE）",
    "health_check": "health_check（健康检查）",
    "status": "status（服务状态）",
    "version": "version（版本号）",
    "help": "help（列出全部 Job）",
    "app_config": "app_config（导出生效配置，密钥已脱敏）",
}
# 默认不勾的理由只有两类：会改动 / 删除已有记忆，或代价明显（重建索引）。
# health_check 与 status 必须默认勾上——helper 自己的健康探测打的就是 /health_check，
# 官方 DSH 插件的状态卡片读的也是这两个，漏掉它们会让人以为服务挂了。
EXPOSE_DEFAULT_OFF = ("delete", "move", "frontmatter_delete", "reindex", "daily_reindex")
# 官方 default.yaml 读不到时的兜底（正常安装不会走到）：只用来建界面，写盘前一定再过滤。
EXPOSE_JOBS_FALLBACK = tuple(job for _group, jobs in EXPOSE_JOB_GROUPS for job in jobs)
EXPOSE_DEFAULT_FALLBACK = tuple(job for job in EXPOSE_JOBS_FALLBACK
                                if job not in EXPOSE_DEFAULT_OFF)

# 每项的等级与说明。等级只用来给提示和「只勾推荐」分组，**不影响能不能勾**——
# 判断依据是「不勾会不会让谁坏掉」和「勾了会不会改删数据」，不是抽象的好坏。
EXPOSE_TIER_ORDER = ("必留", "推荐", "可选", "慎开")
# 等级 → 主题色键：必留=必须留（蓝）、推荐=绿、可选=灰、慎开=琥珀。
EXPOSE_TIER_COLORS = {"必留": "link", "推荐": "ok", "可选": "muted", "慎开": "warn"}
EXPOSE_JOB_INFO = {
    "health_check": ("必留", "健康检查。ReMe 助手自己的「服务」状态探测、DSH 插件的状态卡片读的就是它，"
                             "不勾会让两边都显示成服务没起来。"),
    "status": ("必留", "服务状态。同上：助手与 DSH 插件都靠它判断服务是否在跑。"),
    "read": ("推荐", "读取一个记忆文件的内容。外部 Agent 回忆时的基本动作。"),
    "write": ("推荐", "新建一个记忆文件。精确写入的前提，通常和 edit 配对使用。"),
    "edit": ("推荐", "精确替换记忆文件里的内容。比整份覆盖安全，建议保留。"),
    "search": ("推荐", "关键词 / 语义检索。回忆的入口。"),
    "traverse": ("推荐", "沿关系图（[[链接]]）遍历相关记忆，从一条记忆找到关联的其它记忆。"),
    "list": ("推荐", "列出目录内容，用来发现有哪些记忆文件。"),
    "stat": ("推荐", "看一个文件的元信息（大小、修改时间等），不改内容。"),
    "save": ("可选", "整份覆盖保存文件。用传入内容替换整个文件，比 edit 粗放。"),
    "load": ("可选", "整份载入文件内容，read 的变体，一次把文件全部读出来。"),
    "daily_write": ("可选", "写当天的 daily 卡片，也就是对话记忆的落地形式。"),
    "read_image": ("可选", "读取图片内容。没配视觉模型时没有意义。"),
    "frontmatter_read": ("可选", "读取文件头（--- 之间的字段，例如 tags、title）。"),
    "frontmatter_update": ("可选", "修改文件头字段，不动正文。"),
    "node_search": ("可选", "按节点（沉淀后的长期记忆单元）检索，比全文检索更聚焦。"),
    "graph_snapshot": ("可选", "导出关系图快照，用于整体查看记忆之间的连接。"),
    "daily_list": ("可选", "列出所有 daily 卡片。"),
    "auto_memory": ("可选", "把一段对话提炼成记忆卡片。DSH 插件的后台工具会调它。"),
    "auto_memory_cc": ("可选", "从 Claude Code 会话提炼记忆。不用 Claude Code 时没有价值。"),
    "auto_dream": ("可选", "立刻把 daily 整理沉淀成长期记忆，相当于手动触发一次「做梦」。"),
    "auto_resource": ("可选", "把 resource 目录里的资料转成卡片。大文件会明显增加 token 与耗时。"),
    "proactive": ("可选", "读当天的兴趣主题（daily/<日期>/interests.yaml）。"),
    "chat": ("可选", "对话入口。只提供 HTTP / SSE 流式接口，不是 MCP 工具。"),
    "version": ("可选", "返回 ReMe 版本号。无副作用，排查问题时有用。"),
    "help": ("可选", "列出全部 Job 及其参数。排查与探索用。"),
    "app_config": ("可选", "导出生效配置。密钥类字段会被脱敏（api_key / token 等显示成 ***）。"),
    "delete": ("慎开", "删除记忆文件。删掉就没了，外部 Agent 一旦被误导会真的删数据。"),
    "move": ("慎开", "移动 / 重命名记忆文件，会改变引用路径。"),
    "frontmatter_delete": ("慎开", "删除文件头字段，属于破坏性修改。"),
    "reindex": ("慎开", "重建检索索引。不改内容，但会明显占用 CPU 与时间。"),
    "daily_reindex": ("慎开", "重建 daily 卡片索引。同上，代价明显。"),
}
EXPOSE_GROUP_NOTES = {
    "记忆读写": "读写记忆文件本身。外部 Agent 的日常动作主要落在这里。",
    "检索与浏览": "把记忆找出来。这一组都是只读的。",
    "索引与维护": "会改动已有数据、或重建索引，默认不勾。",
    "自动记忆": "触发 ReMe 的记忆生产线（提炼、整理、资料转卡）。",
    "服务信息": "服务自身的信息类 Job，无副作用；其中 health_check 与 status 是必留项。",
    "其他 Job": "官方新增、分组表里还没归档的 Job。",
}

# ---------------- 密钥字段 ----------------
# 从配置里读出来的密钥**不放进控件**：控件里存的本来就是真值，星号只是渲染，所以星号
# 数量等于密钥长度——.env 里写着 123，界面上就是 ***，长度直接泄漏。改成填一个定长
# 占位符，长度不再有意义；用户自己敲的照常按真实长度掩码（那是他自己输的）。
KEY_MASK_PLACEHOLDER = "*" * 40


def key_field_untouched(field_text: str) -> bool:
    """用户有没有动过密钥字段（没动过＝还是占位符，或他自己清空了）。"""
    text = (field_text or "").strip()
    return not text or text == KEY_MASK_PLACEHOLDER


def key_field_value(field_text: str, stored: str) -> str:
    """字段当前**代表**的密钥：没动过就用 .env 里存的那份。"""
    return stored if key_field_untouched(field_text) else (field_text or "").strip()

FEATURES = {
    "auto_memory": {
        "name": "Auto Memory",
        "official": True,
        "requires": "LLM",
        "effect": "把对话整理为daily记忆卡片",
        "impact": "每批对话产生模型调用；更及时也更耗token",
    },
    "auto_memory_cc": {
        "name": "Auto Memory CC",
        "official": True,
        "requires": "Claude Code + LLM",
        "effect": "从Claude Code会话生成daily记忆",
        "impact": "不用Claude Code时没有价值；被调用时产生模型费用",
    },
    "auto_resource": {
        "name": "Auto Resource",
        "official": True,
        "requires": "LLM；图像需视觉模型",
        "effect": "监听resource并自动生成资料卡片",
        "impact": "大文件或批量资料可能显著增加token、内存和处理时间",
    },
    "auto_dream": {
        "name": "Auto Dream",
        "official": True,
        "requires": "LLM",
        "effect": "每天把变化的daily提炼、关联和纠正到digest",
        "impact": "抽取一次且每个unit再调用Agent；默认最多5个unit",
    },
    "proactive_read": {
        "name": "Proactive Read",
        "official": True,
        "requires": "已有兴趣主题",
        "effect": "读取已有的主动主题",
        "impact": "读取本身低成本；0.4.1.11默认配置不生成新主题",
    },
    "chat": {
        "name": "ReMe Chat",
        "official": True,
        "requires": "LLM",
        "effect": "提供ReMe内部只读Agent聊天入口",
        "impact": "Codex/DSH已有Agent时通常不需要，会增加模型调用",
    },
    "embedding": {
        "name": "Embedding",
        "official": False,
        "requires": "Embedding模型或API",
        "effect": "增强近义、中英混合和改写召回",
        "impact": "新增/修改和查询需要向量计算；可能产生API费用",
    },
    "faiss": {
        "name": "FAISS HNSW",
        "official": False,
        "requires": "Embedding",
        "effect": "大量向量时加速近邻检索",
        "impact": "增加索引内存和重建时间；小库收益有限",
    },
    "studio": {
        "name": "ReMe Studio",
        "official": True,
        "requires": "reme_studio",
        "effect": "浏览、编辑、搜索和查看运行状态",
        "impact": "少量Web服务开销，不调用LLM",
    },
    "mcp": {
        "name": "MCP Server",
        "official": True,
        "requires": "无",
        "effect": "让Codex和其他MCP客户端使用ReMe工具",
        "impact": "只注册工具；实际成本由调用的Job决定",
    },
}

DEFAULT_CONFIG = {
    "reme_root": DEFAULT_REME_ROOT,
    "mode": "minimal",
    "start_on_launch": False,
    "autostart": False,
    "start_tunnels_with_reme": False,
    "probe_interval_sec": 20,
    "custom": {
        "auto_memory": True,
        "auto_memory_cc": False,
        "auto_resource": False,
        "auto_dream": True,
        "proactive_read": True,
        "chat": False,
        "embedding": False,
        "faiss": False,
        "studio": True,
        "mcp": True,
    },
    "llm": {
        "base_url": "",
        "model": "",
        "max_tokens": 65536,
        "thinking_enable": False,
        "reasoning_effort": "",
        "probe_ok": False,
        "probe_detail": "未测试",
    },
    "embedding": {
        "base_url": "",
        "model": "text-embedding-v4",
        "dimensions": 1024,
        "probe_ok": False,
        "probe_detail": "未测试",
    },
    "pipeline": {
        "scan_days": 2,
        "max_units": 5,
        "dream_cron": "0 23 * * *",
    },
    "expose": {
        "custom": False,
        # 出厂默认＝「默认勾选集」的内置副本；真正的候选名单在运行时由官方 default.yaml 推导
        "jobs": list(EXPOSE_DEFAULT_FALLBACK),
    },
    "targets": [
        {
            "name": "Ubuntu24.04",
            "user": "ubuntu",
            "host": "192.168.1.100",
            "port": 22,
            "key": "",
            "remote_port": 22333,
            "enabled": True,
        }
    ],
}

MINIMAL_FEATURES = {
    "auto_memory": False,
    "auto_memory_cc": False,
    "auto_resource": False,
    "auto_dream": False,
    "proactive_read": False,
    "chat": False,
    "embedding": False,
    "faiss": False,
    "studio": True,
    "mcp": True,
}
FULL_FEATURES = {key: bool(item["official"]) for key, item in FEATURES.items()}
PRESET_LLM = {"max_tokens": 65536, "thinking_enable": False, "reasoning_effort": ""}
PRESET_PIPELINE = {"scan_days": 2, "max_units": 5, "dream_cron": "0 23 * * *"}
PRESET_EMBEDDING = {"model": "text-embedding-v4", "dimensions": 1024}
# 只在读不到 ReMe 生成的 app.yaml 时兜底（比如还没安装 ReMe）。基础模式真正的 job 名单
# 由 existing_job_names() 从 app.yaml 读——那份配置里其实有二十多个 job，不是这五个。
MINIMAL_JOBS = ("search", "read", "write", "edit", "traverse")
FEATURE_GROUPS = (
    ("记忆的产生", ("auto_memory", "auto_memory_cc", "auto_resource", "auto_dream", "proactive_read")),
    ("检索与成本", ("embedding", "faiss")),
    ("界面与接入", ("chat", "studio", "mcp")),
)


def preset_features(mode: str) -> dict:
    if mode == "minimal":
        return dict(MINIMAL_FEATURES)
    return dict(FULL_FEATURES)


# ---------------- 设置窗口状态逻辑（纯函数，可独立测试） ----------------
BASELINE_SAVED = "saved"  # 基线 = 磁盘上已保存的配置（自定义模式打开时的起点）


def settings_new_draft(cfg: dict, root_value: str) -> dict:
    mode = cfg["mode"]
    return {
        "mode": mode,
        "baseline": mode if mode != "custom" else BASELINE_SAVED,
        "features": deep_copy(cfg["custom"]),
        "llm": deep_copy(cfg["llm"]),
        "embedding": deep_copy(cfg["embedding"]),
        "pipeline": deep_copy(cfg["pipeline"]),
        "expose": deep_copy(cfg["expose"]),
        "reme_root": root_value,
    }


def settings_display_features(draft: dict) -> dict:
    """What the checkboxes show: the draft in custom mode, the preset otherwise."""
    if draft["mode"] == "custom":
        return draft["features"]
    return preset_features(draft["mode"])


def settings_load_mode(draft: dict, mode: str, saved_cfg: dict, saved_root: str, saved_mode: str) -> bool:
    """Switch the capability set for `mode`; keep everything the user has filled in.

    Endpoints, model names, keys, dimensions and tuning values are account-level data that
    is valid in every mode, so switching modes must not wipe them — only the capability set
    (which features are on) changes. Returns True when the mode actually changed.
    """
    if mode == draft["mode"]:
        return False
    draft["mode"] = mode
    draft["baseline"] = mode if mode != "custom" else BASELINE_SAVED
    draft["features"] = preset_features(mode) if mode != "custom" else deep_copy(saved_cfg["custom"])
    return True


def settings_baseline_values(draft: dict, saved_cfg: dict) -> dict:
    """Values “回到基线” restores.

    Credentials are deliberately excluded: base URLs, model names and API keys are never
    reset, because they belong to the user's account rather than to a mode.
    """
    baseline = draft.get("baseline", BASELINE_SAVED)
    if baseline == BASELINE_SAVED:
        return {
            "features": deep_copy(saved_cfg["custom"]),
            "llm_params": dict(PRESET_LLM),
            "embedding_space": dict(PRESET_EMBEDDING),
            "pipeline": deep_copy(saved_cfg["pipeline"]),
            "expose": deep_copy(saved_cfg["expose"]),
        }
    return {
        "features": preset_features(baseline),
        "llm_params": dict(PRESET_LLM),
        "embedding_space": dict(PRESET_EMBEDDING),
        "pipeline": dict(PRESET_PIPELINE),
        "expose": {"custom": False, "jobs": list(EXPOSE_DEFAULT_FALLBACK)},
    }


def settings_baseline_label(draft: dict) -> str:
    baseline = draft.get("baseline", BASELINE_SAVED)
    if baseline == BASELINE_SAVED:
        return "已保存配置"
    return MODE_NAMES.get(baseline, baseline)


def settings_matches_preset(draft: dict, mode: str) -> bool:
    """模式身份 = **能力集合**（哪些功能与后台 Job 开着），公共设置不参与判断。

    以前这里把 token 预算、思考强度、Embedding 维度/模型、整理参数、MCP 允许列表一起比，
    结果是「在全功能模式下只调了个思考强度」也被判定与预设不同而降级为自定义——用户无法预期。
    这些参数与地址/模型/Key 一样属于**公共设置**：在哪个模式下都成立，改它们不该改变模式。
    """
    features = draft.get("features") or {}
    preset = preset_features(mode)
    return all(bool(features.get(key)) == bool(preset[key]) for key in FEATURES)


def settings_collapse_mode(draft: dict) -> str | None:
    """Mode is derived from the values: if the draft equals a preset, that IS the mode.

    Returns the collapsed mode name, or None when the draft is a genuine custom set.
    """
    if draft["mode"] != "custom":
        return None
    for mode in ("minimal", "full"):
        if settings_matches_preset(draft, mode):
            draft["mode"] = mode
            draft["baseline"] = mode
            return mode
    return None


def settings_materialize_display(draft: dict) -> None:
    """Make the draft mirror what the window currently shows for a fixed preset.

    The window is the source of truth while editing (the UI collects widget values before
    every change); this helper exists so tests and other callers can reproduce that state
    without a window.
    """
    if draft["mode"] == "custom":
        return
    draft["features"] = preset_features(draft["mode"])
    draft["pipeline"] = dict(PRESET_PIPELINE)
    draft["expose"] = {"custom": False, "jobs": list(EXPOSE_DEFAULT_FALLBACK)}


def settings_apply_edit(draft: dict, section: str, key: str, value,
                        saved_cfg: dict) -> tuple[bool, str | None]:
    """Apply one edit.

    The caller must first make the draft mirror the window (the UI collects every widget
    value, so text the user just typed is preserved and never overwritten by a stale copy).

    Returns (degraded_to_custom, collapsed_mode): a fixed preset degrades to custom, and a
    custom draft that becomes identical to a preset collapses back to that preset so the
    mode label always matches the content.
    """
    degraded = False
    if draft["mode"] != "custom" and section == "feature":
        # 只有改「能力项」才离开固定预设；改参数/凭据/整理参数/MCP 允许列表都留在预设里
        # （保留下当前显示/刚输入的值，用磁盘旧值覆盖是不行的）
        previous = draft["mode"]
        draft["mode"] = "custom"
        draft["baseline"] = previous
        degraded = True
    if section == "feature":
        draft["features"][key] = bool(value)
        if key == "embedding" and not value:
            draft["features"]["faiss"] = False  # FAISS 依赖 Embedding
    elif section in ("llm", "embedding", "pipeline"):
        draft[section][key] = value
        if section == "llm" and key in ("base_url", "model", "thinking_enable", "reasoning_effort"):
            # 参数一变，上次的测试结论就不再代表当前配置——否则状态条会一直显示"就绪"
            draft["llm"]["probe_ok"] = False
            draft["llm"]["probe_detail"] = "未测试"
    elif section == "expose":
        if key == "custom":
            draft["expose"]["custom"] = bool(value)
        else:
            jobs = set(draft["expose"]["jobs"])
            jobs.add(key) if value else jobs.discard(key)
            draft["expose"]["jobs"] = [job for job in servable_job_names() if job in jobs]
    return degraded, settings_collapse_mode(draft)


def settings_resettable(draft: dict, saved_cfg: dict) -> set:
    """Which “回到基线” affordances apply right now.

    与基线对比的部分：能力集合 + 参数 + 整理参数 + MCP 允许列表；**凭据永远不可重置**。
    注意固定预设也要走这套比较：模式现在只由能力项决定，预设里照样可能有被调过的参数
    （以前这里对非自定义模式直接返回空集，用户改了参数就没法一键还原）。
    """
    base = settings_baseline_values(draft, saved_cfg)
    names = set()
    # 用"将要写入的能力集"（窗口显示值）而不是草稿里可能还没同步的那份：
    # 固定预设下窗口显示的是预设能力集，而草稿在第一次 collect 之前还留着保存下来的自定义集合。
    pending_features = settings_display_features(draft)
    for key in FEATURES:
        if bool(pending_features.get(key)) != bool(base["features"].get(key)):
            names.add(f"feature:{key}")
    if draft["pipeline"] != base["pipeline"]:
        names.add("pipeline")
    if any(draft["llm"].get(key) != base["llm_params"].get(key) for key in PRESET_LLM):
        names.add("llm")
    if draft["llm"].get("max_tokens") != base["llm_params"].get("max_tokens"):
        names.add("llm_tokens")
    if any(draft["embedding"].get(key) != base["embedding_space"].get(key)
           for key in PRESET_EMBEDDING):
        names.add("embedding")
    if draft["embedding"].get("dimensions") != base["embedding_space"].get("dimensions"):
        names.add("embedding_dims")
    if draft["expose"] != base["expose"]:
        names.add("expose")
    return names


def settings_changed_items(draft: dict, saved_cfg: dict, saved_root: str, saved_mode: str,
                           targets: list) -> list:
    """Differences against what is currently saved on disk (not against defaults).

    能力集要比较「**将要写入的**」与「**当前生效的**」：
      * 将要写入 = 窗口显示的能力集（固定预设下就是该预设的能力集）；
      * 当前生效 = 当前模式对应的能力集（固定预设用它自己的，自定义才用保存下来的 custom）。
    否则固定预设下刚打开窗口就会把预设与旧 custom 的差异列成"未保存改动"（误报）。
    """
    items = []
    if draft["mode"] != saved_mode:
        items.append("模式")
    pending_features = settings_display_features(draft)
    effective_features = (saved_cfg["custom"] if saved_mode == "custom"
                          else preset_features(saved_mode))
    for key in FEATURES:
        if bool(pending_features.get(key)) != bool(effective_features.get(key)):
            items.append(FEATURES[key]["name"])
    if draft["llm"] != saved_cfg["llm"]:
        items.append("LLM 参数")
    if draft["embedding"] != saved_cfg["embedding"]:
        items.append("Embedding")
    if draft["pipeline"] != saved_cfg["pipeline"]:
        items.append("记忆管道")
    if draft["expose"] != saved_cfg["expose"]:
        items.append("MCP 暴露")
    if draft["reme_root"] != saved_root:
        items.append("ReMe 目录")
    if targets != saved_cfg.get("targets", []):
        items.append("VM 目标")
    return items


def settings_gating(draft: dict, service_up: bool, llm_ready: bool) -> dict:
    """Every enable/disable decision in one place, keyed by capability (not by section)."""
    features = settings_display_features(draft)
    custom = draft["mode"] == "custom"
    return {
        "editable": custom,
        "features": features,
        "model_features": any(features.get(key) for key in
                              ("auto_memory", "auto_memory_cc", "auto_resource", "auto_dream", "chat")),
        "embedding_fields": bool(features.get("embedding")),
        "dream_fields": bool(features.get("auto_dream")),
        # 能不能勾＝这个 job 在当前模式 / 功能开关下**真的存在**（一条规则代替了以前
        # 三处手写条件：mcp 开关、基础模式名单、auto_* 功能对应关系）
        "job_enabled": {
            job: bool(features.get("mcp")) and job in existing_job_names(draft["mode"], features)
            for job in servable_job_names()
        },
        "dream_button": bool(features.get("auto_dream")) and service_up and llm_ready,
        "reindex_button": service_up,
        "reindex_scopes": (["all", "embedding", "bm25"] if features.get("embedding") else ["all", "bm25"]),
    }


def settings_reset_feature(draft: dict, key: str, saved_cfg: dict) -> None:
    base = settings_baseline_values(draft, saved_cfg)
    draft["features"][key] = bool(base["features"].get(key))
    if not draft["features"][key] and key == "embedding":
        draft["features"]["faiss"] = False


def settings_reset_section(draft: dict, section: str, saved_cfg: dict) -> None:
    base = settings_baseline_values(draft, saved_cfg)
    if section == "llm":
        # 只重置参数，保留端点与 Key；参数一变，上次的测试结论随之作废
        draft["llm"].update(base["llm_params"], probe_ok=False, probe_detail="未测试")
    elif section == "embedding":
        draft["embedding"].update(base["embedding_space"], probe_ok=False, probe_detail="未测试")
    elif section == "pipeline":
        draft["pipeline"] = deep_copy(base["pipeline"])
    elif section == "expose":
        draft["expose"] = deep_copy(base["expose"])


def settings_reset_field(draft: dict, section: str, key: str, saved_cfg: dict) -> None:
    base = settings_baseline_values(draft, saved_cfg)
    source = {"llm": base["llm_params"], "embedding": base["embedding_space"],
              "pipeline": base["pipeline"]}.get(section)
    if source is not None and key in source:
        draft[section][key] = source[key]


def settings_reset_all(draft: dict, saved_cfg: dict) -> None:
    base = settings_baseline_values(draft, saved_cfg)
    draft["features"] = deep_copy(base["features"])
    draft["llm"].update(base["llm_params"], probe_ok=False, probe_detail="未测试")  # 端点/模型/Key 保留
    draft["embedding"].update(base["embedding_space"], probe_ok=False, probe_detail="未测试")
    draft["pipeline"] = deep_copy(base["pipeline"])
    draft["expose"] = deep_copy(base["expose"])


LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_MAX_BYTES = 1 << 20      # 1 MB per file
LOG_FILE_BACKUPS = 3              # reme-helper.log.1 ... .3, so ~4 MB ceiling


def _configure_logging() -> None:
    """装一个会自转的日志处理器：单文件 1MB，保留 3 份备份。

    托盘程序长期常驻，纯追加的日志会一直涨（这台机器上已经 55KB，且只在出问题时才有人看）。
    按大小滚动是常规做法，也不需要额外依赖。

    滚动在 Windows 上有个坑：另一个进程还开着日志文件时改不了名。正常情况下单实例守卫
    保证只有一个托盘，但升级期间新旧版本可能同时在跑；这种情况退回普通 FileHandler，
    宁可这次不滚，也不要因为日志装不上而启动失败。
    """
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler: logging.Handler
    try:
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(LOG_PATH, maxBytes=LOG_FILE_MAX_BYTES,
                                      backupCount=LOG_FILE_BACKUPS, encoding="utf-8")
    except Exception:  # noqa: BLE001 - 装不上日志不该拦住启动
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)


_configure_logging()


def log(message: str) -> None:
    logging.info(message)


def write_log_file(name: str, text: str) -> Path:
    """把一次诊断（--smoke / --ui-check / --release / --lang-audit）的结论落到 ``DIAG_LOG_DIR``。

    以前这些文件写在程序目录根部，仓库根就被 smoke.log、ui-check.log、lang-audit.log
    这些「跑一次留一个」的文件堆满了。它们属于「跑完即弃」：进分发包的 log/，仓库根只留
    需要长期维护的文件，构建时也只需清一个目录。

    注意别用 LOG_DIR（那是应用自己的日志目录，在 %LOCALAPPDATA% 下）：诊断输出要跟着
    这次运行的那个包走，构建脚本才找得到、也才清得掉。
    """
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_LOG_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


def deep_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def validate_cron(value) -> str:
    text = str(value or "").strip()
    return text if CRON_RE.match(text) else "0 23 * * *"


def normalize_advanced(cfg: dict) -> None:
    llm = cfg.setdefault("llm", {})
    llm["base_url"] = str(llm.get("base_url") or "").strip()
    llm["model"] = str(llm.get("model") or "").strip()
    llm["max_tokens"] = clamp_int(llm.get("max_tokens"), 512, 131072, 65536)
    llm["thinking_enable"] = bool(llm.get("thinking_enable"))
    llm["reasoning_effort"] = str(llm.get("reasoning_effort") or "").strip()
    llm["probe_ok"] = bool(llm.get("probe_ok"))
    llm["probe_detail"] = str(llm.get("probe_detail") or "未测试")
    pipe = cfg.setdefault("pipeline", {})
    pipe["scan_days"] = clamp_int(pipe.get("scan_days"), 1, 14, 2)
    pipe["max_units"] = clamp_int(pipe.get("max_units"), 1, 20, 5)
    pipe["dream_cron"] = validate_cron(pipe.get("dream_cron"))
    expose = cfg.setdefault("expose", {})
    expose["custom"] = bool(expose.get("custom"))
    # 这里**不校验 job 名是否存在**：本函数在 CFG 绑定之前就会被调用，而名单要靠 CFG 里的
    # reme_root 才能读出来。校验放在 expose_values() 与写盘前，那是 CFG 已经就位的地方。
    # 「勾了配置项但一项都没勾」是合法状态（＝不写白名单），所以只在键缺失时才补默认值。
    if not isinstance(expose.get("jobs"), list):
        expose["jobs"] = list(EXPOSE_DEFAULT_FALLBACK)
    else:
        expose["jobs"] = [item for item in expose["jobs"]
                          if isinstance(item, str) and item.strip()]
    emb = cfg.setdefault("embedding", {})
    emb["base_url"] = str(emb.get("base_url") or "").strip()
    emb["model"] = str(emb.get("model") or PRESET_EMBEDDING["model"]).strip()
    emb["dimensions"] = clamp_int(emb.get("dimensions"), 64, 8192, PRESET_EMBEDDING["dimensions"])
    emb["probe_ok"] = bool(emb.get("probe_ok"))
    emb["probe_detail"] = str(emb.get("probe_detail") or "未测试")


def llm_values() -> dict:
    llm = CFG.get("llm") or {}
    return {
        "base_url": str(llm.get("base_url") or "").strip(),
        "model": str(llm.get("model") or "").strip(),
        "max_tokens": clamp_int(llm.get("max_tokens"), 512, 131072, 65536),
        "thinking_enable": bool(llm.get("thinking_enable")),
        "reasoning_effort": str(llm.get("reasoning_effort") or "").strip(),
    }


def pipeline_values() -> dict:
    pipe = CFG.get("pipeline") or {}
    return {
        "scan_days": clamp_int(pipe.get("scan_days"), 1, 14, 2),
        "max_units": clamp_int(pipe.get("max_units"), 1, 20, 5),
        "dream_cron": validate_cron(pipe.get("dream_cron")),
    }


_OFFICIAL_JOBS_CACHE: dict = {"key": None, "jobs": {}}


def official_jobs() -> dict:
    """官方 default.yaml 声明的全部 job —— 真实 job 名的唯一来源。

    带 mtime 缓存：每次刷新界面都会问一次，不能每次都重解析 21 KB 的 YAML。
    """
    path = official_default_path()
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        key = (str(path), None)
    if _OFFICIAL_JOBS_CACHE["key"] != key:
        declared: dict = {}
        try:
            if path.is_file():
                config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                found = config.get("jobs")
                if isinstance(found, dict):
                    declared = found
        except (OSError, yaml.YAMLError) as exc:
            log(f"official default config unreadable ({path}): {exc}")
        _OFFICIAL_JOBS_CACHE["key"] = key
        _OFFICIAL_JOBS_CACHE["jobs"] = declared
    return _OFFICIAL_JOBS_CACHE["jobs"]


def is_servable(spec) -> bool:
    """这个 job 能否被服务层注册。

    判据就是 base_service.add_jobs() 的那一条：background / cron 的 job 被强制
    enable_serve=False，永远不会对外服务，写进白名单反而会 raise。
    """
    backend = spec.get("backend") if isinstance(spec, dict) else None
    return backend not in ("background", "cron")


def servable_job_names() -> tuple:
    """允许列表的**全部候选**：官方声明、且服务层加得进去的 job，按分组表排好。

    官方将来新增、而分组表还没收录的名字会附在末尾——宁可多列一个，也不静默漏掉。
    """
    declared = official_jobs()
    if not declared:
        return EXPOSE_JOBS_FALLBACK
    names = {name for name, spec in declared.items() if is_servable(spec)}
    grouped = tuple(job for _group, jobs in EXPOSE_JOB_GROUPS for job in jobs if job in names)
    extra = tuple(sorted(name for name in names if name not in grouped))
    return grouped + extra


def custom_job_removals(selected: dict) -> set:
    """当前功能选择会砍掉哪些 job —— generate_custom_config 与界面共用这一份规则。

    以前两处各写一份，界面上标着「可用」的 job 在生成出来的配置里可能并不存在，
    白名单一旦引用它就会让 ReMe 起不来。
    """
    removals = set()
    if not selected.get("auto_memory"):
        removals.add("auto_memory")
    if not selected.get("auto_memory_cc"):
        removals.add("auto_memory_cc")
    if not selected.get("auto_resource"):
        removals.update({"resource_watch_loop", "auto_resource"})
    if not selected.get("auto_dream"):
        removals.update({"dream_cron", "auto_dream"})
    if not selected.get("proactive_read"):
        removals.add("proactive")
    if not selected.get("chat"):
        removals.add("chat")
    return removals


def existing_job_names(mode: str, selected: dict | None = None) -> set:
    """该模式下**真正会存在**的 job 名，用来灰显勾选框。

    全部由官方 default.yaml + 功能开关推导，**不再读回生成出来的配置**：读回来就又绕成
    「文件可能过时」，而这正是白名单会写进不存在名字的根源。基础模式与自定义模式只差
    一组功能开关，所以走的是同一条推导路径。
    """
    declared = official_jobs()
    if not declared:
        return set(MINIMAL_JOBS)
    if mode == "full":
        return set(declared)
    if mode == "custom":
        features = selected if selected is not None else CFG.get("custom") or {}
    else:
        features = preset_features(mode)
    return set(declared) - custom_job_removals(features)


def default_expose_jobs() -> list:
    """默认勾选：可服务名单里去掉会改删记忆、或代价明显的那几项。"""
    return [job for job in servable_job_names() if job not in EXPOSE_DEFAULT_OFF]


def expose_job_rows() -> tuple:
    """按分组返回要显示的 (组名, (job, ...))，组内只保留当前候选名单里的 job。"""
    names = set(servable_job_names())
    rows = []
    for group_name, jobs in EXPOSE_JOB_GROUPS:
        kept = tuple(job for job in jobs if job in names)
        if kept:
            rows.append((group_name, kept))
    known = {job for _group, jobs in EXPOSE_JOB_GROUPS for job in jobs}
    extra = tuple(job for job in servable_job_names() if job not in known)
    if extra:
        rows.append(("其他 Job", extra))
    return tuple(rows)


def expose_values() -> dict:
    """写进配置的暴露设置。

    顺手丢掉已经不存在的 job 名——老配置里的 proactive_read 就是这样退场的，
    留着它下次生成配置会让 ReMe 起不来。
    """
    expose = CFG.get("expose") or {}
    jobs = [item for item in (expose.get("jobs") or []) if isinstance(item, str) and item.strip()]
    allowed = set(servable_job_names())
    return {"custom": bool(expose.get("custom")),
            "jobs": [job for job in jobs if job in allowed]}


def embedding_values() -> dict:
    emb = CFG.get("embedding") or {}
    return {
        "base_url": str(emb.get("base_url") or "").strip(),
        "model": str(emb.get("model") or PRESET_EMBEDDING["model"]).strip(),
        "dimensions": clamp_int(emb.get("dimensions"), 64, 8192, PRESET_EMBEDDING["dimensions"]),
        "probe_ok": bool(emb.get("probe_ok")),
        "probe_detail": str(emb.get("probe_detail") or "未测试"),
    }


def cron_echo(expr: str) -> str:
    """Turn a cron string into a plain-language line, or say it will fall back."""
    text = str(expr or "").strip()
    for known, label in CRON_PRESETS:
        if text == known:
            return f"下次整理：{label.split('（')[0]}"
    if not CRON_RE.match(text):
        return "cron 格式不正确，将回退为每天 23:00"
    parts = text.split()
    try:
        minute, hour = int(parts[0]), int(parts[1])
        return f"下次整理：每天 {hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        return "下次整理：按自定义计划执行"


def daily_stats(scan_days: int) -> tuple[int, int]:
    """Count daily files and characters inside the scan window (real workspace data)."""
    root = reme_root() / "workspace" / "daily"
    if not root.is_dir():
        return 0, 0
    days = sorted((item for item in root.glob("2*-*-*") if item.is_dir()), reverse=True)[:max(1, scan_days)]
    targets = [item for day in days for item in day.glob("*.md")]
    targets += [root / f"{day.name}.md" for day in days if (root / f"{day.name}.md").is_file()]
    chars = 0
    for path in targets:
        try:
            chars += len(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return len(targets), chars


def cosine_similarity(left: list, right: list) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


def extract_json_object(text: str):
    """Pull the first JSON object out of a model reply, tolerating ``` fences."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except Exception:  # noqa: BLE001 - callers only care whether it parsed
        return None


def test_embedding(base_url: str, model: str, api_key: str, dimensions: int) -> tuple[bool, str, bool]:
    """Verify the endpoint serves embeddings, honours the dimension, and ranks a paraphrase
    above an unrelated sentence — a retrieval sanity check rather than a bare ping."""
    if not base_url or not model:
        return False, "请先填写 Embedding 的地址与模型", False
    samples = ["猫喜欢吃鱼", "小猫爱吃鱼", "今天股市大涨"]
    url = base_url.rstrip("/") + "/embeddings"
    started = time.time()
    ok, data = http_json(url, {"model": model, "input": samples, "dimensions": dimensions},
                         timeout=60.0, api_key=api_key)
    dimension_note = ""
    if not ok and "400" in str(data):
        # 部分端点不接受 dimensions 参数，去掉参数重试一次
        ok, data = http_json(url, {"model": model, "input": samples}, timeout=60.0, api_key=api_key)
        if ok:
            dimension_note = "；该端点不接受 dimensions 参数，按原生维度返回"
    elapsed = time.time() - started
    if not ok:
        detail = str(data)
        if "404" in detail:
            return False, f"该端点不提供 embedding（HTTP 404，{elapsed:.1f}s）。换一个端点，或改用本地模型。", False
        return False, f"调用失败（{elapsed:.1f}s）：{detail}", False
    try:
        vectors = [item["embedding"] for item in data["data"]]
        actual = len(vectors[0])
    except Exception:
        return False, f"返回结构异常（{elapsed:.1f}s）：{str(data)[:200]}", False
    if actual != dimensions:
        return False, (
            f"端点返回 {actual} 维，与配置的 {dimensions} 维不一致（{elapsed:.1f}s）。"
            "必须把“维度”改成一致，否则检索结果不可用（改完要重建索引）。"
        ), False
    near = cosine_similarity(vectors[0], vectors[1])
    far = cosine_similarity(vectors[0], vectors[2])
    if near <= far:
        return False, (
            f"维度 {actual} 一致，但语义排序异常（近义 {near:.2f} ≤ 无关 {far:.2f}，{elapsed:.1f}s）："
            "该模型可能不适合中文检索，或模型名/维度填错了。"
        ), False
    return True, (
        f"已验证：embedding 接口可用 + 语义排序正常（近义 {near:.2f} > 无关 {far:.2f}）"
        f"，维度 {actual}，{elapsed:.1f}s{dimension_note}"
    ), True


def load_config() -> dict:
    raw = {}
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            log(f"config load failed: {exc}")
    cfg = deep_copy(DEFAULT_CONFIG)
    cfg.update({k: v for k, v in raw.items() if k not in {"custom", "llm", "embedding", "pipeline", "expose", "targets"}})
    for section in ("custom", "llm", "embedding", "pipeline", "expose"):
        incoming = raw.get(section)
        if isinstance(incoming, dict):
            cfg[section].update(incoming)
    normalize_advanced(cfg)
    cfg["targets"] = raw.get("targets") or deep_copy(DEFAULT_CONFIG["targets"])
    if cfg.get("mode") not in MODE_NAMES:
        cfg["mode"] = "minimal"
    try:
        cfg["probe_interval_sec"] = max(5, int(cfg.get("probe_interval_sec", 20)))
    except (TypeError, ValueError):
        cfg["probe_interval_sec"] = 20
    for target in cfg["targets"]:
        target.setdefault("name", target.get("host") or "VM")
        target.setdefault("user", "")
        target.setdefault("host", "")
        target.setdefault("port", 22)
        target.setdefault("key", "")
        target.setdefault("remote_port", 22333)
        target.setdefault("enabled", True)
    return cfg


def seed_config() -> None:
    """首次运行：把 config.json 放进用户数据目录（**播种 + 迁移二合一**）。

    源文件 `APP_DIR/config.json` 有**两种身份**，取决于用户是怎么拿到它的：
      * 新装 —— 发布包里那份是 `make_release_config.py` 生成的**出厂模板**
      * 老用户升级 —— 那份是**他自己的活配置**
    所以「新位置不存在就复制过去」这一段代码同时覆盖播种与迁移，不必分两条路。

    幂等：第二次启动时新位置已存在，直接返回。**只复制、不删除** —— 旧文件留着当回退材料。
    显式覆盖（REME_HELPER_CONFIG）时什么都不做：那种情况下调用方自己指定了配置，不该被我们
    的播种逻辑插一脚。
    """
    if os.environ.get("REME_HELPER_CONFIG"):
        return
    if CONFIG_PATH.exists() or not LEGACY_CONFIG_PATH.is_file():
        return
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_CONFIG_PATH, CONFIG_PATH)
        log(f"config seeded: {LEGACY_CONFIG_PATH} -> {CONFIG_PATH}")
    except OSError as exc:  # noqa: BLE001 - 读不到旧文件就按出厂默认跑，别拦住启动
        log(f"config seed failed: {exc}")


seed_config()
CFG = load_config()


def save_config() -> None:
    CONFIG_PATH.write_text(json.dumps(CFG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reme_root() -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(CFG.get("reme_root") or DEFAULT_REME_ROOT))))


def looks_like_reme_install(path: Path) -> bool:
    """A usable ReMe root: the venv python plus either the CLI or the package."""
    if not path.is_dir():
        return False
    python = path / "venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = path / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return False
    markers = [
        path / "venv" / "Scripts" / "reme.exe",
        path / ".venv" / "Scripts" / "reme.exe",
        path / "venv" / "Lib" / "site-packages" / "reme",
        path / ".venv" / "Lib" / "site-packages" / "reme",
    ]
    return any(marker.exists() for marker in markers)


def scan_reme_installations() -> list[Path]:
    """Look for existing ReMe installs so a fresh user does not have to type the path."""
    candidates: list[Path] = [reme_root()]
    env_root = os.environ.get("REME_ROOT")
    if env_root:
        candidates.append(Path(os.path.expandvars(env_root)))
    home = Path(os.path.expanduser("~"))
    local_appdata = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    for base in ("H:/Tools", "C:/Tools", "D:/Tools", "E:/Tools"):
        candidates.append(Path(base) / "ReMe")
    candidates += [
        home / "ReMe",
        home / "reme",
        home / "Documents" / "ReMe",
        local_appdata / "Programs" / "ReMe",
        Path("C:/ReMe"),
    ]
    for drive in ("C:/", "D:/", "E:/", "F:/", "H:/"):
        candidates.append(Path(drive) / "ReMe")
    found: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in found:
            continue
        if looks_like_reme_install(resolved):
            found.append(resolved)
    return found


def reme_log_dir() -> Path:
    return reme_root() / "logs"


DREAM_SCAN_RE = re.compile(
    r"scan summary existing=(?P<existing>\d+) indexed=(?P<indexed>\d+) changed=(?P<changed>\d+)"
    r" unchanged=(?P<unchanged>\d+) deleted=(?P<deleted>\d+)"
)
DREAM_INTEGRATE_RE = re.compile(r"Integrated (?P<units>\d+) unit\(s\); skipped (?P<skipped>\d+)")
DREAM_SKIP_MARK = "skip no changed input"
LOG_TIME_RE = re.compile(r"^(?P<when>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")


def last_dream_summary(max_files: int = 4, tail_lines: int = 20000) -> tuple[bool, str]:
    """Summarise the most recent dream run from ReMe's logs (read-only, no service call)."""
    log_dir = reme_log_dir()
    if not log_dir.is_dir():
        return False, "还没有日志目录"
    try:
        files = sorted((path for path in log_dir.glob("*.log")), key=lambda path: path.stat().st_mtime)
    except OSError:
        return False, "读取日志失败"
    if not files:
        return False, "还没有日志"
    lines: list[str] = []
    for path in files[-max_files:]:
        try:
            lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_lines:])
        except OSError:
            continue
    state = {"kind": "", "when": "", "units": 0, "skipped": 0, "changed": None, "existing": None}
    for line in reversed(lines):
        if not state["kind"]:
            if DREAM_SKIP_MARK in line:
                state["kind"], state["when"] = "skip", (LOG_TIME_RE.match(line).group("when") if LOG_TIME_RE.match(line) else "")
            else:
                integrated = DREAM_INTEGRATE_RE.search(line)
                if integrated:
                    state["kind"] = "integrated"
                    state["units"] = int(integrated.group("units"))
                    state["skipped"] = int(integrated.group("skipped"))
                    state["when"] = LOG_TIME_RE.match(line).group("when") if LOG_TIME_RE.match(line) else ""
            continue
        scan = DREAM_SCAN_RE.search(line)
        if scan:
            state["changed"] = int(scan.group("changed"))
            state["existing"] = int(scan.group("existing"))
            break
    if not state["kind"]:
        return False, "还没有整理记录"
    when = state["when"] or "（时间未知）"
    if state["kind"] == "skip":
        return True, f"上次整理：{when} · 判定无新内容，直接跳过（未消耗 token）"
    detail = f"上次整理：{when} · 写入 {state['units']} 个节点"
    if state["changed"] is not None:
        detail += f"（扫描 {state['existing']} 个文件、其中 {state['changed']} 个有变化"
        detail += f"，跳过 {state['skipped']} 个单元）" if state["skipped"] else "）"
    elif state["skipped"]:
        detail += f"（跳过 {state['skipped']} 个单元）"
    return True, detail


def reme_installed() -> bool:
    return looks_like_reme_install(reme_root())


def reme_install_prompt(root_hint: str = DEFAULT_REME_ROOT) -> str:
    """A ready-to-paste prompt that lets an agent install and start ReMe for the user."""
    return (
        "请在这台 Windows 机器上安装并启动 ReMe（本地优先的长期记忆服务），完成后回报结果。\n"
        "\n"
        "背景：ReMe 用 Markdown 文件保存记忆，本机服务默认监听 2333 端口，供 DSH / Codex 等客户端"
        "通过 MCP 读写记忆。\n"
        "\n"
        "请按官方方式安装（PowerShell）：\n"
        f"1) 建目录与虚拟环境：mkdir \"{root_hint}\"；用 Python 3.11+（推荐 3.13）执行 "
        f"python -m venv \"{root_hint}\\venv\"\n"
        f"2) 安装：\"{root_hint}\\venv\\Scripts\\python.exe\" -m pip install -U \"reme-ai[core]\"\n"
        f"3) 启动服务：\"{root_hint}\\venv\\Scripts\\reme.exe\" start service.backend=http"
        "（默认 http://127.0.0.1:2333/，Studio 也在同一个地址）\n"
        f"4) 验证：请求 http://127.0.0.1:2333/health_check 应返回正常；浏览器打开 "
        "http://127.0.0.1:2333/ 能看到工作区界面\n"
        "5) 如果 2333 被占用，用 service.port=<其他端口> 启动并告诉我端口号\n"
        "\n"
        "完成后请告诉我：① 安装根目录的绝对路径 ② 服务地址与端口 ③ 是否已配置 LLM / Embedding"
        "（记忆的自动提炼需要 LLM；语义检索需要 Embedding，可选）。\n"
        "官方文档：https://github.com/agentscope-ai/ReMe"
    )


def helper_location() -> str:
    """本工具自己的位置（打包后是 exe，源码运行是目录）。"""
    return str(Path(sys.executable) if getattr(sys, "frozen", False) else APP_DIR)


def reme_upgrade_prompt(current: str = "", latest: str = "", root_hint: str = "") -> str:
    """给 AI 的升级提示词：**两段式**——先只分析并回报方案，等用户说「执行」才动手。

    关键设计：不允许 AI 照着步骤直接升级。升级会牵动配置、依赖与配套工具，必须先让它
    读一遍目标版本、评估风险、把决策点摆出来；用户确认后才执行。
    """
    root = root_hint or str(CFG.get("reme_root") or DEFAULT_REME_ROOT)
    versions = reme_versions()
    installed = current or versions.get("reme-ai", "") or "未知"
    # 目标版本可能还不知道（用户没点过「检查更新」）：那就直说，别写「未知」再跟一句括注，
    # 那样读起来自相矛盾。
    target = latest or REME_UPDATE_STATE.get("latest", "")
    target_hint = (t("（PyPI 最新稳定版；以你自己查到的为准）") if target
                   else t("还没查过，请自行查 PyPI 上的最新稳定版"))
    running = "运行中" if service_is_healthy() else "已停止"
    return "\n".join([
        t("请帮我升级这台机器上的 ReMe（本地优先的长期记忆服务）。"),
        t("先只做分析，把方案报给我；等我说「执行」再动手。"),
        "",
        t("## 现状"),
        f"- {t('安装根目录：')}{root}{t('（venv 在同一目录下）')}",
        f"- {t('当前版本：')}reme-ai {installed}{t('，pip 安装，extra 是 [core]')}",
        f"- {t('目标版本：')}{target or t('（待确认）')}{target_hint}",
        f"- {t('服务地址：')}http://127.0.0.1:2333{t('，当前')}{t(running)}",
        f"- {t('配套工具：')}{helper_location()}{t('，负责生成配置、启停服务、VM 隧道')}",
        "",
        t("## 第一阶段：只分析，不动手"),
        t("允许的动作：查 PyPI、把新版 wheel 下载到临时目录解包对比、读 config/ 与日志、读包的 METADATA。"),
        t("在我说「执行」之前：不要运行任何 pip 安装命令、不要停启服务、不要改任何配置文件。"),
        t("请按这个格式回报："),
        t("1. 版本与来源：当前 → 目标，数据从哪来"),
        t("2. 会影响什么：新版 default.yaml 的 job 表差异（新增 / 删除 / 改名了哪些）；"
          "依赖变化，尤其是 agentscope 的 pin（现在是 ==2.0.7.post1）"),
        t("3. 需要联动 ReMe 助手的地方：升级后要用它重新生成三份配置（app.yaml / app-full.yaml / "
          "app-custom.yaml）；要重启它（它启动时才重新内省思考强度档位的合法集合）；"
          "要重新核对 MCP 工具暴露白名单（新 default.yaml 的 job 表可能变了）；助手本身不用重装"),
        t("4. 升级步骤：编号、简明、每一步带决策点"),
        t("5. 风险与回滚：回滚要给出一条具体命令"),
        t("6. 结论：有问题就把问题列出来；没问题就说「没有问题」，然后停下等我回复「执行」"),
        "",
        t("## 第二阶段：我说「执行」之后"),
        t("1. 先备份：完整复制 workspace（我的记忆本体），再备份 config\\ 与 .env。备份是复制，不是移动。"),
        t("2. 确认服务已停止（本机由 ReMe 助手的托盘菜单启停）。"),
        f"3. {t('用同一个 extra 升级：')}\"{root}\\venv\\Scripts\\python.exe\" -m pip install -U \"reme-ai[core]\"",
        t("4. 打开 ReMe 助手控制台，逐项核对后点「验证并保存」，重新生成配置。"),
        t("5. 起服务验证：health_check、Studio 页面、reme version；"
          "再用助手跑一次「测试连接」确认 LLM / Embedding 仍可用。"),
        t("6. 回报新版本号，以及第 2 项里预判的差异是否属实。"),
        "",
        t("## 硬约束"),
        t("- 不要改动 .env 与 workspace 的内容（只备份）"),
        t("- 不要用 --no-deps「图省事」"),
        t("- 保持 [core] extra，否则会丢掉 agentscope 与 reme_studio"),
        t("- 只升级 ReMe，ReMe 助手不用动"),
        t("- 任何一步失败就停下来告诉我，不要自行绕过"),
    ])


def merge_env_defaults(draft: dict, env: dict) -> dict:
    """用 .env 校正端点字段，返回 ``{"filled": [...], "corrected": [...]}``。

    **ReMe 真正读的是 .env**，所以这里以 .env 为准：
      * 保存值为空 → 直接补上（filled）：老版本可能存过空模型，不补的话界面看着像「配置丢了」；
      * 保存值与 .env 不同 → 用 .env 覆盖（corrected）：否则界面显示的和实际生效的是两回事
        （外部工具/Studio 改过 .env 就会这样）。

    两项都会提示用户，保存后会把 .env 的值写回 config.json，两边重新一致。
    """
    filled: list[str] = []
    corrected: list[str] = []
    pairs = (
        ("llm", "base_url", "LLM_BASE_URL"),
        ("llm", "model", "LLM_MODEL_NAME"),
        ("embedding", "base_url", "EMBEDDING_BASE_URL"),
        ("embedding", "model", "EMBEDDING_MODEL_NAME"),
    )
    for section, key, env_name in pairs:
        current = str(draft[section].get(key) or "").strip()
        value = str(env.get(env_name) or "").strip()
        if not value:
            continue
        if not current:
            draft[section][key] = value
            filled.append(f"{section}.{key}")
        elif current != value:
            draft[section][key] = value
            corrected.append(f"{section}.{key}")
    return {"filled": filled, "corrected": corrected}


def reme_exe() -> Path:
    return reme_root() / "venv" / "Scripts" / "reme.exe"


def reme_python() -> Path:
    return reme_root() / "venv" / "Scripts" / "python.exe"


def mode_config_path(mode: str | None = None) -> Path:
    selected = mode or CFG["mode"]
    names = {"minimal": "app.yaml", "full": "app-full.yaml", "custom": "app-custom.yaml"}
    return reme_root() / "config" / names[selected]


def official_default_path() -> Path:
    return reme_root() / "venv" / "Lib" / "site-packages" / "reme" / "config" / "default.yaml"


# ---------------- ReMe 版本与更新 ----------------
PYPI_REME_JSON = "https://pypi.org/pypi/reme-ai/json"
# 托盘菜单的文案**每次右键都会重新求值**，所以这里既不能起子进程（实测 160ms，右键会卡），
# 也不该反复读盘 —— 目录 mtime 一变（装了/升了包）就自动失效。
_VERSION_CACHE: dict = {"key": None, "value": {}}
# 最近一次「检查更新」的结果：托盘版本行要把它显示出来，气泡被系统吞掉也看得见。
REME_UPDATE_STATE: dict = {"checked_for": "", "latest": "", "at": 0.0, "error": ""}


def site_packages_dir(root: Path | None = None) -> Path | None:
    base = root or reme_root()
    for relative in (("venv", "Lib", "site-packages"), (".venv", "Lib", "site-packages")):
        path = base.joinpath(*relative)
        if path.is_dir():
            return path
    return None


def installed_package_version(dist: str, root: Path | None = None) -> str:
    """从 site-packages 的 *.dist-info 里读版本号，不起子进程。

    METADATA 里的 Version 是权威值；读不到才退回解析目录名（reme_ai-0.4.1.11.dist-info）。
    """
    site = site_packages_dir(root)
    if site is None:
        return ""
    prefix = dist.replace("-", "_").lower() + "-"
    try:
        found = sorted(entry for entry in site.iterdir()
                       if entry.is_dir()
                       and entry.name.lower().startswith(prefix)
                       and entry.name.lower().endswith(".dist-info"))
    except OSError as exc:
        log(f"dist-info scan failed: {exc}")
        return ""
    if not found:
        return ""
    info = found[-1]
    try:
        metadata = info / "METADATA"
        if metadata.is_file():
            for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                    if version:
                        return version
    except OSError as exc:
        log(f"METADATA read failed: {exc}")
    stem = info.name[: -len(".dist-info")]
    return stem.split("-", 1)[1] if "-" in stem else ""


def reme_versions() -> dict:
    """``{"reme-ai": "0.4.1.11", "reme_studio": "0.1.1"}``，带目录 mtime 缓存。"""
    site = site_packages_dir()
    try:
        key = (str(site), site.stat().st_mtime_ns if site else None)
    except OSError:
        key = (str(site), None)
    if _VERSION_CACHE["key"] != key:
        _VERSION_CACHE["key"] = key
        _VERSION_CACHE["value"] = {name: installed_package_version(name)
                                   for name in ("reme-ai", "reme_studio")}
    return _VERSION_CACHE["value"]


def is_prerelease(value: str) -> bool:
    """``0.4.2.0b1`` / ``0.5.0rc1`` / ``0.5.0.dev1`` 这类都算预发布。

    PyPI 的 ``info.version`` 是「最后一次上传」，上游发了预发布它就会变成预发布版，
    所以我们只看稳定版。
    """
    return bool(re.search(r"[A-Za-z]", str(value or "")))


def version_key(value: str) -> tuple:
    """把版本号拆成可比较的元组（``0.4.1.11`` → ``(0, 4, 1, 11)``）。"""
    parts = []
    for chunk in re.split(r"[.\-+]", str(value or "").strip()):
        match = re.match(r"^(\d+)", chunk)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts)


def version_is_newer(candidate: str, current: str) -> bool:
    """candidate 是否比 current 新。优先用 packaging 按 PEP 440 比，取不到再退化成元组比较。

    退化的那种分不清 ``0.4.2.0b1`` 与 ``0.4.2.0`` —— 但我们只拿稳定版来比，不影响。
    """
    if not candidate or not current:
        return False
    try:
        from packaging.version import InvalidVersion, parse
    except ImportError:
        return version_key(candidate) > version_key(current)
    try:
        return parse(candidate) > parse(current)
    except InvalidVersion:
        return version_key(candidate) > version_key(current)


def pick_latest_stable(data: dict) -> str:
    """从 PyPI 的 JSON 里挑出最新的**稳定**版本号。"""
    candidates = [name for name in (data.get("releases") or {}) if name and not is_prerelease(name)]
    info_version = str((data.get("info") or {}).get("version") or "").strip()
    if info_version and not is_prerelease(info_version):
        candidates.append(info_version)
    if not candidates:
        return ""
    try:
        from packaging.version import parse
        return str(max(candidates, key=parse))
    except Exception:  # noqa: BLE001 - packaging 不在或版本号怪：退回元组比较
        return max(candidates, key=version_key)


def fetch_latest_reme_version(timeout: float = 8.0) -> tuple[bool, str]:
    """查 PyPI 上 reme-ai 的最新稳定版。返回 ``(ok, 版本号或错误说明)``。"""
    request = urllib.request.Request(
        PYPI_REME_JSON, headers={"User-Agent": f"{APP_ID}/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            data = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    latest = pick_latest_stable(data if isinstance(data, dict) else {})
    if not latest:
        return False, "响应里没有可用的稳定版本号"
    return True, latest


def check_reme_update() -> tuple[bool, str]:
    """托盘「检查 ReMe 更新」：只提示，不升级。run_action 会把返回值弹成气泡。"""
    current = reme_versions().get("reme-ai", "")
    if not current:
        return False, "没检测到 ReMe，先安装再检查更新"
    ok, detail = fetch_latest_reme_version()
    if not ok:
        REME_UPDATE_STATE.update(checked_for=current, latest="", at=time.time(), error=detail)
        return False, f"检查更新失败：{detail}（离线，或者 PyPI 被代理拦了？）"
    REME_UPDATE_STATE.update(checked_for=current, latest=detail, at=time.time(), error="")
    if version_is_newer(detail, current):
        return True, (f"ReMe 有新版本 {detail}（本机 {current}）。"
                      "右键「复制 ReMe 更新步骤（交给 AI 执行）」")
    return True, f"ReMe 已是最新版本 {current}"


def read_env_values() -> dict[str, str]:
    values = {k: str(v) for k, v in os.environ.items()}
    path = reme_root() / ".env"
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        except OSError as exc:
            log(f"env read failed: {exc}")
    return values


def env_file_text() -> str:
    path = reme_root() / ".env"
    try:
        return path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    except OSError as exc:
        log(f"env read failed: {exc}")
        return ""


def write_env_values(updates: dict[str, str]) -> None:
    """Update .env keys in place, keeping unrelated lines and comments."""
    path = reme_root() / ".env"
    remaining = {key: value for key, value in updates.items() if value is not None}
    lines = env_file_text().splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def write_env_text(text: str) -> None:
    """Restore a previous .env snapshot (used to roll back a failed save)."""
    path = reme_root() / ".env"
    if text:
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    elif path.is_file():
        path.unlink()


def http_json(url: str, payload: dict | None = None, timeout: float = 30.0, api_key: str = "") -> tuple[bool, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
        return True, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()[:400]
        return False, f"HTTP {exc.code} {detail}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def fetch_models(base_url: str, api_key: str = "") -> tuple[bool, object]:
    ok, result = fetch_models_detailed(base_url, api_key)
    if not ok:
        return False, result
    ids, _caps = result
    return True, ids


def fetch_models_detailed(base_url: str, api_key: str = "") -> tuple[bool, object]:
    """→ (True, (ids, caps_by_id)) 或 (False, 错误文本)。

    caps_by_id 保留每个模型的 capabilities：部分网关（例如本机的 opencodex）会声明
    supports_reasoning 与 reasoning_effort，用来把「思考强度」那一行收窄；普通
    OpenAI 兼容端点只返回 id，这时 caps 是空字典，就只用本地那一层判断。
    """
    if not base_url:
        return False, "请先填写 Base URL"
    ok, data = http_json(base_url.rstrip("/") + "/models", timeout=20.0, api_key=api_key)
    if not ok:
        return False, data
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        ids: list[str] = []
        caps: dict[str, dict] = {}
        for item in data["data"]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            ids.append(model_id)
            if isinstance(item.get("capabilities"), dict):
                caps[model_id] = item["capabilities"]
        if ids:
            return True, (ids, caps)
        return False, "端点没有返回任何模型"
    return False, "返回结构不是 OpenAI 兼容的模型列表"


# ================= reasoning 能力：硬约束 + 参考信息 =================
# ReMe 把 reasoning_effort 原样塞进 agentscope 的 Parameters，那是个 pydantic Literal：
# 值不在集合里就在**组件构造时**失败（一个网络包都不发），整个服务起不来。所以
# 「ReMe 那一层」是**唯一的硬约束**，必须离线、确定性地校验。
# 端点声明的模型能力只当**参考信息**，不用来禁用档位：实测那份元数据两个方向都会错
# （声明 ultra 却全部拒收；声明 supports_reasoning=false 却全都接受），拿它过滤会把本来
# 能用的选项悄悄藏掉——那比"多显示几个档位"更糟。真发错了上游会明确报错。
EFFORT_BACKEND_FALLBACK: dict[str, tuple[str, ...]] = {
    "openai": ("none", "minimal", "low", "medium", "high", "xhigh"),
    "deepseek": ("high", "max"),
    "anthropic": ("low", "medium", "high", "xhigh", "max"),
    "moonshot": ("low", "high", "max"),
    "xai": ("low", "medium", "high"),
    "dashscope": (),
    "gemini": (),
    "ollama": (),
}
_BACKEND_EFFORT_CACHE: dict[str, tuple[str, ...]] = {}
_BACKEND_EFFORT_STARTED = False
_BACKEND_EFFORT_LOCK = threading.Lock()

# 走 ReMe 自己那条链（wrapper.credential_cls.get_chat_model_class()）去问模型类，
# 所以不用硬编码、也不会随 agentscope 升级而漂移。
_MODEL_LIBRARY_EFFORT_SCRIPT = (
    "import json,typing\n"
    "from reme.components.as_llm import (AnthropicAsLLM, DashScopeAsLLM, DeepSeekAsLLM,"
    " GeminiAsLLM, MoonshotAsLLM, OllamaAsLLM, OpenAIAsLLM, XAIAsLLM)\n"
    "WRAPPERS={'openai':OpenAIAsLLM,'anthropic':AnthropicAsLLM,'dashscope':DashScopeAsLLM,"
    "'deepseek':DeepSeekAsLLM,'gemini':GeminiAsLLM,'moonshot':MoonshotAsLLM,"
    "'ollama':OllamaAsLLM,'xai':XAIAsLLM}\n"
    "out={}\n"
    "for name,cls in WRAPPERS.items():\n"
    "    try:\n"
    "        mc=cls.credential_cls.get_chat_model_class()\n"
    "        fld=getattr(mc.Parameters,'model_fields',{}).get('reasoning_effort')\n"
    "        vals=None\n"
    "        if fld is not None:\n"
    "            for arg in typing.get_args(fld.annotation):\n"
    "                got=[x for x in typing.get_args(arg) if isinstance(x,str)]\n"
    "                if got:\n"
    "                    vals=got\n"
    "                    break\n"
    "        out[name]=vals\n"
    "    except Exception:\n"
    "        out[name]=None\n"
    "print(json.dumps(out))\n"
)


def _run_model_library_effort_script() -> dict[str, tuple[str, ...]]:
    """跑模型接入库档位脚本：起子进程读已安装 agentscope 的类型注解。只在后台线程调用。"""
    try:
        result = subprocess.run(
            [str(reme_python()), "-c", _MODEL_LIBRARY_EFFORT_SCRIPT],
            cwd=str(reme_root()),
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
        raw = json.loads(result.stdout.strip().splitlines()[-1])
        return {str(key): tuple(values or ()) for key, values in raw.items()}
    except Exception as exc:  # noqa: BLE001 - 跑脚本只是增强手段，失败就用内置表
        log(f"model-library effort script failed: {exc}")
        return {}


def _warm_backend_effort_values() -> None:
    global _BACKEND_EFFORT_STARTED
    with _BACKEND_EFFORT_LOCK:
        if _BACKEND_EFFORT_STARTED:
            return
        _BACKEND_EFFORT_STARTED = True
    table = _run_model_library_effort_script()
    if not table:
        return
    for name, values in EFFORT_BACKEND_FALLBACK.items():
        table.setdefault(name, values)
    _BACKEND_EFFORT_CACHE.clear()
    _BACKEND_EFFORT_CACHE.update(table)


def backend_effort_values() -> dict[str, tuple[str, ...]]:
    """{backend: 该 backend 允许的档位}。**永不阻塞 UI 线程**。

    跑模型接入库档位脚本只是"增强"，不是前提：内置表已与当前安装一致，所以先返回
    内置值、后台线程换新即可。第一次调用会拉起一个约 1 秒的子进程——绝不能落在建窗口
    的路径上，否则整页要晚一拍才排完版。
    """
    if not _BACKEND_EFFORT_CACHE:
        _BACKEND_EFFORT_CACHE.update(EFFORT_BACKEND_FALLBACK)
        threading.Thread(target=_warm_backend_effort_values, daemon=True).start()
    return dict(_BACKEND_EFFORT_CACHE)


def llm_backend_name() -> str:
    """ReMe 真正使用的 backend：.env 里的 LLM_BACKEND（ReMe 默认 openai）。"""
    return str(read_env_values().get("LLM_BACKEND") or "").strip().lower() or "openai"


def effort_options(model_caps: dict | None = None) -> tuple[list[str], str, list[str]]:
    """→ (可选档位, 原因码, 端点声明的档位)。

    可选档位**只由 ReMe 那一层决定**（agentscope 的 pydantic Literal）—— 那是硬约束：
    值不在集合里，服务在**组件构造**时就会直接失败，连网络请求都发不出去。

    端点声明的模型能力只作为提示返回，**不用来过滤**：实测这份元数据两个方向都可能错
    （声明 ultra 却全部拒收；声明 supports_reasoning=false 却全都接受），拿它禁用档位
    会把本来能用的选项悄悄藏掉。真发错了上游会明确报错，而「测试连接」现在会带上
    真实生效的参数，能当场测出来。

    原因码：backend_none（该后台没有这个参数）/ model_declared（端点声明了档位）
    / backend_only（端点没提供能力信息）。
    """
    allowed = list(backend_effort_values().get(llm_backend_name(), ()))
    declared: list[str] = []
    if isinstance(model_caps, dict):
        raw = model_caps.get("reasoning_effort")
        if isinstance(raw, list):
            declared = [value for value in raw if isinstance(value, str)]
    if not allowed:
        return [], "backend_none", declared
    return allowed, ("model_declared" if declared else "backend_only"), declared


def effort_is_allowed(value: str, options: list[str]) -> bool:
    """"不设置"（空串）永远允许；其余必须落在可用集合里。"""
    return not value or value in options



def test_llm(base_url: str, model: str, api_key: str = "",
             thinking_enable: bool = False, reasoning_effort: str = "") -> tuple[bool, str]:
    """Verify the endpoint serves chat completions *and* returns structured JSON.

    A bare ping would pass on a model that cannot produce the JSON that auto_memory and
    auto_dream depend on, so the probe asks for a fixed JSON object and checks the answer.

    同时按**将要写进配置的那组参数**再发一次：agentscope 只在 thinking_enable 为真时
    才把 reasoning_effort 带上线（见其 _openai_chat/_model.py），所以这里照同样的条件
    带上。否则「测试通过」和「服务能起来」说的不是一回事。
    """
    if not base_url or not model:
        return False, "请先填写 Base URL 与模型名"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You reply with a JSON object only, no prose."},
            {"role": "user", "content": 'Reply with exactly {"ok": true} and nothing else.'},
        ],
        "max_tokens": 256,
    }
    if thinking_enable and reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    started = time.time()
    ok, data = http_json(base_url.rstrip("/") + "/chat/completions", payload, timeout=90.0, api_key=api_key)
    elapsed = time.time() - started
    if not ok:
        if payload.get("reasoning_effort"):
            return False, (f"调用失败（{elapsed:.1f}s，这次带了 reasoning_effort="
                           f"{reasoning_effort}）：{data}")
        return False, f"调用失败（{elapsed:.1f}s）：{data}"
    try:
        message = data["choices"][0]["message"]
    except Exception:
        return False, f"返回结构异常（{elapsed:.1f}s）：{str(data)[:200]}"
    content = str(message.get("content") or "").strip()
    reasoning = str(message.get("reasoning_content") or "").strip()
    if not content and reasoning:
        return False, (
            f"连通但 content 为空（{elapsed:.1f}s）：模型把预算花在 reasoning 上。"
            "请提高 max_tokens 或保持“允许内部思考”关闭，否则 auto_dream 会写出空内容。"
        )
    if not content:
        return False, f"连通但返回空内容（{elapsed:.1f}s）"
    parsed = extract_json_object(content)
    if isinstance(parsed, dict) and parsed.get("ok") is True:
        return True, f"已验证：对话接口可用 + 能按要求输出 JSON（{elapsed:.1f}s）"
    return False, (
        f"接口可用，但未按要求输出 JSON（{elapsed:.1f}s）：{content[:80]!r}。"
        "记忆提炼依赖结构化输出，建议换模型或提高 max_tokens。"
    )


def run_reme_job(job: str, payload: dict | None = None, timeout: float = 900.0) -> tuple[bool, str]:
    if not probe_health():
        return False, "ReMe 未运行，请先启动服务"
    started = time.time()
    ok, data = http_json(f"http://127.0.0.1:2333/{job}", payload or {}, timeout=timeout)
    elapsed = time.time() - started
    if not ok:
        return False, f"{job} 调用失败（{elapsed:.0f}s）：{data}"
    if isinstance(data, dict):
        if data.get("success") is False:
            return False, f"{job} 返回失败（{elapsed:.0f}s）：{str(data.get('answer'))[:300]}"
        answer = str(data.get("answer") or "").strip()
        if answer:
            return True, f"{job} 完成（{elapsed:.0f}s）：{answer[:400]}"
        metadata = json.dumps(data.get("metadata") or {}, ensure_ascii=False)
        return True, f"{job} 完成（{elapsed:.0f}s）：{metadata[:300]}"
    return True, f"{job} 完成（{elapsed:.0f}s）"


def missing_env_names(env: dict, section: str) -> list[str]:
    """Which credential variables are missing, by exact name (no 「和/或」 ambiguity)."""
    if section == "llm":
        names = ("LLM_BASE_URL", "LLM_API_KEY")
    else:
        names = ("EMBEDDING_BASE_URL", "EMBEDDING_API_KEY")
    return [name for name in names if not str(env.get(name) or "").strip()]


def missing_env_text(env: dict, section: str) -> str:
    missing = missing_env_names(env, section)
    return "、".join(missing) if missing else "（无）"


def mode_needs_llm(mode: str) -> bool:
    if mode == "full":
        return True
    if mode != "custom":
        return False
    selected = CFG["custom"]
    return any(selected.get(key) for key in ("auto_memory", "auto_memory_cc", "auto_resource", "auto_dream", "chat"))


def llm_ready() -> bool:
    env = read_env_values()
    if env.get("LLM_BACKEND", "").casefold() == "ollama":
        return True
    return bool(env.get("LLM_API_KEY") and env.get("LLM_BASE_URL"))


def embedding_ready() -> bool:
    env = read_env_values()
    return bool(env.get("EMBEDDING_API_KEY") and env.get("EMBEDDING_BASE_URL"))


def validate_install(mode: str | None = None) -> tuple[bool, str]:
    selected = mode or CFG["mode"]
    root = reme_root()
    exe = reme_exe()
    python = reme_python()
    config = mode_config_path(selected)
    if not root.is_dir():
        return False, f"ReMe目录不存在：{root}"
    if not exe.is_file():
        return False, f"找不到命令：{exe}"
    if not python.is_file():
        return False, f"找不到ReMe虚拟环境Python：{python}"
    if mode_needs_llm(selected):
        # 保存/启动前先拦住：非法档位的失败发生在本地组件构造，日志里只是一串
        # pydantic 报错，用户很难自己连回到"思考强度选错了"。
        effort = str((CFG.get("llm") or {}).get("reasoning_effort") or "").strip()
        allowed = effort_options()[0]
        if not effort_is_allowed(effort, allowed):
            return False, (
                f"思考强度“{effort}”不被当前后台（{llm_backend_name()}）接受。\n\n"
                "ReMe 把 reasoning_effort 交给 agentscope 校验，取值是固定集合；填错了会在"
                "启动时直接失败（连网络请求都发不出去）。\n"
                f"当前可用：{'、'.join(allowed) if allowed else '（该后台不支持这一项，请选“不设置”）'}\n"
                "请在【LLM 与模型】里重新选择后再保存。"
            )
    # 三份配置全部由官方 default.yaml 推导：别人装了官方 ReMe 时 config/ 里一份都没有，
    # 这里就是它们的来源。自定义模式每次都重生成（功能开关随时可改）；基础/完整两份是
    # 固定预设，同样按当前设置重写 —— 以前它们是从不更新的预置文件，界面上改整理参数
    # 在服务端根本不生效。
    try:
        generate_mode_config(selected, config)
    except FileNotFoundError:
        pass          # 官方配置还没装出来：让下面的存在性检查给出可读的报错
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return False, f"{MODE_NAMES[selected]}配置生成失败：{exc}"
    if not config.is_file():
        return False, f"配置不存在：{config}"
    try:
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("根节点不是对象")
    except Exception as exc:
        return False, f"配置解析失败：{exc}"
    if mode_needs_llm(selected) and not llm_ready():
        missing = missing_env_text(read_env_values(), "llm")
        return False, (
            f"该模式需要 LLM，但 {reme_root() / '.env'} 中以下变量未填写：{missing}\n\n"
            "请点击“写入 .env”写入，或直接在【LLM 与模型】里填写。\n"
            "（本地无鉴权网关可随便填一个 Key，例如 sk-local）"
        )
    if selected == "custom" and CFG["custom"].get("embedding") and not embedding_ready():
        missing = missing_env_text(read_env_values(), "embedding")
        return False, (
            f"Embedding 已启用，但 {reme_root() / '.env'} 中以下变量未填写：{missing}\n\n"
            "请填写后点“写入 .env”，并先用“测试 Embedding”验证。"
        )
    try:
        result = subprocess.run(
            [str(python), "-c", "import importlib.metadata; print(importlib.metadata.version('reme-ai'))"],
            cwd=str(root),
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=15,
        )
        version = result.stdout.strip()
        if result.returncode != 0 or not version:
            return False, f"ReMe版本校验失败：{result.stdout.strip()[-300:]}"
    except Exception as exc:
        return False, f"ReMe命令校验失败：{exc}"
    return True, f"{MODE_NAMES[selected]}配置有效（ReMe {version}）"


def env_value_survives_interpolation(value: str) -> bool:
    """True when ReMe's post-substitution coercion returns this value unchanged.

    ReMe expands `${ENV}` inside the already-parsed string and then runs the
    result through `_convert_value` (reme/config/config_parser.py), which turns
    "123" into int, "true" into bool, "[a]" into a list. Quoting the placeholder
    in YAML does not help: the quotes are consumed by the YAML parser before
    expansion, so the coercion still sees the bare number.
    """
    text = str(value).strip()
    if not text:
        return True
    if text.casefold() in ("none", "null", "true", "false"):
        return False
    if text[0] in "[{\"":
        return False
    for cast in (int, float):
        try:
            cast(text)
        except ValueError:
            continue
        return False
    return True


def credential_field(env_name: str, value: str, placeholder: str) -> str:
    """YAML value for one credential field.

    Keeps the `${ENV}` placeholder while the value survives ReMe's coercion, so
    `.env` stays the single place credentials live. A value that would be retyped
    (a purely numeric API key, say) is written as a literal instead — PyYAML then
    quotes it and ReMe never passes a placeholder-free scalar through
    `_convert_value`. That is what makes an arbitrary API key safe.
    """
    text = str(value or "").strip()
    if not text or env_value_survives_interpolation(text):
        return placeholder
    log(f"credential {env_name}: value would be retyped by ReMe, inlined as a YAML literal")
    return text


_OFFICIAL_CONFIG_CACHE: dict = {"key": None, "config": {}}


def official_default_config() -> dict:
    """官方 default.yaml 的完整配置（带 mtime 缓存）。"""
    source = official_default_path()
    try:
        key = (str(source), source.stat().st_mtime_ns)
    except OSError:
        key = (str(source), None)
    if _OFFICIAL_CONFIG_CACHE["key"] != key:
        if not source.is_file():
            raise FileNotFoundError(f"官方default配置不存在：{source}")
        config = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise ValueError(f"官方default配置结构异常：{source}")
        _OFFICIAL_CONFIG_CACHE["key"] = key
        _OFFICIAL_CONFIG_CACHE["config"] = config
    return deep_copy(_OFFICIAL_CONFIG_CACHE["config"])


def local_config_overrides(selected: dict) -> dict:
    """三份配置共用的本机覆盖项：路径、时区、语言、服务地址。"""
    return {
        "app_name": "ReMe",
        "enable_logo": False,
        "workspace_dir": (reme_root() / "workspace").as_posix(),
        "timezone": "Asia/Shanghai",
        "language": "zh",
        "service": {
            "backend": "http",
            "host": "127.0.0.1",
            "port": 2333,
            "web_enabled": bool(selected.get("studio")),
            "mcp_enabled": bool(selected.get("mcp")),
            "mcp_path": "/mcp",
        },
    }


def apply_llm_settings(config: dict, env: dict) -> None:
    """把界面上的 LLM 参数与凭据写进 ``components.as_llm.default``。

    **凭据必须显式覆盖**：官方 default.yaml 里是裸写的 ``${LLM_API_KEY:-}``，纯数字
    Key 会在 ReMe 插值后被改成 int，as_llm 在组件构造时就校验类型，整个服务起不来。
    """
    default_llm = ((config.get("components") or {}).get("as_llm") or {}).get("default")
    if not isinstance(default_llm, dict):
        return
    llm = llm_values()
    parameters = dict(default_llm.get("parameters") or {})
    parameters["max_tokens"] = llm["max_tokens"]
    parameters["thinking_enable"] = llm["thinking_enable"]
    effort = llm["reasoning_effort"]
    if effort and not effort_is_allowed(effort, effort_options()[0]):
        # 绝不把 ReMe 会拒绝的值写进配置：as_llm 在**组件构造**时就校验 reasoning_effort
        # （pydantic Literal），一个网络包都发不出去，整个服务直接起不来。
        log(f"reasoning_effort {effort!r} not accepted by backend "
            f"{llm_backend_name()}; omitted from generated config")
        effort = ""
    if effort:
        parameters["reasoning_effort"] = effort
    default_llm["parameters"] = parameters
    default_llm["credential"] = {
        "api_key": credential_field("LLM_API_KEY", env.get("LLM_API_KEY", ""), "${LLM_API_KEY:-}"),
        "base_url": credential_field("LLM_BASE_URL",
                                     env.get("LLM_BASE_URL") or llm["base_url"], "${LLM_BASE_URL:-}"),
    }


def apply_wrapper_credentials(config: dict, env: dict) -> None:
    """同一类坑：agent_wrapper 的 claude_code / codex 也用裸 ``${...}`` 写凭据。

    保留原占位符文本（含它自己的 ``:-`` 默认值），只在值会被改型时写死字面量。
    """
    wrappers = ((config.get("components") or {}).get("agent_wrapper") or {})
    for wrapper_name, env_prefix in (("claude_code", "CLAUDE_CODE"),
                                     ("codex", "CODEX"), ("codex_oauth", "CODEX")):
        wrapper = wrappers.get(wrapper_name)
        if not isinstance(wrapper, dict):
            continue
        for field, suffix in (("api_key", "API_KEY"), ("base_url", "BASE_URL")):
            placeholder = wrapper.get(field)
            if isinstance(placeholder, str) and placeholder.startswith("${"):
                env_name = f"{env_prefix}_{suffix}"
                wrapper[field] = credential_field(env_name, env.get(env_name, ""), placeholder)


def apply_pipeline_settings(config: dict) -> None:
    """把整理参数（扫描天数 / 单次上限 / cron）写进 dream_cron 与 auto_dream。

    写的是**整份 job**（从官方配置取来再打补丁），不是片段：``extends`` 的深合并对
    列表是整体替换，只写半截 steps 会把继承来的其它步骤弄丢。
    """
    pipe = pipeline_values()
    jobs = config.setdefault("jobs", {})
    for job_name in ("dream_cron", "auto_dream"):
        job = jobs.get(job_name)
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("backend") == "dream_extract_step":
                step["scan_days"] = pipe["scan_days"]
                step["max_units"] = pipe["max_units"]
        properties = ((job.get("parameters") or {}).get("properties") or {})
        for key, value in (("scan_days", pipe["scan_days"]), ("max_units", pipe["max_units"])):
            if isinstance(properties.get(key), dict):
                properties[key]["default"] = value
    dream_cron = jobs.get("dream_cron")
    if isinstance(dream_cron, dict):
        dream_cron["cron"] = pipe["dream_cron"]


def generate_full_config(destination: Path | None = None) -> Path:
    """全功能模式：``extends: default`` + 本机覆盖项。

    继承官方 default，所以升级后天然跟随新版；但**凭据、LLM 参数与整理参数必须显式
    覆盖**——不覆盖的话，界面上的这些字段在服务端根本不生效（以前这份配置是手写的，
    一直没被重新生成过，改它们等于没改）。
    """
    env = read_env_values()
    config: dict = {"extends": "default"}
    config.update(local_config_overrides(preset_features("full")))
    official = official_default_config()
    jobs = official.get("jobs") or {}
    # 只带需要打补丁的两个 job；其余全部继承，保持这份配置短小
    config["jobs"] = {name: deep_copy(jobs[name])
                      for name in ("dream_cron", "auto_dream") if isinstance(jobs.get(name), dict)}
    apply_pipeline_settings(config)
    components = {"as_llm": {"default": {"parameters": {}, "credential": {}}}}
    wrappers = ((official.get("components") or {}).get("agent_wrapper") or {})
    if wrappers:
        components["agent_wrapper"] = deep_copy(wrappers)
    config["components"] = components
    apply_llm_settings(config, env)
    apply_wrapper_credentials(config, env)

    target = destination or mode_config_path("full")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target


def generate_mode_config(mode: str, destination: Path | None = None) -> Path:
    """按模式生成配置，三份都从**官方 default.yaml 推导**。

    基础模式与自定义模式是同一套逻辑换一组功能开关（实测与旧脚本产出的 app.yaml
    零差异）；全功能模式继承官方 default。ReMe 目录里因此不需要预置任何东西——
    别人装了官方 ReMe 也能用，升级后重新生成即可，没有本地脚本要维护。
    """
    if mode == "full":
        return generate_full_config(destination)
    config = official_default_config()
    selected = CFG["custom"] if mode == "custom" else preset_features(mode)
    env = read_env_values()
    jobs = config.get("jobs", {})
    removals = custom_job_removals(selected)
    config["jobs"] = {name: value for name, value in jobs.items() if name not in removals}

    components = config.setdefault("components", {})
    llm_needed = mode_needs_llm(mode)
    if not llm_needed:
        components.pop("as_llm", None)
        components.pop("agent_wrapper", None)
    if selected.get("embedding"):
        emb = embedding_values()
        components["as_embedding"] = {
            "default": {
                "backend": "openai",
                "model": emb["model"],
                "dimensions": emb["dimensions"],
                "credential": {
                    "api_key": credential_field("EMBEDDING_API_KEY", env.get("EMBEDDING_API_KEY", ""), "${EMBEDDING_API_KEY}"),
                    "base_url": credential_field("EMBEDDING_BASE_URL", env.get("EMBEDDING_BASE_URL") or emb["base_url"], "${EMBEDDING_BASE_URL}"),
                },
                "parameters": {},
            }
        }
        components["embedding_store"] = {"default": {"backend": "local", "as_embedding": "default"}}
        components["file_store"]["default"]["embedding_store"] = "default"
        components["file_store"]["default"]["backend"] = "faiss" if selected.get("faiss") else "local"
    else:
        components.pop("as_embedding", None)
        components.pop("embedding_store", None)
        components["file_store"]["default"]["embedding_store"] = ""
        components["file_store"]["default"]["backend"] = "local"

    config.update(local_config_overrides(selected))

    if llm_needed:
        apply_llm_settings(config, env)
    apply_wrapper_credentials(config, env)
    apply_pipeline_settings(config)

    expose = expose_values()
    if expose["custom"]:
        # 只写**这份配置里真正存在、且服务层加得进去**的名字。base_service.add_jobs()
        # 对白名单里的陌生名字是 raise KeyError，对加不进去的名字是 raise TypeError，
        # 两种都会让 ReMe 起不来；宁可少写几个，也不能把服务写崩。
        effective = config.get("jobs") or {}
        allowed = [name for name in expose["jobs"]
                   if name in effective and is_servable(effective.get(name))]
        dropped = [name for name in expose["jobs"] if name not in allowed]
        if dropped:
            log(f"expose allowlist: dropped jobs that do not exist in this config: {dropped}")
        if allowed:
            config["service"]["jobs"] = allowed
        else:
            # 一项都没勾＝不写白名单＝全部对外开放（界面上是这么说的，这里保持一致）
            log("expose allowlist is empty after validation; not writing service.jobs")

    target = destination or mode_config_path(mode)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target


def generate_custom_config(destination: Path | None = None) -> Path:
    """旧名字，保留给已有调用点与测试（等价于生成自定义模式）。"""
    return generate_mode_config("custom", destination)


STATE_LOCK = threading.RLock()
ACTION_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
STATE = {"phase": "stopped", "healthy": False, "pid": None, "managed": False, "message": ""}
SERVICE_PROCESS: subprocess.Popen | None = None
SERVICE_LOG_HANDLE = None
SETTINGS_ROOT = None
AUX_WINDOWS: list = []   # 非控制台的辅助窗口（路径指引 / 说明文档）
GUIDE_WINDOW: dict = {"win": None}   # 「路径与入口」窗口：语言一变就整体重建
TUNNEL_PROCS: dict[str, subprocess.Popen] = {}
TUNNEL_STATE: dict[str, bool] = {}
# 用户希望这条隧道是连着的（连过一次就为 True；手动停止置 False）。
# 健康检查据此决定要不要把掉线的隧道接回来，而不是无脑重启用户刚停掉的隧道。
TUNNEL_WANTED: dict[str, bool] = {}
TRAY_ICON = None

# ---------------- UI 线程：整个进程只用一个 Tk 解释器 ----------------
# Tk 对象与创建它的线程绑定，而托盘回调跑在 pystray 自己的线程上。跨线程碰 Tcl 有两种
# 致命后果：调用方（托盘线程）会卡死在 Tcl_ConditionWait 里永不返回；隐式默认根窗口
# 会把 ttk.Style()/Toplevel()/StringVar() 引到别的解释器上，抛 “main thread is not in
# main loop”，窗口建到一半就死掉——这两种都会表现为「点控制台没反应」。
# 规则：
#   * 只有 UI 线程碰 Tk，其它线程一律通过 ui_post() 投递请求（只碰 Python 队列）；
#   * Tk 解释器只创建一次并常驻，语言/主题切换只重建窗口内容，不重建解释器。
UI_LOCK = threading.Lock()
UI_QUEUE: queue.Queue = queue.Queue()
UI_HOST: dict = {"root": None, "thread": None, "win": None, "ready": threading.Event(), "error": ""}
UI_ERRORS: list = []          # UI 线程里被捕获的异常（测试与 --ui-check 用它当红灯）


def in_ui_thread() -> bool:
    """当前线程是否是 UI 线程（唯一允许直接操作 Tk 的线程）。"""
    thread = UI_HOST.get("thread")
    return thread is not None and threading.current_thread() is thread


def ui_post(work) -> None:
    """从任意线程投递一个「在 UI 线程里执行」的请求，由 UI 线程稍后执行。"""
    start_ui_thread()
    UI_QUEUE.put(work)


def start_ui_thread(wait: float = 20.0) -> None:
    """按需启动 UI 线程（进程内唯一）。"""
    with UI_LOCK:
        thread = UI_HOST.get("thread")
        if thread is not None and thread.is_alive():
            return
        UI_HOST["ready"].clear()
        UI_HOST["error"] = ""
        thread = threading.Thread(target=ui_thread_main, name="reme-helper-ui", daemon=True)
        UI_HOST["thread"] = thread
        thread.start()
    UI_HOST["ready"].wait(wait)


def report_ui_exception(exc_type, exc_value, exc_tb) -> None:
    """Tk 回调里的未捕获异常：进日志，绝不让窗口悄悄死掉。"""
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    UI_ERRORS.append(detail)
    try:
        log("unhandled error in a UI callback:\n" + detail)
    except Exception:  # noqa: BLE001
        pass


def ui_call(work, timeout: float = 20.0):
    """在 UI 线程里执行 work 并等它返回结果（测试与需要同步结果的调用用）。

    和 ui_post 一样只碰 Python 队列，唯一区别是等结果：绝不在调用线程碰 Tcl。
    """
    box: dict = {}
    done = threading.Event()

    def wrapper() -> None:
        try:
            box["value"] = work()
        except Exception as exc:  # noqa: BLE001 - 交回调用方
            box["error"] = exc
        finally:
            done.set()

    if in_ui_thread():
        wrapper()
    else:
        ui_post(wrapper)
        if not done.wait(timeout):
            raise TimeoutError("UI 线程没有在限定时间内响应")

    if "error" in box:
        raise box["error"]
    return box.get("value")


def console_widgets(include_aux: bool = True) -> list[dict]:
    """当前控制台里每个控件的类型/文字/颜色/几何（主题一致性与布局测试用）。

    ``include_aux`` 为 False 时只看控制台窗口本身，用于严格的布局比对
    （辅助窗口和主窗口的 Toplevel/TFrame 在按类型归并时会撞在一起）。
    """
    def collect() -> list[dict]:
        roots = [UI_HOST.get("win")] + (list(AUX_WINDOWS) if include_aux else [])
        stack = [widget for widget in roots if widget is not None]
        if not stack:
            return []
        out: list[dict] = []
        while stack:
            widget = stack.pop()
            try:
                cls = widget.winfo_class()
            except tk.TclError:
                continue
            try:
                mapped = bool(widget.winfo_ismapped())
            except tk.TclError:
                mapped = False
            item = {"class": cls, "text": "", "fg": "", "bg": "", "mapped": mapped,
                    "x": widget.winfo_rootx(), "y": widget.winfo_rooty(),
                    "w": widget.winfo_width(), "h": widget.winfo_height()}
            try:
                if cls in ("Label", "Button", "Checkbutton", "Radiobutton",
                           "TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TLabelframe"):
                    item["text"] = str(widget.cget("text"))
                elif cls in ("TCombobox", "Combobox"):
                    item["text"] = str(widget.get())
            except tk.TclError:
                pass
            try:
                item["fg"] = str(widget.cget("foreground"))
                item["bg"] = str(widget.cget("background"))
            except tk.TclError:
                pass
            out.append(item)
            try:
                stack.extend(widget.winfo_children())
            except tk.TclError:
                pass
        return out

    return ui_call(collect)


def console_texts() -> list[tuple[str, str]]:
    """当前控制台里所有控件的文字（测试/英文模式审查用）。

    返回 [(控件类, 文字)]：标签、按钮、勾选/单选、下拉框选项与当前值、表格表头与行。
    """
    def collect() -> list[tuple[str, str]]:
        roots = [UI_HOST.get("win")] + list(AUX_WINDOWS)
        stack = [widget for widget in roots if widget is not None]
        if not stack:
            return []
        out: list[tuple[str, str]] = []
        while stack:
            widget = stack.pop()
            try:
                cls = widget.winfo_class()
            except tk.TclError:
                continue
            try:
                if cls in ("Label", "Button", "Checkbutton", "Radiobutton",
                           "TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TLabelframe"):
                    value = str(widget.cget("text"))
                    if value:
                        out.append((cls, value))
                elif cls == "Text":
                    body = str(widget.get("1.0", "end"))
                    if body.strip():
                        out.append((cls, body[:6000]))
                elif cls in ("TCombobox", "Combobox"):
                    out.append((cls, str(widget.get())))
                    out.extend((cls, str(option)) for option in (widget.cget("values") or []))
                elif cls == "Treeview":
                    for column in widget.cget("columns"):
                        out.append(("Treeview.heading", str(widget.heading(column, "text"))))
                    for item in widget.get_children():
                        out.extend(("Treeview.row", str(value)) for value in widget.item(item, "values"))
            except tk.TclError:
                pass
            try:
                stack.extend(widget.winfo_children())
            except tk.TclError:
                pass
        return out

    return ui_call(collect)


def ui_parent():
    """对话框的父窗口：优先控制台，否则用隐藏的根窗口。"""
    win = UI_HOST.get("win")
    try:
        if win is not None and win.winfo_exists():
            return win
    except tk.TclError:
        pass
    return UI_HOST.get("root")


def ui_thread_main() -> None:
    """UI 线程主体：创建唯一的 Tk 解释器（隐藏的根窗口），然后循环处理请求队列。"""
    try:
        host = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - reported to whoever is waiting
        UI_HOST["error"] = f"{type(exc).__name__}: {exc}"
        log(f"ui: cannot create the Tk interpreter: {exc}")
        UI_HOST["ready"].set()
        return
    host.withdraw()
    host.title(app_title())
    host.report_callback_exception = report_ui_exception
    apply_window_icon(host)
    UI_HOST["root"] = host
    UI_THREADS[:] = [threading.current_thread()]   # 只保留当前 UI 线程，避免残留已死线程
    apply_theme()
    UI_HOST["ready"].set()
    pump_ui_requests()
    log("ui: interpreter ready")
    host.mainloop()
    log("ui: window loop ended")


def run_theme_hooks() -> None:
    """主题切换后调用登记的钩子（说明文档的 tag 颜色等）。"""
    for hook in list(THEME_HOOKS):
        try:
            hook()
        except Exception as exc:  # noqa: BLE001 - 钩子失败不该影响主题切换
            log(f"theme hook failed: {exc}")
            if hook in THEME_HOOKS:
                THEME_HOOKS.remove(hook)


def restyle_all() -> None:
    """把当前主题铺到所有窗口的普通 tk 控件上，并跑一遍主题钩子。"""
    host = UI_HOST.get("root")
    if host is not None:
        try:
            if host.winfo_exists():
                restyle_widgets(host)     # host 的子窗口包含控制台与指引/说明
        except tk.TclError:
            pass
    run_theme_hooks()


def apply_pending_theme() -> None:
    """把挂起的主题切换在当前（UI）线程里落地。

    托盘切主题时只是置了 PENDING_THEME，由**控制台窗口**的轮询负责落地；如果这时控制台
    没开着，就没人消费它——接着打开的「打开指引」/说明文档/VM 对话框会用旧样式，看着还是
    上一个主题的样子（用户报的「切了深色，指引还是浅色」）。所以进入 UI 线程的请求泵里先补上。
    """
    if PENDING_THEME["dirty"]:
        PENDING_THEME["dirty"] = False
        apply_theme()
        restyle_all()


def pump_ui_requests() -> None:
    """在 UI 线程里排空请求队列。"""
    host = UI_HOST.get("root")
    if host is None:
        return
    apply_pending_theme()   # 每一轮都先落地挂起的主题（队列空时也要生效）
    while True:
        try:
            work = UI_QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            work()
        except Exception as exc:  # noqa: BLE001 - one bad request must not kill the thread
            UI_ERRORS.append(f"{type(exc).__name__}: {exc}")
            log(f"ui request failed: {type(exc).__name__}: {exc}")
            log(traceback.format_exc())
    try:
        host.after(80, pump_ui_requests)
    except tk.TclError:
        pass


def state_copy() -> dict:
    with STATE_LOCK:
        return dict(STATE)


def service_is_healthy() -> bool:
    """Return the monitor's cached result without blocking the tray UI."""
    return bool(state_copy().get("healthy"))


def set_state(**values) -> None:
    with STATE_LOCK:
        STATE.update(values)


def health_url() -> str:
    return "http://127.0.0.1:2333/health_check"


def probe_health(timeout: float = 3.0) -> bool:
    request = urllib.request.Request(
        health_url(), data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        answer = str(data.get("answer") or "")
        version = str((data.get("metadata") or {}).get("health", {}).get("version") or "")
        return response.status == 200 and bool(data.get("success")) and ("ReMe" in answer or bool(version))
    except (OSError, ValueError, urllib.error.URLError):
        return False


def service_up(timeout: float = 3.0) -> bool:
    """ReMe 现在是否真的在跑 —— 直接探测，而不是读监控缓存。

    ``service_is_healthy()`` 返回的是监控线程缓存的状态（不阻塞托盘），在刚启动、
    监控还没跑完第一轮时是 False。判断「能不能开隧道」这种要立刻做决定的地方，
    必须看实况：隧道完全可以连上一个健康、但不由本工具托管的 ReMe。
    """
    return probe_health(timeout)


def matching_reme_processes() -> list[psutil.Process]:
    root = str(reme_root()).casefold()
    found = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            command = " ".join(proc.info.get("cmdline") or []).casefold()
            if root in command and "reme" in command and "start" in command:
                found.append(proc)
        except (psutil.Error, OSError):
            continue
    return found


def refresh_service_state() -> None:
    healthy = probe_health()
    processes = matching_reme_processes()
    pid = processes[0].pid if processes else None
    phase = "running" if healthy else "stopped"
    if processes and not healthy:
        phase = "error"
    set_state(phase=phase, healthy=healthy, pid=pid, managed=bool(SERVICE_PROCESS), message="")


def wait_for_health(expected: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_health(1.5) is expected:
            return True
        time.sleep(0.5)
    return False


def terminate_process_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        children = root.children(recursive=True)
        for proc in reversed(children):
            with proc.oneshot():
                proc.terminate()
        root.terminate()
        _, alive = psutil.wait_procs([*children, root], timeout=8)
        for proc in alive:
            proc.kill()
    except psutil.NoSuchProcess:
        return
    except psutil.Error as exc:
        log(f"process termination failed pid={pid}: {exc}")


def start_service(mode: str | None = None) -> tuple[bool, str]:
    global SERVICE_PROCESS, SERVICE_LOG_HANDLE
    selected = mode or CFG["mode"]
    valid, detail = validate_install(selected)
    if not valid:
        return False, detail
    if probe_health():
        refresh_service_state()
        return True, "ReMe已经运行"
    config = mode_config_path(selected)
    log_file = reme_root() / "logs" / f"reme-{time.strftime('%Y%m%d')}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_LOG_HANDLE = log_file.open("a", encoding="utf-8")
    command = [str(reme_exe()), "start", f"config={config.as_posix()}"]
    env = {**os.environ, "PYTHONUTF8": "1"}
    set_state(phase="starting", message=MODE_NAMES[selected])
    try:
        SERVICE_PROCESS = subprocess.Popen(
            command,
            cwd=str(reme_root()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=SERVICE_LOG_HANDLE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        SERVICE_LOG_HANDLE.close()
        SERVICE_LOG_HANDLE = None
        SERVICE_PROCESS = None
        set_state(phase="error", message=str(exc))
        return False, f"启动失败：{exc}"
    if not wait_for_health(True, 35):
        code = SERVICE_PROCESS.poll()
        if code is None:
            terminate_process_tree(SERVICE_PROCESS.pid)
        SERVICE_PROCESS = None
        if SERVICE_LOG_HANDLE:
            SERVICE_LOG_HANDLE.close()
            SERVICE_LOG_HANDLE = None
        set_state(phase="error", message="health timeout")
        return False, f"启动后健康检查失败，请查看{log_file}"
    set_state(phase="running", healthy=True, pid=SERVICE_PROCESS.pid, managed=True, message="")
    log(f"ReMe started mode={selected} pid={SERVICE_PROCESS.pid} config={config}")
    if CFG.get("start_tunnels_with_reme"):
        start_all_tunnels()
    return True, f"ReMe 已启动（{MODE_NAMES[selected]}）"


def stop_service() -> tuple[bool, str]:
    global SERVICE_PROCESS, SERVICE_LOG_HANDLE
    stop_all_tunnels()
    processes = matching_reme_processes()
    if not processes and not probe_health():
        set_state(phase="stopped", healthy=False, pid=None, managed=False, message="")
        return True, "ReMe已经停止"
    set_state(phase="stopping")
    for proc in processes:
        terminate_process_tree(proc.pid)
    if SERVICE_PROCESS and SERVICE_PROCESS.poll() is None:
        terminate_process_tree(SERVICE_PROCESS.pid)
    wait_for_health(False, 10)
    SERVICE_PROCESS = None
    if SERVICE_LOG_HANDLE:
        SERVICE_LOG_HANDLE.close()
        SERVICE_LOG_HANDLE = None
    healthy = probe_health()
    set_state(phase="error" if healthy else "stopped", healthy=healthy, pid=None, managed=False)
    return (not healthy), ("停止失败，2333端口仍响应" if healthy else "ReMe已停止")


def restart_service() -> tuple[bool, str]:
    stop_service()
    return start_service()


def switch_mode(mode: str) -> tuple[bool, str]:
    old = CFG["mode"]
    if mode == old:
        return True, f"当前已经是{MODE_NAMES[mode]}"
    valid, detail = validate_install(mode)
    if not valid:
        return False, detail
    was_running = probe_health()
    if was_running:
        ok, stop_detail = stop_service()
        if not ok:
            return False, stop_detail
    CFG["mode"] = mode
    if was_running:
        ok, start_detail = start_service(mode)
        if not ok:
            CFG["mode"] = old
            restored, restore_detail = start_service(old)
            return False, f"新模式启动失败：{start_detail}；旧模式恢复：{restore_detail if restored else '失败'}"
    save_config()
    return True, f"已切换到{MODE_NAMES[mode]}" + ("并重新启动" if was_running else "")


def target_key(target: dict) -> str:
    return f"{target.get('user','')}@{target.get('host','')}:{target.get('port',22)}:{target.get('remote_port',22333)}"


def target_connection(target: dict) -> str:
    return f"{target['user']}@{target['host']}" if target.get("user") else target["host"]


def ssh_command(target: dict, remote_command: str | None = None) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(target.get("port", 22)),
    ]
    if target.get("key"):
        command += ["-i", str(Path(target["key"]).expanduser())]
    if remote_command is None:
        command += [
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=20",
            "-o",
            "ServerAliveCountMax=3",
            "-N",
            "-R",
            f"127.0.0.1:{int(target.get('remote_port',22333))}:127.0.0.1:2333",
            target_connection(target),
        ]
    else:
        command += [target_connection(target), remote_command]
    return command


def probe_tunnel(target: dict) -> bool:
    remote = (
        f"curl -sf --max-time 5 -H 'Content-Type: application/json' -d '{{}}' "
        f"http://127.0.0.1:{int(target.get('remote_port',22333))}/health_check"
    )
    try:
        result = subprocess.run(
            ssh_command(target, remote),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=15,
        )
        return result.returncode == 0 and '"success":true' in result.stdout.replace(" ", "").lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def start_tunnel(target: dict) -> tuple[bool, str]:
    key = target_key(target)
    if not probe_health():
        return False, "ReMe尚未运行"
    # 进入这里就是「希望它连着」；随后调用的 stop_tunnel 会清掉这个标记，所以要在这里先立起来。
    TUNNEL_WANTED[key] = True
    if probe_tunnel(target):
        TUNNEL_STATE[key] = True
        return True, f"{target['name']}隧道已经连接"
    stop_tunnel(target)
    TUNNEL_WANTED[key] = True
    try:
        process = subprocess.Popen(
            ssh_command(target),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        TUNNEL_PROCS[key] = process
    except OSError as exc:
        return False, f"SSH启动失败：{exc}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None:
        if probe_tunnel(target):
            TUNNEL_STATE[key] = True
            log(f"tunnel started target={key} pid={process.pid}")
            return True, f"{target['name']}隧道已连接"
        time.sleep(1)
    stop_tunnel(target)
    return False, f"{target['name']}隧道连接失败，请检查SSH密钥和VM"


def stop_tunnel(target: dict) -> None:
    """停隧道，并记下「这是用户主动停的」。

    没有这个标记的话，健康检查会把它当成掉线又拉起来——用户点了「停止」却看到隧道
    自己回来了。标记由 start_tunnel 清除。
    """
    key = target_key(target)
    TUNNEL_WANTED[key] = False
    process = TUNNEL_PROCS.pop(key, None)
    if process and process.poll() is None:
        terminate_process_tree(process.pid)
    mapping = f"127.0.0.1:{int(target.get('remote_port',22333))}:127.0.0.1:2333"
    connection = target_connection(target)
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            command = " ".join(proc.info.get("cmdline") or [])
            if mapping in command and connection in command and (proc.info.get("name") or "").lower().startswith("ssh"):
                terminate_process_tree(proc.pid)
        except (psutil.Error, OSError):
            continue
    TUNNEL_STATE[key] = False


def start_all_tunnels() -> tuple[bool, str]:
    targets = [target for target in CFG["targets"] if target.get("enabled", True)]
    if not targets:
        return False, "没有启用的VM目标"
    failures = []
    for target in targets:
        ok, detail = start_tunnel(target)
        if not ok:
            failures.append(detail)
    return (not failures), ("全部隧道已连接" if not failures else "；".join(failures))


def stop_all_tunnels() -> tuple[bool, str]:
    for target in CFG.get("targets", []):
        stop_tunnel(target)
    return True, "VM隧道已停止"


def refresh_tunnels() -> None:
    """每轮健康检查调用：更新隧道状态，并把掉线的隧道拉回来。

    以前这里只**看**状态，于是有两种情况会让隧道一直是断的：
    ① ssh 进程中途消失（网络抖动、VM 重启、被系统回收）；
    ② 工具启动时 ReMe 已经在跑 —— ``start_service`` 会提前返回，挂在它后面的
       「启动隧道」分支根本不执行，「ReMe 启动后启动隧道」这个勾选项等于失效，
       用户得自己去托盘点一次。

    现在用 TUNNEL_WANTED 记住「这条隧道应该是连着的」：首次（由 seed_tunnels_wanted
    按配置播种）或掉线之后，只要 ReMe 健康就接回去。用户手动停过的隧道不会被自动拉起。
    """
    for target in CFG.get("targets", []):
        key = target_key(target)
        process = TUNNEL_PROCS.get(key)
        if process and process.poll() is None:
            TUNNEL_STATE[key] = True
            continue
        if process:
            TUNNEL_PROCS.pop(key, None)
        was_up = TUNNEL_STATE.get(key, False)
        TUNNEL_STATE[key] = False
        if not target.get("enabled", True):
            continue
        if not TUNNEL_WANTED.get(key, False) and not was_up:
            continue
        if not service_up():
            continue
        # 它此前是连着的（或用户要求它连着）：这轮把它接回去
        TUNNEL_WANTED[key] = True
        ok, detail = start_tunnel(target)
        log(f"tunnel auto-reconnect target={key} ok={ok} detail={detail}")


def seed_tunnels_wanted() -> None:
    """启动时按配置播种「这些隧道应该连着」。

    只有打开了「ReMe启动后启动隧道」才播种；用户随后在托盘里单独停掉某条隧道，
    stop_tunnel 会把该目标的标记清掉，不会被这里重新拉起。
    """
    wanted = bool(CFG.get("start_tunnels_with_reme"))
    for target in CFG.get("targets", []):
        if target.get("enabled", True):
            TUNNEL_WANTED[target_key(target)] = wanted


def notify(message: str) -> None:
    log(message)
    if TRAY_ICON:
        try:
            TRAY_ICON.notify(message, t(APP_NAME))
        except Exception:
            pass


def run_action(function, refresh=True) -> None:
    def worker():
        if not ACTION_LOCK.acquire(blocking=False):
            notify("正在执行另一项操作")
            return
        try:
            ok, detail = function()
            notify(("成功：" if ok else "失败：") + detail)
        except Exception as exc:
            log(f"action failed: {exc}")
            notify(f"操作失败：{exc}")
        finally:
            ACTION_LOCK.release()
            if refresh:
                refresh_service_state()
                if TRAY_ICON:
                    refresh_tray_menu()
    threading.Thread(target=worker, daemon=True).start()


def open_path(path) -> None:
    target = str(path)
    if target.startswith(("http://", "https://")):
        webbrowser.open(target)
        return
    if Path(target).exists():
        os.startfile(target)
    else:
        notify(f"路径不存在：{target}")


def choose_from_list(parent, title: str, options: list[str], prompt: str) -> str | None:
    """Small modal picker used when a scan finds several candidates."""
    chosen: dict[str, str | None] = {"value": None}
    master = parent if parent is not None else ui_parent()
    dialog = tk.Toplevel(master)
    dialog.title(f"{t(APP_NAME)} · {title}")
    attach_dialog(master, dialog)
    dialog.grab_set()
    body = ttk.Frame(dialog, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=prompt, font=FONT_UI).pack(anchor="w", pady=(0, 8))
    box = tk.Listbox(body, height=min(len(options), 8), width=max(len(item) for item in options) + 2,
                     activestyle="none", font=FONT_UI)
    for option in options:
        box.insert("end", option)
    box.selection_set(0)
    box.pack(fill="both", expand=True)
    row = ttk.Frame(body)
    row.pack(fill="x", pady=(10, 0))

    def confirm(_event=None):
        selection = box.curselection()
        chosen["value"] = options[selection[0]] if selection else None
        dialog.destroy()

    ttk.Button(row, text="使用这个", command=confirm).pack(side="right")
    ttk.Button(row, text="取消", command=dialog.destroy).pack(side="right", padx=(0, 6))
    box.bind("<Double-Button-1>", confirm)
    dialog.wait_window()
    return chosen["value"]


SERVICE_PORT_TEXT = "2333"
# 随包文档的布局：doc/<lang>/setup.md + doc/<lang>/configuration.md，脚本共用一份 doc/capture.mjs。
# 只有一个 doc/ 目录——仓库里再放一个 docs/ 只会让人分不清「哪份是要发的、哪份是给人看的」。
INTEGRATION_DOC_NAME = "setup.md"
CONFIG_DOC_NAME = "configuration.md"
INTEGRATION_DOC_SCRIPT = "capture.mjs"
SETUP_GUIDE_MIN_CHARS = 20000


def doc_file_dir() -> Path:
    """随工具分发的文档目录（``doc/``）；打包后随 ``_internal`` 一起走。

    开发态在仓库根（``PACKAGE_DIR``），打包态在 exe 目录（``APP_DIR``）。
    """
    for candidate in (APP_DIR / "doc", APP_DIR / "_internal" / "doc", PACKAGE_DIR / "doc"):
        if candidate.is_dir():
            return candidate
    return APP_DIR / "doc"


def integration_doc_markdown() -> str:
    """接入文档正文：按界面语言取 ``doc/<lang>/setup.md``，并把附录 A 的捕获脚本拼在末尾。

    端口与 workspace 现场替换成当前配置的值；脚本在文件系统里只保留一份
    （``doc/capture.mjs``），复制时才拼接，避免两处内容漂移。
    """
    directory = doc_file_dir()
    lang = "en" if ui_lang() == "en" else "zh"
    path = directory / lang / INTEGRATION_DOC_NAME
    if not path.exists():
        fallback = directory / "zh" / INTEGRATION_DOC_NAME
        if fallback.exists():
            path = fallback
    if not path.exists():
        return t("接入文档缺失：请确认 doc 目录随工具一起分发。")
    body = path.read_text(encoding="utf-8")
    body = body.replace("<REME_PORT>", SERVICE_PORT_TEXT).replace(
        "<REME_WORKSPACE>", str(reme_root() / "workspace"))
    script = directory / INTEGRATION_DOC_SCRIPT
    if script.exists():
        body += "\n```javascript\n" + script.read_text(encoding="utf-8").rstrip() + "\n```\n"
    return body


def show_integration_doc() -> None:
    """在同一个内置窗口里阅读接入文档；要交给 AI 时用「复制接入文档」。"""
    show_doc_viewer(integration_doc_markdown, " · 接入 Agent 文档")


def copy_integration_doc() -> None:
    """把接入文档（含附录 A 脚本）放进剪贴板，提示粘贴给 AI。"""
    doc = integration_doc_markdown()
    if copy_to_clipboard(doc):
        toast("接入文档已复制：粘贴给 AI，让它照着把 Codex 与 DSH 接到 ReMe")
    else:
        notify(t("复制失败"))


def _console_guide_markdown() -> str:
    """控制台说明的正文（内容随工具分发，见 guide.py）。"""
    return guide.guide_markdown({
        "lang": ui_lang(),
        "reme_root": str(reme_root()),
        "mode_label": t(MODE_NAMES.get(CFG.get("mode"), CFG.get("mode") or "")),
        "config_path": str(mode_config_path()),
        "workspace": str(reme_root() / "workspace"),
        "env_path": str(reme_root() / ".env"),
        "logs": str(reme_root() / "logs"),
        "service_url": "http://127.0.0.1:2333/",
        "version": VERSION,
    })


def show_doc_viewer(build_markdown=None, title_suffix: str = " · 控制台说明") -> None:
    """在内置窗口里渲染控制台说明。

    内容随工具分发（``guide.py``），不再依赖 ReMe 安装目录里的 Markdown 文件——那份文件
    是某台机器上写的、普通用户装完 ReMe 并不会带着它，而且里面的路径不具备通用性。
    正文讲通用做法，只有「本机路径」那一节在打开时现场取值。
    """
    def ui():
        host = UI_HOST.get("root")
        if host is None:
            return
        root = tk.Toplevel(host)
        AUX_WINDOWS.append(root)   # 留住引用，避免被 GC 掉
        root.title(app_title() + t(title_suffix))
        markdown = (build_markdown or _console_guide_markdown)()
        root.geometry("1120x780")
        root.minsize(760, 520)
        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", padx=24, pady=18, borderwidth=0, cursor="arrow",
                       background=THEME["panel"], foreground=THEME["text"], insertbackground=THEME["text"])
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        base = ("Microsoft YaHei UI", 10)
        text.configure(font=base, spacing1=2, spacing3=4)
        text.tag_configure("h1", font=(base[0], 20, "bold"), spacing1=14, spacing3=10)
        text.tag_configure("h2", font=(base[0], 15, "bold"), spacing1=12, spacing3=7)
        text.tag_configure("h3", font=(base[0], 12, "bold"), spacing1=9, spacing3=5)
        text.tag_configure("bold", font=(base[0], base[1], "bold"))
        text.tag_configure("list", lmargin1=18, lmargin2=36)

        def apply_doc_tags() -> None:
            """说明文档里的代码块/引用/表格颜色跟着主题走（以前写死浅色，深色下看不清）。"""
            text.tag_configure("code", font=("Cascadia Mono", 9), background=THEME["code_bg"],
                               foreground=THEME["text"], lmargin1=18, lmargin2=18)
            text.tag_configure("quote", foreground=THEME["muted"], lmargin1=18, lmargin2=18)
            text.tag_configure("table", font=("Cascadia Mono", 9), background=THEME["table_bg"],
                               foreground=THEME["text"])

        apply_doc_tags()
        THEME_HOOKS.append(apply_doc_tags)
        root.bind("<Destroy>", lambda event: THEME_HOOKS.remove(apply_doc_tags)
                  if event.widget is root and apply_doc_tags in THEME_HOOKS else None)
        link_count = 0

        def insert_inline(line: str, base_tag: str | None = None):
            nonlocal link_count
            pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
            position = 0
            for match in pattern.finditer(line):
                text.insert("end", line[position:match.start()], base_tag)
                token = match.group(0)
                if token.startswith("**"):
                    text.insert("end", token[2:-2], (base_tag, "bold") if base_tag else "bold")
                elif token.startswith("`"):
                    text.insert("end", token[1:-1], (base_tag, "code") if base_tag else "code")
                else:
                    label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token).groups()
                    tag = f"link-{link_count}"
                    link_count += 1
                    text.tag_configure(tag, foreground=THEME["link"], underline=True)
                    text.tag_bind(tag, "<Enter>", lambda _e: text.configure(cursor="hand2"))
                    text.tag_bind(tag, "<Leave>", lambda _e: text.configure(cursor="arrow"))
                    text.tag_bind(tag, "<Button-1>", lambda _e, u=url: webbrowser.open(u))
                    text.insert("end", label, (base_tag, tag) if base_tag else tag)
                position = match.end()
            text.insert("end", line[position:], base_tag)

        in_code = False
        for raw in markdown.splitlines():
            if raw.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                text.insert("end", raw + "\n", "code")
            elif raw.startswith("### "):
                insert_inline(raw[4:], "h3"); text.insert("end", "\n")
            elif raw.startswith("## "):
                insert_inline(raw[3:], "h2"); text.insert("end", "\n")
            elif raw.startswith("# "):
                insert_inline(raw[2:], "h1"); text.insert("end", "\n")
            elif re.match(r"^\s*[-*+]\s+", raw):
                insert_inline("• " + re.sub(r"^\s*[-*+]\s+", "", raw), "list"); text.insert("end", "\n")
            elif re.match(r"^\s*\d+[.)]\s+", raw):
                insert_inline(raw.strip(), "list"); text.insert("end", "\n")
            elif raw.startswith("> "):
                insert_inline(raw[2:], "quote"); text.insert("end", "\n")
            elif raw.startswith("|") and raw.endswith("|"):
                if not re.match(r"^\|[\s:|-]+\|$", raw):
                    text.insert("end", "  ".join(cell.strip() for cell in raw.strip("|").split("|")) + "\n", "table")
            elif re.match(r"^\s*([-*_])\1\1+\s*$", raw):
                text.insert("end", "─" * 72 + "\n", "quote")
            else:
                insert_inline(raw); text.insert("end", "\n")
        text.configure(state="disabled")

    ui_post(ui)


def copy_to_clipboard(value: str) -> bool:
    """把文本放进剪贴板（必须在 UI 线程里调用：剪贴板要一个活着的 Tk 窗口）。"""
    host = UI_HOST.get("root")
    if host is None:
        return False
    try:
        host.clipboard_clear()
        host.clipboard_append(value)
        host.update_idletasks()
        return True
    except tk.TclError:
        return False


def path_guide_items() -> list[dict]:
    """「文件都在哪」的清单：名称、说明、路径、打开动作。"""
    root = reme_root()
    return [
        {"name": "ReMe 目录", "desc": "安装根目录，config / workspace / logs 都在下面",
         "path": root, "action": lambda: open_path(root)},
        {"name": "workspace", "desc": "你的记忆文件（Markdown），可以直接翻看或备份",
         "path": root / "workspace", "action": lambda: open_path(root / "workspace")},
        {"name": "当前配置", "desc": "控制台保存后生效的 app*.yaml；一般不用手改",
         "path": mode_config_path(), "action": lambda: open_path(mode_config_path())},
        {"name": "官方 default 配置", "desc": "ReMe 自带的默认配置，只读参考",
         "path": official_default_path(), "action": lambda: open_path(official_default_path())},
        {"name": ".env（凭据）", "desc": "LLM / Embedding 的地址与 Key，注意别外传",
         "path": root / ".env", "action": open_env_template},
        {"name": "日志目录", "desc": "出问题时看这里的 *.log",
         "path": root / "logs", "action": lambda: open_path(root / "logs")},
        {"name": "控制台说明", "desc": "内置的接入与排障说明（在窗口里打开，不依赖 ReMe 目录）",
         "path": "（内置文档）", "action": show_doc_viewer},
        {"name": "接入 Agent 文档", "desc": "怎么把 Codex、DSH 这些客户端接到 ReMe 上（可阅读，也可复制给 AI 照着做）",
         "path": "（内置文档）", "action": show_integration_doc},
    ]


def _copy_path(value: str) -> None:
    notify(t("已复制路径：") + value if copy_to_clipboard(value) else t("复制失败"))


def show_path_guide() -> None:
    """「路径与入口」窗口：替代托盘里堆着的一排「打开…」。"""
    ui_post(_open_path_guide)


def _open_path_guide() -> None:
    host = UI_HOST.get("root")
    if host is None:
        return
    apply_theme()
    items = path_guide_items()
    win = tk.Toplevel(host)
    AUX_WINDOWS.append(win)
    GUIDE_WINDOW["win"] = win
    win.bind("<Destroy>", lambda event: (GUIDE_WINDOW.update({"win": None})
                                         if event.widget is win else None))
    win.title(app_title() + t(" · 路径与入口"))
    win.geometry("1000x470")
    win.minsize(780, 380)
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=t("这些文件在哪、点一下就能打开；平时改配置请用控制台，这里只是帮你找到它们。"),
              font=FONT_UI, foreground=THEME["muted"], wraplength=920, justify="left").grid(
        row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))
    for index, item in enumerate(items, start=1):
        ttk.Label(body, text=t(item["name"]), font=FONT_BOLD).grid(row=index, column=0, sticky="w", pady=5)
        ttk.Label(body, text=t(item["desc"]), font=FONT_HINT, foreground=THEME["muted"],
                  wraplength=300, justify="left").grid(row=index, column=1, sticky="w", padx=(12, 12))
        path_text = str(item["path"])
        if not re.search(r"[:\\\\/]", path_text):
            path_text = t(path_text)      # 「（内置文档）」这类说明性取值也要翻；真路径原样
        tk.Label(body, text=path_text, font=FONT_HINT, foreground=THEME["link"],
                 background=THEME["bg"], anchor="w", justify="left", wraplength=330).grid(
            row=index, column=2, sticky="w")
        ttk.Button(body, text=t("打开"), width=8, command=item["action"]).grid(
            row=index, column=3, sticky="e", padx=(12, 4))
        ttk.Button(body, text=t("复制路径"), width=10,
                   command=lambda path=str(item["path"]): _copy_path(path)).grid(row=index, column=4, sticky="e")
    body.columnconfigure(1, weight=1)
    footer = ttk.Frame(body)
    footer.grid(row=len(items) + 1, column=0, columnspan=5, sticky="ew", pady=(16, 0))
    ttk.Label(footer, text=t("密钥只放在 .env；改完配置记得回控制台保存。"),
              font=FONT_HINT, foreground=THEME["muted"]).pack(side="left")
    ttk.Button(footer, text=t("关闭"), command=win.destroy).pack(side="right")
    restyle_widgets(win)


def open_env_template() -> None:
    path = reme_root() / ".env"
    if not path.exists():
        path.write_text(
            "# ReMe LLM configuration\n"
            "LLM_BACKEND=openai\n"
            "LLM_MODEL_NAME=qwen3.7-plus\n"
            "LLM_API_KEY=\n"
            "LLM_BASE_URL=\n\n"
            "# Optional embedding configuration\n"
            "EMBEDDING_BACKEND=openai\n"
            "EMBEDDING_MODEL_NAME=text-embedding-v4\n"
            "EMBEDDING_API_KEY=\n"
            "EMBEDDING_BASE_URL=\n",
            encoding="utf-8",
        )
    os.startfile(str(path))


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, APP_ID)
        return bool(value)
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg

    path = str(Path(sys.executable).resolve())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, f'"{path}"')
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass


def toggle_autostart(_icon, _item) -> None:
    enabled = not autostart_enabled()
    set_autostart(enabled)
    CFG["autostart"] = enabled
    save_config()


def sync_autostart_path() -> None:
    """自启开着的时候，把 Run 值指回**当前这个** exe。

    1.0.6 的 exe 带版本号，所以它的自启值是
    ``...\\reme-helper-1.0.6\\reme-helper-1.0.6.exe``。把新版**解压覆盖**到那个
    目录（不是走更新器，而是手动替换）之后，那个文件就没了，值变成悬空——而
    没有任何东西会去重写它：`set_autostart()` 只在用户点菜单切换时才跑。结果是
    下次开机静默失效，用户只会觉得"自启莫名其妙坏了"。

    幂等且便宜：只在自启开着、且存的值不是当前 exe 时才写。顺带也修好"整个文件夹
    被移动/改名"的情况。路径来源与 `set_autostart` 一致，都是 `sys.executable`。

    ⚠️ **只在打包态修**：从源码跑（`python src\\main.py`）时 `sys.executable` 是
    python.exe，照做会把自启值改成 python.exe —— 实测踩过一次。开发态没有"安装位置"
    这个概念，本就不该动它。
    """
    if os.name != "nt" or not CFG.get("autostart"):
        return
    if not getattr(sys, "frozen", False):
        return
    try:
        import winreg

        current = str(Path(sys.executable).resolve())
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            try:
                stored, _ = winreg.QueryValueEx(key, APP_ID)
            except FileNotFoundError:
                stored = ""
            if str(stored).strip('"') != current:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, f'"{current}"')
                log(f"autostart path repaired: {stored!r} -> {current!r}")
    except OSError as exc:  # noqa: BLE001 - 自启修不好也不该拦住托盘
        log(f"autostart path repair failed: {exc}")
    if TRAY_ICON:
        refresh_tray_menu()


def toggle_start_on_launch(_icon, _item) -> None:
    CFG["start_on_launch"] = not CFG.get("start_on_launch", False)
    save_config()
    if TRAY_ICON:
        refresh_tray_menu()


def toggle_tunnels_on_start(_icon, _item) -> None:
    CFG["start_tunnels_with_reme"] = not CFG.get("start_tunnels_with_reme", False)
    save_config()
    if TRAY_ICON:
        refresh_tray_menu()


def scan_local_keys() -> list[str]:
    ssh_dir = Path.home() / ".ssh"
    names = ("id_ed25519", "id_rsa", "id_ecdsa", "id_ed25519_opencodex_helper")
    return [str(ssh_dir / name) for name in names if (ssh_dir / name).is_file()]


def target_has_key(target: dict) -> bool:
    configured = str(target.get("key") or "").strip()
    return Path(configured).expanduser().is_file() if configured else bool(scan_local_keys())


def validate_targets(targets: list[dict]) -> None:
    seen = set()
    for target in targets:
        if not str(target.get("host") or "").strip():
            raise ValueError("VM目标的主机 / IP不能为空")
        for field, default in (("port", 22), ("remote_port", 22333)):
            try:
                target[field] = int(target.get(field, default))
            except (TypeError, ValueError) as exc:
                raise ValueError("SSH端口和VM映射端口必须是数字") from exc
            if not 1 <= target[field] <= 65535:
                raise ValueError("端口必须在1到65535之间")
        identity = (str(target["host"]).lower(), target["port"], target["remote_port"])
        if identity in seen:
            raise ValueError("同一VM目标不能重复使用同一个映射端口")
        seen.add(identity)


def edit_target_dialog(parent, target: dict | None = None) -> dict | None:
    initial = deep_copy(target or {
        "name": "Ubuntu24.04", "user": "ubuntu", "host": "192.168.1.100",
        "port": 22, "remote_port": 22333, "key": "", "enabled": True,
    })
    window = tk.Toplevel(parent)
    window.title("编辑VM目标" if target else "添加VM目标")
    window.geometry("520x350")
    attach_dialog(parent, window)
    window.grab_set()
    body = ttk.Frame(window, padding=14)
    body.pack(fill="both", expand=True)
    fields = (("名称", "name"), ("用户名", "user"), ("主机 / IP / SSH别名", "host"),
              ("SSH端口", "port"), ("VM映射端口", "remote_port"), ("私钥路径（留空使用 ~/.ssh）", "key"))
    variables = {}
    for row, (label, key) in enumerate(fields):
        ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=5)
        variables[key] = tk.StringVar(value=str(initial.get(key, "")))
        ttk.Entry(body, textvariable=variables[key], width=46).grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=5)
    enabled = tk.BooleanVar(value=bool(initial.get("enabled", True)))
    ttk.Checkbutton(body, text="启用（参与隧道连接与状态统计）", variable=enabled).grid(
        row=len(fields), column=0, columnspan=2, sticky="w", pady=6)
    local_keys = scan_local_keys()
    ttk.Label(body, text="本机密钥：" + ("、".join(Path(item).name for item in local_keys) if local_keys else "未发现"),
              foreground="#666666").grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w")
    body.columnconfigure(1, weight=1)
    result = {}

    def accept():
        candidate = {key: value.get().strip() for key, value in variables.items()}
        candidate["name"] = candidate["name"] or candidate["host"] or "VM"
        candidate["enabled"] = enabled.get()
        try:
            validate_targets([candidate])
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=window)
            return
        result.update(candidate)
        window.destroy()

    buttons = ttk.Frame(body)
    buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="e", pady=(16, 0))
    ttk.Button(buttons, text="取消", command=window.destroy).pack(side="left", padx=6)
    ttk.Button(buttons, text="确定", command=accept).pack(side="left")
    window.bind("<Return>", lambda _event: accept())
    parent.wait_window(window)
    return result or None


def choose_target_dialog(title: str) -> dict | None:
    targets = CFG.get("targets", [])
    if not targets:
        notify("还没有VM目标")
        return None
    if len(targets) == 1:
        return targets[0]
    parent = ui_parent()
    if parent is None:
        return None
    root = tk.Toplevel(parent)
    root.title(title)
    root.geometry("460x300")
    box = tk.Listbox(root)
    box.pack(fill="both", expand=True, padx=12, pady=12)
    for target in targets:
        box.insert("end", f"{target['name']}  {target['user']}@{target['host']}:{target['port']}")
    selected = {}

    def accept():
        indexes = box.curselection()
        if indexes:
            selected["target"] = targets[indexes[0]]
        root.destroy()

    ttk.Button(root, text="确定", command=accept).pack(side="right", padx=12, pady=(0, 12))
    ttk.Button(root, text="取消", command=root.destroy).pack(side="right", pady=(0, 12))
    root.wait_window()
    return selected.get("target")


def target_line(target: dict) -> str:
    connected = "●" if TUNNEL_STATE.get(target_key(target), False) else "○"
    key_status = "🔑" if target_has_key(target) else "无密钥"
    enabled = "☑" if target.get("enabled", True) else "☐"
    return f"{enabled} {target['name']}  {target['host']}  {connected} {key_status}"


def toggle_target(target: dict):
    def action(_icon, _item):
        target["enabled"] = not target.get("enabled", True)
        save_config()
        if target["enabled"] and service_is_healthy():
            run_action(lambda: start_tunnel(target))
        else:
            stop_tunnel(target)
            if TRAY_ICON:
                refresh_tray_menu()
    return action


def add_target(_icon=None, _item=None) -> None:
    def ui():
        parent = ui_parent()
        if parent is None:
            return
        candidate = edit_target_dialog(parent)
        if candidate:
            try:
                validate_targets(CFG["targets"] + [candidate])
                CFG["targets"].append(candidate)
                save_config()
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=parent)
        if TRAY_ICON:
            refresh_tray_menu()
    ui_post(ui)


def edit_target(_icon=None, _item=None) -> None:
    def ui():
        parent = ui_parent()
        if parent is None:
            return
        selected = choose_target_dialog("选择要编辑的VM目标")
        if not selected:
            return
        candidate = edit_target_dialog(parent, selected)
        if candidate:
            others = [item for item in CFG["targets"] if item is not selected]
            try:
                validate_targets(others + [candidate])
                stop_tunnel(selected)
                selected.clear(); selected.update(candidate)
                save_config()
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=parent)
        if TRAY_ICON:
            refresh_tray_menu()
    ui_post(ui)


def delete_target(_icon=None, _item=None) -> None:
    def ui():
        parent = ui_parent()
        if parent is None:
            return
        selected = choose_target_dialog("选择要删除的VM目标")
        if not selected:
            return
        accepted = messagebox.askyesno(APP_NAME, f"确定删除 {selected['name']}（{selected['host']}）？", parent=parent)
        if accepted:
            stop_tunnel(selected)
            CFG["targets"] = [item for item in CFG["targets"] if item is not selected]
            save_config()
            if TRAY_ICON:
                refresh_tray_menu()
    ui_post(ui)


def rescan_keys(_icon=None, _item=None) -> None:
    keys = scan_local_keys()
    notify("已扫描本机SSH密钥：" + ("、".join(Path(item).name for item in keys) if keys else "未发现"))
    refresh_tray_menu()


def build_targets_menu() -> pystray.Menu:
    items = [pystray.MenuItem(lambda _item, t=target: target_line(t), toggle_target(target),
                              checked=lambda _item, t=target: bool(t.get("enabled", True)))
             for target in CFG.get("targets", [])]
    if items:
        items.append(pystray.Menu.SEPARATOR)
    items.extend((
        pystray.MenuItem(menu_text("＋ 添加目标…"), add_target),
        pystray.MenuItem(menu_text("✎ 编辑目标…"), edit_target),
        pystray.MenuItem(menu_text("－ 删除目标…"), delete_target),
        pystray.MenuItem(menu_text("重新扫描本机密钥"), rescan_keys),
    ))
    return pystray.Menu(*items)


FONT_UI = ("Microsoft YaHei UI", 10)
FONT_SECTION = ("Microsoft YaHei UI", 11, "bold")
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_HINT = ("Microsoft YaHei UI", 9)
FONT_NUM = ("Microsoft YaHei UI", 12, "bold")

# ---------------- 主题（浅色 / 深色） ----------------
PALETTES = {
    "light": {
        "bg": "#f4f5f7", "panel": "#ffffff", "text": "#111827", "text2": "#374151",
        "muted": "#6b7280", "disabled": "#4b5563", "link": "#0969da",
        "ok": "#0a7d28", "warn": "#b26a00", "err": "#b3261e",
        "field_bg": "#ffffff", "field_fg": "#111827", "tip_bg": "#ffffe0", "tip_fg": "#111827",
        "toast_bg": "#1f2937", "toast_fg": "#f9fafb", "sel_bg": "#cfe3ff", "border": "#d0d4da",
        "code_bg": "#f3f3f3", "table_bg": "#fafafa",
    },
    "dark": {
        "bg": "#1b1f27", "panel": "#222833", "text": "#e8eaed", "text2": "#c7ccd6",
        "muted": "#98a2b3", "disabled": "#aab3c2", "link": "#6cb6ff",
        "ok": "#4ade80", "warn": "#fbbf24", "err": "#f87171",
        "field_bg": "#2a313d", "field_fg": "#e8eaed", "tip_bg": "#2f3744", "tip_fg": "#e8eaed",
        "toast_bg": "#3b4354", "toast_fg": "#f3f4f6", "sel_bg": "#33507a", "border": "#3a4250",
        "code_bg": "#2a313d", "table_bg": "#242b36",
    },
}
THEME: dict = dict(PALETTES["light"])


def theme_name() -> str:
    return "dark" if str(CFG.get("theme") or "light").lower() == "dark" else "light"


# 浅色/深色共用同一个 ttk 引擎：
#   1) 两个引擎的控件高度不一样（vista 27px / clam 33px），一切主题整页都会位移；
#   2) clam 在这台机器上把「选中」画成 ✗、未选画成实心块，勾选框含义正好反了；
#   3) alt 是 Tk 自带引擎，接受完整的颜色配置，勾选框就是标准的空框/对勾。
TTK_ENGINE = "alt"
COLOR_KEYS = ("bg", "panel", "text", "text2", "muted", "disabled", "link", "ok", "warn", "err",
              "field_bg", "field_fg", "tip_bg", "tip_fg", "toast_bg", "toast_fg", "sel_bg", "border",
              "code_bg", "table_bg")
PALETTE_BEFORE: dict = dict(PALETTES["light"])


def _configure_styles(style) -> None:
    """把当前调色板铺到所有用到的 ttk 样式上（每次切主题都要重配：setTheme 会重置样式）。"""
    bg, panel, text_color = THEME["bg"], THEME["panel"], THEME["text"]
    border, field_bg, field_fg = THEME["border"], THEME["field_bg"], THEME["field_fg"]
    style.configure(".", background=bg, foreground=text_color, fieldbackground=field_bg,
                    bordercolor=border, lightcolor=border, darkcolor=border,
                    troughcolor=bg, focuscolor=THEME["sel_bg"],
                    selectbackground=THEME["sel_bg"], selectforeground=text_color)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=text_color)
    style.configure("TButton", background=panel, foreground=text_color, bordercolor=border,
                    lightcolor=panel, darkcolor=panel, focuscolor=THEME["sel_bg"], padding=(8, 4))
    style.map("TButton",
              background=[("pressed", THEME["sel_bg"]), ("active", THEME["sel_bg"]), ("disabled", bg)],
              foreground=[("disabled", THEME["disabled"])])
    for name_ in ("TCheckbutton", "TRadiobutton"):
        style.configure(name_, background=bg, foreground=text_color, focuscolor=bg,
                        indicatorcolor=THEME["ok"], indicatormargin=(1, 1, 6, 1))
        style.map(name_,
                  background=[("active", bg)],
                  indicatorcolor=[("selected", THEME["ok"]), ("!selected", field_bg),
                                  ("disabled", THEME["disabled"])],
                  foreground=[("disabled", THEME["disabled"])])
    style.configure("TEntry", fieldbackground=field_bg, foreground=field_fg, insertcolor=text_color,
                    bordercolor=border, lightcolor=border, darkcolor=border)
    style.map("TEntry", fieldbackground=[("disabled", bg)], foreground=[("disabled", THEME["disabled"])])
    style.configure("TCombobox", fieldbackground=field_bg, background=panel, foreground=field_fg,
                    arrowcolor=text_color, bordercolor=border, lightcolor=border, darkcolor=border)
    style.map("TCombobox", fieldbackground=[("readonly", field_bg), ("disabled", bg)],
              foreground=[("readonly", field_fg), ("disabled", THEME["disabled"])],
              arrowcolor=[("disabled", THEME["disabled"])])
    style.configure("TSeparator", background=border)
    style.configure("Treeview", background=panel, fieldbackground=panel, foreground=text_color,
                    bordercolor=border, lightcolor=panel, darkcolor=panel)
    style.map("Treeview", background=[("selected", THEME["sel_bg"])],
              foreground=[("selected", text_color)])
    style.configure("Treeview.Heading", background=bg, foreground=text_color, bordercolor=border,
                    lightcolor=bg, darkcolor=bg)
    style.map("Treeview.Heading", background=[("active", THEME["sel_bg"])])
    style.configure("Vertical.TScrollbar", background=panel, troughcolor=bg, bordercolor=border,
                    arrowcolor=text_color, lightcolor=panel, darkcolor=panel)
    style.map("Vertical.TScrollbar", background=[("active", THEME["sel_bg"])])
    # 思考强度那一排「分段按钮」：自己建的样式，必须每次都重配，否则切主题会退化成黑块
    style.configure("Segmented.Toolbutton", anchor="center", padding=(10, 4),
                    background=panel, foreground=text_color, bordercolor=border,
                    lightcolor=panel, darkcolor=panel, focuscolor=THEME["sel_bg"])
    style.map("Segmented.Toolbutton",
              background=[("selected", THEME["sel_bg"]), ("active", THEME["sel_bg"]),
                          ("disabled", bg)],
              foreground=[("selected", text_color), ("disabled", THEME["disabled"])])


def apply_theme(name: str | None = None) -> None:
    """把调色板铺到界面。

    浅色和深色用的是同一个 ttk 引擎（见 TTK_ENGINE），所以切换主题不会引起布局位移。
    Only the thread that owns windows may touch ttk: Tk objects are thread-affine, so a
    palette switch from elsewhere just updates THEME and lets the window apply it.
    """
    global PALETTE_BEFORE
    PALETTE_BEFORE = dict(THEME)      # 记下旧颜色，restyle_widgets 据此把前景色也换掉
    THEME.clear()
    THEME.update(PALETTES[theme_name() if name is None else name])
    if threading.current_thread() not in UI_THREADS:
        return
    try:
        style = ttk.Style()
        try:
            style.theme_use(TTK_ENGINE)
        except tk.TclError:  # 万一该 Tk 构建没有 alt，就沿用当前引擎，至少颜色是对的
            log(f"theme_use({TTK_ENGINE}) failed, keeping {style.theme_use()}")
        _configure_styles(style)
    except tk.TclError as exc:  # noqa: BLE001 - theming must never break the app
        log(f"apply_theme failed: {exc}")


def theme_color_map() -> dict:
    """旧调色板的颜色 → 新调色板里同一个键的颜色。

    这样「按语义上色」的控件（muted 灰、warn 橙、ok 绿、link 蓝）在换主题后仍然是同一个语义色，
    而不是被一律刷成正文色。
    """
    return {PALETTE_BEFORE[key]: THEME[key]
            for key in COLOR_KEYS
            if key in PALETTE_BEFORE and key in THEME and PALETTE_BEFORE[key] != THEME[key]}


PALETTE_COLORS = {color for palette in PALETTES.values() for color in palette.values()}


def restyle_widgets(widget, remap: dict | None = None) -> None:
    """给普通 tk 控件换色（ttk 的跟着样式走）。

    两处必须小心，都是踩过的坑：
      * 只改 background 不改 foreground → 深色切浅色后 tk.Label 还是近白字，浅底上「看不清」；
      * 只映射已知颜色 → 没显式设过背景的 Label（Tk 系统默认色）映射不到，深色下变成白块。
    所以：认识的调色板颜色按语义映射，不认识的一律用主题色兜底。
    """
    if remap is None:
        remap = theme_color_map()
        remap = dict(remap)
        remap.setdefault("SystemButtonFace", THEME["bg"])
        remap.setdefault("SystemWindow", THEME["bg"])
        remap.setdefault("white", THEME["panel"])
        remap.setdefault("black", THEME["text"])
    try:
        cls = widget.winfo_class()
    except tk.TclError:
        return

    def keep(value, fallback: str) -> str:
        text = str(value)
        if text in remap:
            return remap[text]
        if text in PALETTE_COLORS:
            return text
        return fallback

    try:
        if cls in ("Frame", "Toplevel", "Tk"):
            widget.configure(background=keep(widget.cget("background"), THEME["bg"]))
        elif cls == "Canvas":
            widget.configure(background=THEME["bg"], highlightthickness=0)
        elif cls == "Label":
            widget.configure(background=keep(widget.cget("background"), THEME["bg"]),
                             foreground=keep(widget.cget("foreground"), THEME["text"]))
        elif cls == "Text":
            widget.configure(background=THEME["panel"], foreground=THEME["text"],
                             insertbackground=THEME["text"])
        elif cls == "Listbox":
            widget.configure(background=THEME["panel"], foreground=THEME["text"],
                             selectbackground=THEME["sel_bg"], selectforeground=THEME["text"])
        elif cls in ("Button", "Checkbutton", "Radiobutton", "Entry"):
            widget.configure(background=keep(widget.cget("background"), THEME["bg"]),
                             foreground=keep(widget.cget("foreground"), THEME["text"]))
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        restyle_widgets(child, remap)


# 主题切换后需要「手工重新上色」的地方（tk.Text 的 tag 颜色不会跟着 ttk 样式走）
THEME_HOOKS: list = []
PENDING_THEME = {"dirty": False}
PENDING_LANG = {"dirty": False}
UI_THREADS: list = []


def ui_lang() -> str:
    return "en" if str(CFG.get("ui_lang") or "zh").lower().startswith("en") else "zh"


def t(text) -> str:
    """把界面文案换成当前语言（中文模式原样返回，未收录的也原样返回）。

    词表在 i18n.py：一行一条中英对照，拼接出来的句子按最长片段替换。
    """
    try:
        return i18n.translate(text, ui_lang())
    except Exception:  # noqa: BLE001 - translation must never break the UI
        return str(text)


def app_title() -> str:
    """标题栏 / 托盘提示里的产品名。

    APP_NAME 是个常量，不跟着语言走；弹窗标题早就被 messagebox 包装层翻掉了，
    只剩窗口标题和托盘提示需要在这里补上。注意别去动 APP_ID：托盘窗口类名和开机
    自启的注册表项都靠它，必须与语言无关。
    """
    return f"{t(APP_NAME)} {VERSION}"


def expose_open_prefix(exposed: int, total: int) -> str:
    """「已开放 27/32：」——两种暴露状态共用的平行前缀。

    整句作为一个词条翻译、计数走占位符：半角冒号在中文里难看，而全角冒号一旦留在
    f-string 里就会在英文模式下残留（英文模式的全树扫描正是这么抓到它的）。
    """
    return t("已开放 {exposed}/{total}：").format(exposed=exposed, total=total)


def translate_tree(widget) -> None:
    """Translate the static texts of an already-built widget tree.

    Widgets are created with their Chinese text; this pass swaps in English where a
    translation exists, which keeps the call sites free of translation noise.
    """
    if ui_lang() == "zh":
        return
    try:
        cls = widget.winfo_class()
    except tk.TclError:
        return
    try:
        if cls in ("Label", "Button", "Checkbutton", "Radiobutton", "LabelFrame", "TLabel",
                   "TButton", "TCheckbutton", "TRadiobutton", "TLabelframe"):
            current = str(widget.cget("text"))
            if current:
                widget.configure(text=t(current))
        elif cls == "Treeview":
            for column in widget.cget("columns"):
                widget.heading(column, text=t(str(widget.heading(column, "text"))))
        elif cls in ("TCombobox", "Combobox"):
            values = list(widget.cget("values") or [])
            if values:
                widget.configure(values=[t(value) for value in values])
        elif cls == "TNotebook":
            for index in range(widget.index("end")):
                widget.tab(index, text=t(str(widget.tab(index, "text"))))
        elif cls in ("TCombobox", "Combobox"):
            values = list(widget.cget("values") or [])
            if values:
                widget.configure(values=[t(value) for value in values])
        elif cls == "TNotebook":
            for index in range(widget.index("end")):
                widget.tab(index, text=t(str(widget.tab(index, "text"))))
    except tk.TclError:
        pass
    try:
        for child in widget.winfo_children():
            translate_tree(child)
    except tk.TclError:
        pass


class _TranslatedMessageBox:
    """messagebox shim: translates the title and body of every dialog automatically."""

    def __getattr__(self, name):
        target = getattr(_raw_messagebox, name)

        def call(title="", message="", *args, **kwargs):
            return target(t(title), t(message), *args, **kwargs)

        return call


messagebox = _TranslatedMessageBox()


def set_language(lang: str, reopen: bool = True) -> None:
    """Switch UI language, persist it, and rebuild the console so the change is visible."""
    CFG["ui_lang"] = "en" if str(lang).lower().startswith("en") else "zh"
    save_config()
    if TRAY_ICON:
        TRAY_ICON.title = t(APP_NAME)   # 托盘悬浮提示也跟着换
        refresh_tray_menu(force=True)   # 菜单项文案是「重建菜单时」求值的，必须重画
    if not reopen:
        return
    if in_ui_thread():
        reload_console()
    else:
        PENDING_LANG["dirty"] = True


def reload_console() -> None:
    """重建控制台内容（切换语言后用它整体换文案）。解释器与 UI 线程都保持不变。"""
    def work() -> None:
        win = UI_HOST.get("win")
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
            if UI_HOST.get("win") is win:
                UI_HOST["win"] = None
        PENDING_LANG["dirty"] = False
        PENDING_THEME["dirty"] = False
        open_console()
        refresh_aux_windows()

    if in_ui_thread():
        work()
    else:
        ui_post(work)


def toggle_language(_icon=None, _item=None) -> None:
    set_language("zh" if ui_lang() == "en" else "en")


def toggle_theme(_icon=None, _item=None) -> None:
    """Flip light/dark and persist it.

    A tray menu callback runs on pystray's thread, where touching another thread's Tk
    widgets raises; in that case the window applies the change on its next pump tick.
    """
    CFG["theme"] = "light" if theme_name() == "dark" else "dark"
    save_config()
    if in_ui_thread():
        apply_theme()
        for window in (UI_HOST.get("win"), UI_HOST.get("root")):
            try:
                if window is not None and window.winfo_exists():
                    restyle_widgets(window)
            except tk.TclError:
                pass
    else:
        PENDING_THEME["dirty"] = True
    if TRAY_ICON:
        refresh_tray_menu()
    notify("已切换到" + ("深色" if theme_name() == "dark" else "浅色") + "主题")


class LinkLabel(tk.Label):
    """Clickable text link (used for per-section and per-field “恢复默认”)."""

    def __init__(self, parent, text: str, command, font=FONT_HINT) -> None:
        super().__init__(parent, text=text, foreground=THEME["link"], cursor="hand2", font=font)
        self.command = command
        self.font_base = font
        self._enabled = True
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    def _click(self, _event=None) -> None:
        if self._enabled and self.command:
            self.command()

    def _enter(self, _event=None) -> None:
        if self._enabled:
            self.configure(font=(self.font_base[0], self.font_base[1], "underline"))

    def _leave(self, _event=None) -> None:
        self.configure(font=self.font_base)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(foreground=THEME["link"] if enabled else THEME["disabled"],
                       cursor="hand2" if enabled else "arrow")

    @property
    def enabled(self) -> bool:
        return self._enabled


class Tooltip:
    """Hover help for a widget: a borderless toplevel shown next to it."""

    REGISTRY: dict = {}   # widget -> Tooltip, so text can be updated later

    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip = None
        Tooltip.REGISTRY[str(widget)] = self
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text

    @classmethod
    def update_text(cls, widget, text: str) -> None:
        """Attach or replace hover help for a widget."""
        existing = cls.REGISTRY.get(str(widget))
        if existing is None:
            cls(widget, text)
        else:
            existing.set_text(text)

    def show(self, _event=None) -> None:
        if self.tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            tk.Label(self.tip, text=t(self.text), justify="left", background=THEME["tip_bg"],
                     foreground=THEME["tip_fg"], relief="solid",
                     borderwidth=1, wraplength=430, font=("Microsoft YaHei UI", 9)).pack(ipadx=6, ipady=4)
        except Exception:  # noqa: BLE001 - tooltips must never break the window
            self.tip = None

    def hide(self, _event=None) -> None:
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:  # noqa: BLE001
                pass
            self.tip = None


def show_settings(autoclose_ms: int | None = None, harness=None) -> None:
    """打开控制台。

    可以从任意线程调用（托盘回调、测试、命令行都走这里）：真正的构建被投递到 UI 线程，
    因为 Tk 对象只能由创建它的线程操作。

    ``harness`` is a test seam: it receives a small dict of inspectors/actions so an
    automated check can drive the real window instead of re-implementing its logic.
    """
    ui_post(lambda: open_console(autoclose_ms, harness))


def open_console(autoclose_ms: int | None = None, harness=None) -> None:
    """在 UI 线程里打开控制台：已经开着就前置，否则构建一个（不新建解释器）。"""
    host = UI_HOST.get("root")
    if host is None:
        detail = UI_HOST.get("error") or "Tk 解释器未能创建"
        log(f"console: cannot open ({detail})")
        try:
            messagebox.showerror(APP_NAME, f"控制台无法打开：{detail}\n\n详见日志：{LOG_PATH}")
        except Exception:  # noqa: BLE001 - 连对话框都弹不出来时只能记日志
            pass
        return
    apply_pending_theme()
    existing = UI_HOST.get("win")
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return
        except tk.TclError:
            pass
        UI_HOST["win"] = None
    build_console(host, autoclose_ms, harness)


def build_console(host, autoclose_ms: int | None = None, harness=None) -> None:
    """构建控制台窗口（必须在 UI 线程里调用）。

    窗口是常驻解释器的一个 Toplevel：关闭只销毁它，切语言只重建它，解释器始终活着。
    这正是「切换几次后控制台打不开」的根因修复——旧实现每次开窗都新建一个 Tk 解释器，
    跨线程的隐式默认根窗口会让新解释器抛 “main thread is not in main loop”。
    """
    PENDING_THEME["dirty"] = False   # 新窗口直接读当前配置，用不到挂起的切换
    PENDING_LANG["dirty"] = False

    def ui():
        global SETTINGS_ROOT
        root = tk.Toplevel(host)
        UI_HOST["win"] = root
        SETTINGS_ROOT = root
        apply_theme()
        root.title(app_title() + t(" · 控制台"))
        root.geometry("1040x820")
        root.minsize(880, 560)

        # ---------- 滚动容器 ----------
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, highlightthickness=0, borderwidth=0, background=THEME["bg"])
        vbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        scroll_pending = [False]
        width_state = {"pending": False, "value": 0}

        def apply_scrollregion() -> None:
            scroll_pending[0] = False
            canvas.configure(scrollregion=canvas.bbox("all"))

        def schedule_scrollregion(_event=None) -> None:
            if not scroll_pending[0]:
                scroll_pending[0] = True
                root.after(40, apply_scrollregion)

        def apply_width() -> None:
            width_state["pending"] = False
            viewport = width_state["value"]
            target = max(560, min(viewport - 28, 920))  # readable column, centred on wide screens
            canvas.coords(inner_id, max(14, (viewport - target) // 2), 6)
            canvas.itemconfigure(inner_id, width=target)

        def sync_inner_width(event) -> None:
            width_state["value"] = event.width
            if not width_state["pending"]:
                width_state["pending"] = True
                root.after(40, apply_width)

        def on_wheel(event) -> None:
            # Only scroll the page when the pointer is not over a widget that scrolls itself
            # (combobox dropdowns live in their own toplevel, so they never reach here).
            widget = getattr(event, "widget", None)
            if widget is not None:
                try:
                    if widget.winfo_class() in ("Listbox", "Treeview", "Text", "Spinbox", "TCombobox", "TSpinbox"):
                        return
                except Exception:  # noqa: BLE001 - widget may be gone
                    return
            box = canvas.bbox("all")
            if box and (box[3] - box[1]) > canvas.winfo_height():
                canvas.yview_scroll((-1 if event.delta > 0 else 1) * 3, "units")

        def on_destroy(event) -> None:
            global SETTINGS_ROOT
            if event.widget is not root:
                return
            try:
                root.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            SETTINGS_ROOT = None
            if UI_HOST.get("win") is root:
                UI_HOST["win"] = None   # 解释器保留，下次开窗复用

        inner.bind("<Configure>", schedule_scrollregion)
        canvas.bind("<Configure>", sync_inner_width)
        # Bind on the toplevel (its bindtag is shared by every child) instead of bind_all:
        # events inside a combobox popdown stay inside that popdown and never scroll the page.
        root.bind("<MouseWheel>", on_wheel)
        root.bind("<Destroy>", on_destroy)

        task_results: queue.Queue = queue.Queue()

        def submit(work, done) -> None:
            def worker():
                try:
                    result = work()
                except Exception as exc:  # noqa: BLE001 - surfaced in the UI
                    result = (False, f"{type(exc).__name__}: {exc}")
                task_results.put((done, result))

            threading.Thread(target=worker, daemon=True).start()

        def pump() -> None:
            if not root.winfo_exists():
                return      # 窗口已销毁：停止这个窗口的轮询
            try:
                while True:
                    done, result = task_results.get_nowait()
                    done(*result)
            except queue.Empty:
                pass
            if PENDING_THEME["dirty"]:
                # 托盘线程切换了主题：在这里（Tk 线程）落地
                PENDING_THEME["dirty"] = False
                apply_theme()
                restyle_all()   # 含指引/说明等辅助窗口与它们的 tag 颜色
                if theme_button is not None:
                    theme_button.configure(text=t("深色") if theme_name() == "light" else t("浅色"))
            if PENDING_LANG["dirty"]:
                # 托盘线程切换了语言：重建窗口以整体换语言
                PENDING_LANG["dirty"] = False
                root.after(10, reload_console)
                return
            root.after(200, pump)

        pump()

        # ---------- 版式助手 ----------

        def section(index: int, title: str, subtitle: str, reset_name: str | None = None,
                    reset_command=None) -> ttk.Frame:
            """Numbered section: bold title, one-line description, hairline separator."""
            frame = ttk.Frame(inner)
            frame.pack(fill="x", padx=12, pady=(16, 0))
            head = ttk.Frame(frame)
            head.pack(fill="x")
            tk.Label(head, text=f"{index}. " + t(title), font=FONT_SECTION, foreground=THEME["text"]).pack(side="left")
            if reset_name:
                link = LinkLabel(head, t("回到基线"), reset_command)
                link.pack(side="right")
                Tooltip(link, "把本区可调项恢复为基线值（见顶部状态条的“基线”）。\n"
                              "固定预设下，基线就是该预设的标准值。")
                reset_widgets[reset_name] = link
            ttk.Label(frame, text=subtitle, font=FONT_HINT, foreground=THEME["muted"], justify="left",
                      wraplength=820).pack(anchor="w", pady=(2, 6))
            ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(0, 4))
            holder = ttk.Frame(frame)
            holder.pack(fill="x")
            holder.columnconfigure(0, minsize=150)
            holder.columnconfigure(1, weight=1)
            return holder

        def field_label(holder, row: int, text: str, key: str | None = None,
                        reset_name: str | None = None, reset_command=None) -> None:
            box = ttk.Frame(holder)
            box.grid(row=row, column=0, sticky="nw", pady=(8, 0))
            tk.Label(box, text=t(text), font=FONT_UI, foreground=THEME["text"]).pack(side="left")
            if key:
                marker = ttk.Label(box, text=" ?", foreground=THEME["link"], cursor="hand2")
                marker.pack(side="left")
                Tooltip(marker, GLOSSARY[key])
            if reset_name:
                link = LinkLabel(box, " ↺", reset_command)
                link.pack(side="left")
                Tooltip(link, "恢复到基线值（该预设的标准值）")
                reset_widgets[reset_name] = link

        def hint(holder, row: int, text: str) -> None:
            ttk.Label(holder, text=text, font=FONT_HINT, foreground=THEME["muted"], justify="left",
                      wraplength=560).grid(row=row, column=1, sticky="w", pady=(2, 0))

        def inline_hint(holder, row: int, text: str) -> None:
            ttk.Label(holder, text=text, font=FONT_HINT, foreground=THEME["muted"]).grid(
                row=row, column=2, sticky="w", padx=(8, 0))

        # ---------- 草稿状态（保存前只改这里） ----------
        draft = settings_new_draft(CFG, str(reme_root()))
        env_merge = merge_env_defaults(draft, read_env_values())
        saved_snapshot = [deep_copy(CFG), str(reme_root()), CFG["mode"]]

        env_values = read_env_values()
        llm_key_present = bool(str(env_values.get("LLM_API_KEY") or "").strip())
        emb_key_present = bool(str(env_values.get("EMBEDDING_API_KEY") or "").strip())

        root_var = tk.StringVar(value=draft["reme_root"])
        mode_var = tk.StringVar(value=draft["mode"])
        llm_base_var = tk.StringVar(value=draft["llm"]["base_url"])
        llm_model_var = tk.StringVar(value=draft["llm"]["model"])
        # 密钥按密码框的常规做法：已配置就显示成一串定长的 ****（长度不泄漏），
        # 点「显示」才明文——但占位符状态下没有内容可显示，那个按钮会被禁用。
        llm_key_var = tk.StringVar(value=KEY_MASK_PLACEHOLDER if llm_key_present else "")
        llm_tokens_var = tk.StringVar(value=str(draft["llm"]["max_tokens"]))
        llm_thinking_var = tk.BooleanVar(value=draft["llm"]["thinking_enable"])
        llm_effort_var = tk.StringVar(value=draft["llm"]["reasoning_effort"] or "不设置")
        emb_base_var = tk.StringVar(value=draft["embedding"]["base_url"])
        emb_model_var = tk.StringVar(value=draft["embedding"]["model"])
        emb_key_var = tk.StringVar(value=KEY_MASK_PLACEHOLDER if emb_key_present else "")
        emb_dims_var = tk.StringVar(value=str(draft["embedding"]["dimensions"]))
        scan_days_var = tk.StringVar(value=str(draft["pipeline"]["scan_days"]))
        max_units_var = tk.StringVar(value=str(draft["pipeline"]["max_units"]))
        cron_choice_var = tk.StringVar(value=draft["pipeline"]["dream_cron"])
        cron_custom_var = tk.StringVar(value=draft["pipeline"]["dream_cron"])
        reindex_scope_var = tk.StringVar(value="all")
        # 二选一：官方默认（不写白名单＝全开）或自定义（只开放勾选的）
        expose_mode_var = tk.StringVar(value="custom" if draft["expose"]["custom"] else "official")
        auto_enable_var = tk.BooleanVar(value=False)
        feature_vars = {key: tk.BooleanVar(value=True) for key in FEATURES}
        expose_vars = {job: tk.BooleanVar(value=True) for job in servable_job_names()}

        llm_status = None
        emb_status = None
        pipe_status = None
        preview_label = None
        footer_label = None
        save_button = None
        discard_button = None
        reset_all_button = None
        switch_note = None
        feature_note = None
        expose_hint = None
        custom_box = None
        expose_gray_hint = None
        chips: dict = {}
        llm_widgets: list = []
        effort_widgets: list = []          # 动态重画的档位按钮（llm_widgets 只建一次，不能用）
        emb_widgets: list = []
        dream_widgets: list = []
        feature_widgets: dict = {}
        job_widgets: dict = {}
        reset_widgets: dict = {}
        model_caps: dict = {}              # {model_id: capabilities}，由「刷新模型」填充
        effort_dropped = {"label": ""}     # 因当前后台/模型不接受而被清空的档位

        def reset_field(section_name: str, key: str) -> None:
            collect_widgets()
            settings_reset_field(draft, section_name, key, saved_snapshot[0])
            collapsed = settings_collapse_mode(draft)
            toast(f"{key} 已回到基线" + (f"；模式自动切换为{MODE_NAMES[collapsed]}" if collapsed else ""))
            apply_widgets()
            refresh_state()
        # ================= 0. 状态条 =================
        strip = ttk.Frame(inner)
        strip.pack(fill="x", padx=14, pady=(14, 0))
        for index, name in enumerate(("模式", "基线", "服务", "LLM", "Embedding", "未保存改动")):
            cell = ttk.Frame(strip)
            cell.grid(row=0, column=index, sticky="w", padx=(0, 30))
            ttk.Label(cell, text=name, font=FONT_HINT, foreground=THEME["muted"]).pack(anchor="w")
            value = tk.Label(cell, text="—", font=FONT_NUM, foreground=THEME["text"], background=THEME["bg"])
            value.pack(anchor="w")
            chips[name] = value
        theme_button = ttk.Button(strip, text="深色" if theme_name() == "light" else "浅色",
                                  command=lambda: switch_theme_here())
        theme_button.grid(row=0, column=len(chips), sticky="e", padx=(0, 4))
        Tooltip(theme_button, "切换浅色 / 深色主题（会记住选择）")
        lang_button = ttk.Button(strip, text="English" if ui_lang() == "zh" else "中文",
                                 command=lambda: set_language("en" if ui_lang() == "zh" else "zh"))
        lang_button.grid(row=0, column=len(chips) + 1, sticky="e")
        Tooltip(lang_button, "切换界面语言 / Switch interface language（会记住选择）")
        ttk.Separator(inner, orient="horizontal").pack(fill="x", padx=12, pady=(10, 0))

        # ================= 1. 运行与模式 =================
        gen = section(1, "运行与模式",
                      "模式决定能力范围（哪些功能与后台 Job 开着）。只改能力项会转为自定义模式；"
                      "地址、模型、Key 与各项参数属于公共设置，改它们不会离开预设。")
        field_label(gen, 0, "ReMe 目录")
        root_entry = ttk.Entry(gen, textvariable=root_var, width=48)
        root_entry.grid(row=0, column=1, sticky="w", pady=(8, 0))
        root_buttons = ttk.Frame(gen)
        root_buttons.grid(row=0, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Button(root_buttons, text="选择…", command=lambda: browse_root()).pack(side="left")
        ttk.Button(root_buttons, text="扫描…", command=lambda: scan_root()).pack(side="left", padx=(6, 0))
        install_note = ttk.Label(gen, text="", font=FONT_HINT, foreground=THEME["warn"],
                                 justify="left", wraplength=620)
        install_note.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        install_buttons = ttk.Frame(gen)
        install_buttons.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        copy_prompt_button = ttk.Button(install_buttons, text="复制安装提示词",
                                        command=lambda: copy_install_prompt())
        copy_prompt_button.pack(side="left")
        open_docs_button = ttk.Button(install_buttons, text="打开官方文档",
                                      command=lambda: open_path("https://github.com/agentscope-ai/ReMe"))
        open_docs_button.pack(side="left", padx=(6, 0))
        read_doc_button = ttk.Button(install_buttons, text="阅读接入文档",
                                     command=lambda: show_integration_doc())
        read_doc_button.pack(side="left", padx=(6, 0))
        copy_doc_button = ttk.Button(install_buttons, text="复制接入文档",
                                     command=lambda: copy_integration_doc())
        copy_doc_button.pack(side="left", padx=(6, 0))
        Tooltip(copy_prompt_button, "复制一段可直接发给 DSH / Codex 的安装指令，让它替你把 ReMe 装好并启动。")
        Tooltip(open_docs_button, "在浏览器打开 ReMe 官方仓库。")
        Tooltip(read_doc_button, "先看这篇：怎么把 Codex、DSH 接到 ReMe 上。想交给 AI 去做，再用右边的「复制接入文档」。")
        Tooltip(copy_doc_button, "复制整篇接入文档（含 Codex 捕获脚本），粘贴给 AI，它就能照着把 Codex 与 DSH 接到 ReMe。")

        mode_box = ttk.Frame(gen)
        mode_box.grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))
        for key in MODE_ORDER:
            line = ttk.Frame(mode_box)
            line.pack(anchor="w", pady=(0, 6))
            ttk.Radiobutton(line, text=t(MODE_NAMES[key]), variable=mode_var, value=key,
                            command=lambda k=key: on_mode_click(k)).pack(side="left")
            ttk.Label(line, text=t(MODE_SUBTITLE[key]), font=FONT_HINT, foreground=THEME["muted"]).pack(side="left", padx=(8, 0))
        note_row = ttk.Frame(gen)
        note_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        switch_note = ttk.Label(note_row, text="", font=FONT_HINT, foreground=THEME["warn"],
                                justify="left", wraplength=540)
        switch_note.pack(side="left")
        LinkLabel(note_row, "  " + t("撤销修改"), lambda: undo_switch()).pack(side="left")

        # ================= 2. LLM =================
        llm_holder = section(2, "LLM 与模型", "写记忆用的模型。地址与 Key 保存在 .env，保存时写入。",
                             "llm", lambda: reset_section("llm"))
        field_label(llm_holder, 0, "Base URL", "LLM")
        llm_base_entry = ttk.Entry(llm_holder, textvariable=llm_base_var, width=46)
        llm_base_entry.grid(row=0, column=1, sticky="w", pady=(8, 0))
        field_label(llm_holder, 1, "模型")
        llm_model_box = ttk.Combobox(llm_holder, textvariable=llm_model_var, width=42)
        llm_model_box.grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Button(llm_holder, text="刷新模型", command=lambda: refresh_models()).grid(
            row=1, column=2, padx=(8, 0), pady=(8, 0))
        # 换了模型就可能换一套合法档位：选中或手输都要重画那一行
        llm_model_box.bind("<<ComboboxSelected>>",
                           lambda _e: on_edit("llm", "model", llm_model_var.get().strip()), add="+")
        def sync_key_toggle(entry, var, toggle, show_var) -> None:
            """占位符还在＝没有内容可显示：禁用「显示」并保持掩码。"""
            untouched = key_field_untouched(var.get())
            if untouched:
                show_var.set(False)
            entry.configure(show="" if show_var.get() else "*")
            toggle.configure(state="disabled" if untouched else "normal")

        def install_key_field(entry, var, toggle, show_var) -> None:
            """定长占位符的交互。

            一敲键就把占位符整体丢掉——否则会拼成「40 个星号 + 真 Key」这种四不像，
            保存时还会当成用户输入写进 .env。
            """
            def drop_placeholder(_event=None) -> None:
                if var.get().strip() == KEY_MASK_PLACEHOLDER:
                    var.set("")

            def on_key(event) -> None:
                if event.char and event.char.isprintable():
                    drop_placeholder()

            entry.bind("<KeyPress>", on_key)
            entry.bind("<<Paste>>", drop_placeholder)
            var.trace_add("write", lambda *_a: sync_key_toggle(entry, var, toggle, show_var))
            sync_key_toggle(entry, var, toggle, show_var)

        field_label(llm_holder, 2, "API Key")
        llm_key_entry = ttk.Entry(llm_holder, textvariable=llm_key_var, width=42, show="*")
        llm_key_entry.grid(row=2, column=1, sticky="w", pady=(8, 0))
        llm_key_show = tk.BooleanVar(value=False)
        llm_key_toggle = ttk.Checkbutton(
            llm_holder, text="显示", variable=llm_key_show,
            command=lambda: llm_key_entry.configure(show="" if llm_key_show.get() else "*"))
        llm_key_toggle.grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        install_key_field(llm_key_entry, llm_key_var, llm_key_toggle, llm_key_show)
        inline_hint(llm_holder, 2, "（已配置；不动这里＝不改，输入新 Key 才覆盖）" if llm_key_present
                    else "（未配置；填写后保存）")
        field_label(llm_holder, 3, "max_tokens", "token", "llm_tokens", lambda: reset_field("llm", "max_tokens"))
        llm_tokens_entry = ttk.Entry(llm_holder, textvariable=llm_tokens_var, width=10)
        llm_tokens_entry.grid(row=3, column=1, sticky="w", pady=(8, 0))
        hint(llm_holder, 4, "建议 ≥8192；过小会导致记忆提炼写出空内容。")
        llm_thinking_check = ttk.Checkbutton(llm_holder, text="允许内部思考（建议保持关闭）",
                                            variable=llm_thinking_var,
                                            command=lambda: on_edit("llm", "thinking_enable", llm_thinking_var.get()))
        llm_thinking_check.grid(row=5, column=1, sticky="w", pady=(8, 0))
        Tooltip(llm_thinking_check, "对应配置 thinking_enable：开启后模型先推理再输出，"
                                    "容易把 token 预算花在推理上，导致记忆提炼返回空内容。")
        field_label(llm_holder, 6, "思考强度", "effort")
        effort_row = ttk.Frame(llm_holder)
        effort_row.grid(row=6, column=1, columnspan=2, sticky="w", pady=(8, 0))
        # 档位由 sync_effort_row() 动态画：可选项**只由本机 ReMe 那一层决定**（硬约束，
        # 见 backend_effort_values）；端点声明的模型能力只作为提示显示。写死的列表正是
        # 上一轮让 max 混进配置、导致 as_llm 起不来、服务整体失败的原因。
        effort_note = ttk.Label(llm_holder, text="", font=FONT_HINT, foreground=THEME["muted"],
                                wraplength=620, justify="left")
        effort_note.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 0))
        llm_status = ttk.Label(llm_holder, text="", font=FONT_HINT, wraplength=560, justify="left")
        llm_status.grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))
        actions = ttk.Frame(llm_holder)
        actions.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(actions, text="测试连接", command=lambda: run_test()).pack(side="left")
        ttk.Label(actions, text="测试只读；保存时会自动把地址 / 模型 / Key 写入 .env"
                                "（手工编辑：托盘右键「打开 .env（凭据）」）",
                  font=FONT_HINT, foreground=THEME["muted"]).pack(side="left", padx=(10, 0))
        llm_widgets.extend([llm_base_entry, llm_model_box, llm_key_entry, llm_tokens_entry,
                            llm_thinking_check])

        # ================= 3. Embedding =================
        emb_holder = section(3, "Embedding（语义检索）", "按语义检索，与 LLM 分开配置；同一份记忆可用不同服务。",
                             "embedding", lambda: reset_section("embedding"))
        emb_head = ttk.Frame(emb_holder)
        emb_head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(4, 0))
        emb_enable_check = ttk.Checkbutton(
            emb_head, text="启用语义检索", variable=feature_vars["embedding"],
            command=lambda: on_edit("feature", "embedding", feature_vars["embedding"].get()),
        )
        emb_enable_check.pack(side="left")
        emb_marker = ttk.Label(emb_head, text=" ?", foreground=THEME["link"], cursor="hand2")
        emb_marker.pack(side="left")
        Tooltip(emb_marker, GLOSSARY["Embedding"])
        field_label(emb_holder, 1, "地址")
        emb_base_entry = ttk.Entry(emb_holder, textvariable=emb_base_var, width=46)
        emb_base_entry.grid(row=1, column=1, sticky="w", pady=(8, 0))
        field_label(emb_holder, 2, "模型")
        emb_model_entry = ttk.Entry(emb_holder, textvariable=emb_model_var, width=26)
        emb_model_entry.grid(row=2, column=1, sticky="w", pady=(8, 0))
        field_label(emb_holder, 3, "API Key")
        emb_key_entry = ttk.Entry(emb_holder, textvariable=emb_key_var, width=42, show="*")
        emb_key_entry.grid(row=3, column=1, sticky="w", pady=(8, 0))
        emb_key_show = tk.BooleanVar(value=False)
        emb_key_toggle = ttk.Checkbutton(
            emb_holder, text="显示", variable=emb_key_show,
            command=lambda: emb_key_entry.configure(show="" if emb_key_show.get() else "*"))
        emb_key_toggle.grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        install_key_field(emb_key_entry, emb_key_var, emb_key_toggle, emb_key_show)
        inline_hint(emb_holder, 3, "（已配置；不动这里＝不改，输入新 Key 才覆盖）" if emb_key_present
                    else "（未配置；填写后保存）")
        field_label(emb_holder, 4, "维度", None, "embedding_dims", lambda: reset_field("embedding", "dimensions"))
        emb_dims_entry = ttk.Entry(emb_holder, textvariable=emb_dims_var, width=10)
        emb_dims_entry.grid(row=4, column=1, sticky="w", pady=(8, 0))
        hint(emb_holder, 5, "需与模型输出一致，否则检索不可用。")
        emb_status = ttk.Label(emb_holder, text="", font=FONT_HINT, wraplength=560, justify="left")
        emb_status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
        emb_actions = ttk.Frame(emb_holder)
        emb_actions.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(emb_actions, text="测试 Embedding", command=lambda: run_emb_test()).pack(side="left")
        ttk.Label(emb_actions, text="未通过测试也可保存，但不会生效", font=FONT_HINT,
                  foreground=THEME["muted"]).pack(side="left", padx=(10, 0))
        emb_widgets.extend([emb_enable_check, emb_base_entry, emb_model_entry, emb_key_entry, emb_dims_entry])
        # 离开输入框即视为一次编辑：把输入收进草稿，避免后续操作把它回写覆盖掉
        for widget in (llm_base_entry, llm_model_box, llm_key_entry, llm_tokens_entry,
                       emb_base_entry, emb_model_entry, emb_key_entry, emb_dims_entry):
            widget.bind("<FocusOut>", lambda _event: on_field_exit(), add="+")

        # ================= 4. 记忆管道 =================
        pipe_holder = section(4, "记忆管道", "自动整理的频率、范围与上限。auto_dream 是常规操作里最贵的一环。",
                              "pipeline", lambda: reset_section("pipeline"))
        auto_head = ttk.Frame(pipe_holder)
        auto_head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(4, 0))
        auto_enable_check = ttk.Checkbutton(auto_head, text="启用自动记忆与整理（Auto Memory + Auto Dream）",
                                           variable=auto_enable_var, command=lambda: on_auto_toggle())
        auto_enable_check.pack(side="left")
        auto_marker = ttk.Label(auto_head, text=" ?", foreground=THEME["link"], cursor="hand2")
        auto_marker.pack(side="left")
        Tooltip(auto_marker, "开启后：对话会被自动提炼成每日记忆卡片（Auto Memory），"
                             "每天再沉淀为长期记忆节点（Auto Dream）。\n"
                             "两项都需要【LLM 与模型】填好地址与 Key；开启会自动转为自定义模式。")
        auto_hint = ttk.Label(pipe_holder, text="", font=FONT_HINT, foreground=THEME["muted"],
                              wraplength=600, justify="left")
        auto_hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))
        field_label(pipe_holder, 2, "扫描天数", "scan_days")
        scan_days_box = ttk.Combobox(pipe_holder, textvariable=scan_days_var, width=8, state="readonly",
                                     values=[str(value) for value in SCAN_DAY_CHOICES])
        scan_days_box.grid(row=2, column=1, sticky="w", pady=(8, 0))
        scan_days_box.bind("<<ComboboxSelected>>", lambda _e: on_edit("pipeline", "scan_days", scan_days_var.get()))
        inline_hint(pipe_holder, 2, "官方默认 2；调大≠更准，更慢更贵")
        field_label(pipe_holder, 3, "每次最多沉淀", "max_units")
        max_units_box = ttk.Combobox(pipe_holder, textvariable=max_units_var, width=8, state="readonly",
                                     values=[str(value) for value in MAX_UNIT_CHOICES])
        max_units_box.grid(row=3, column=1, sticky="w", pady=(8, 0))
        max_units_box.bind("<<ComboboxSelected>>", lambda _e: on_edit("pipeline", "max_units", max_units_var.get()))
        inline_hint(pipe_holder, 3, "官方默认 5；调大只更慢更贵")
        field_label(pipe_holder, 4, "整理计划")
        # 宽度按当前语言里最长的档位名算，英文 "Daily 23:00 (default)" 才不会被截断
        cron_width = max(16, max(len(t(label)) for _expr, label in CRON_PRESETS) + 2)
        cron_box = ttk.Combobox(pipe_holder, textvariable=cron_choice_var, width=cron_width,
                                state="readonly",
                                values=[t(label) for _expr, label in CRON_PRESETS] + [t("自定义…")])
        cron_box.grid(row=4, column=1, sticky="w", pady=(8, 0))
        cron_box.bind("<<ComboboxSelected>>", lambda _e: on_cron_choice())
        cron_entry = ttk.Entry(pipe_holder, textvariable=cron_custom_var, width=16)
        cron_entry.grid(row=4, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        cron_entry.bind("<FocusOut>", lambda _e: on_edit("pipeline", "dream_cron", cron_custom_var.get()))
        preview_label = ttk.Label(pipe_holder, text="", font=FONT_UI, foreground=THEME["text2"],
                                  wraplength=600, justify="left")
        preview_label.grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))
        pipe_status = ttk.Label(pipe_holder, text="", font=FONT_HINT, wraplength=600, justify="left")
        pipe_status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))
        pipe_actions = ttk.Frame(pipe_holder)
        pipe_actions.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        dream_button = ttk.Button(pipe_actions, text="立即整理一次", command=lambda: run_dream_now())
        dream_button.pack(side="left")
        ttk.Button(pipe_actions, text="重建索引", command=lambda: run_reindex_now()).pack(side="left", padx=6)
        reindex_button = pipe_actions.winfo_children()[-1]
        reindex_scope_box = ttk.Combobox(pipe_actions, textvariable=reindex_scope_var,
                                         values=["all", "bm25"], state="readonly", width=10)
        reindex_scope_box.pack(side="left")
        Tooltip(dream_button, "立即整理（auto_dream）：需要 Auto Dream 已启用、LLM 已配置、服务运行中。\n"
                              "会调用模型并写入 digest/，产生 token 费用。")
        pipe_hint = ttk.Label(pipe_holder, text="", font=FONT_HINT, foreground=THEME["muted"],
                              wraplength=600, justify="left")
        pipe_hint.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        dream_history = ttk.Label(pipe_holder, text="", font=FONT_HINT, foreground=THEME["muted"],
                                  wraplength=600, justify="left")
        dream_history.grid(row=9, column=0, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Button(pipe_holder, text="刷新整理记录", command=lambda: refresh_dream_history()).grid(
            row=10, column=0, sticky="w", pady=(4, 0))
        dream_widgets.extend([scan_days_box, max_units_box, cron_box, cron_entry, dream_button])

        def on_expose_mode() -> None:
            """切换「官方默认 / 自定义」。

            选回官方**不重置**已勾的集合——draft 里一直留着，再点自定义还是上次那份。
            """
            on_edit("expose", "custom", expose_mode_var.get() == "custom")

        def apply_expose_preset(kind: str) -> None:
            """「只勾推荐 / 全选 / 全不选」：只动界面上的勾，保存时才落盘。"""
            if kind == "all":
                chosen = set(expose_vars)
            elif kind == "none":
                chosen = set()
            else:
                chosen = {job for job in expose_vars
                          if EXPOSE_JOB_INFO.get(job, ("可选",))[0] in ("必留", "推荐")}
            for job, var in expose_vars.items():
                var.set(job in chosen)
            collect_widgets()
            refresh_state()

        # ================= 5. MCP 工具暴露 =================
        job_holder = section(5, "MCP 工具暴露",
                             "其他 Agent（Codex / VS Code）通过 HTTP 与 MCP 能主动调用的操作。"
                             "这里只决定「外部能不能调」；ReMe 自己的定时任务（索引维护、做梦）不受影响。",
                             "expose", lambda: reset_section("expose"))
        # 二选一：普通用户只需要「官方默认」，专业用户才进自定义。选回官方**不清空**
        # 已勾的集合，再点自定义还是上次那份——draft 里一直留着。
        expose_mode_row = ttk.Frame(job_holder)
        expose_mode_row.grid(row=0, column=0, columnspan=3, sticky="w", pady=(4, 0))
        official_radio = ttk.Radiobutton(expose_mode_row, text="官方默认：全部开放",
                                         value="official", variable=expose_mode_var,
                                         command=lambda: on_expose_mode())
        official_radio.pack(side="left")
        official_mark = ttk.Label(expose_mode_row, text=" ?", foreground=THEME["link"], cursor="hand2")
        official_mark.pack(side="left")
        Tooltip(official_mark, t("不写 service.jobs，ReMe 的原生行为：注册进服务的每个 Job 都对外开放。"
                                 "普通用户保持这一项即可；它和没装这个助手时的行为完全一致。"))
        custom_row = ttk.Frame(job_holder)
        custom_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        custom_radio = ttk.Radiobutton(custom_row, text="自定义：只开放我勾选的",
                                       value="custom", variable=expose_mode_var,
                                       command=lambda: on_expose_mode())
        custom_radio.pack(side="left")
        custom_mark = ttk.Label(custom_row, text=" ?", foreground=THEME["link"], cursor="hand2")
        custom_mark.pack(side="left")
        Tooltip(custom_mark, t("写 service.jobs，只把下面勾选的 Job 对外开放。"
                               "适合「虚拟机里的 Agent 只该读写记忆」这类场景。"
                               "没勾的 Job 外部调不到，但 ReMe 内部的定时任务照常使用它们。"))
        # 判据常驻：勾与不勾各自什么时候才对，必须写在**同一个位置**、两种状态下都不变。
        # 以前两种状态各说一句「当前是什么」，都是坏消息的样子，用户看不出该选哪个。
        expose_rule = ttk.Label(
            job_holder, font=FONT_HINT, foreground=THEME["muted"], justify="left", wraplength=680,
            text="什么时候用官方默认：只是自己用、外部客户端也都在本机 → 保持全开最省事。"
                 "什么时候用自定义：虚拟机等外部 Agent 只该读写记忆、你不想让它们删改 → 收窄。")
        expose_rule.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        expose_hint = ttk.Label(job_holder, text="", font=FONT_HINT, foreground=THEME["muted"],
                                justify="left", wraplength=680)
        expose_hint.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 以下只在「自定义」时出现：官方默认下没有可挑的东西，露出来只会让人以为要配。
        custom_box = ttk.Frame(job_holder)
        custom_box.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        preset_row = ttk.Frame(custom_box)
        preset_row.pack(anchor="w")
        for label, kind, note in (
            ("只勾推荐", "recommended",
             "勾上「必留」与「推荐」两组，也就是外部 Agent 读写记忆需要的那些；慎开项一律不勾。"),
            ("全选", "all", "32 项全勾上，风险最大，只有在确实需要时才用。"),
            ("全不选", "none", "一项都不勾＝不写白名单＝全部开放，和不选「自定义」是一样的效果。"),
        ):
            button = ttk.Button(preset_row, text=t(label),
                                command=lambda k=kind: apply_expose_preset(k))
            button.pack(side="left", padx=(0, 8))
            Tooltip(button, t(note))
        job_box = ttk.Frame(custom_box)
        job_box.pack(anchor="w", pady=(6, 0))
        job_row = 0
        for group_name, group_jobs in expose_job_rows():
            header = ttk.Frame(job_box)
            header.grid(row=job_row, column=0, columnspan=2, sticky="w", pady=(8, 2))
            tk.Label(header, text=t(group_name), font=FONT_BOLD,
                     foreground=THEME["text2"]).pack(side="left")
            group_mark = ttk.Label(header, text=" ?", foreground=THEME["link"], cursor="hand2")
            group_mark.pack(side="left")
            Tooltip(group_mark, t(EXPOSE_GROUP_NOTES.get(group_name, "")))
            job_row += 1
            for index, job in enumerate(group_jobs):
                tier, note = EXPOSE_JOB_INFO.get(job, ("可选", ""))
                cell = ttk.Frame(job_box)
                cell.grid(row=job_row + index // 2, column=index % 2, sticky="w",
                          padx=(16, 16), pady=2)
                box = ttk.Checkbutton(cell, text=t(EXPOSE_JOB_LABELS.get(job, job)),
                                      variable=expose_vars[job],
                                      command=lambda j=job: on_edit("expose", j, expose_vars[j].get()))
                box.pack(side="left")
                job_widgets[job] = box
                tk.Label(cell, text=t(tier), font=FONT_HINT,
                         foreground=THEME[EXPOSE_TIER_COLORS.get(tier, "muted")]).pack(side="left", padx=(6, 0))
                item_mark = ttk.Label(cell, text=" ?", foreground=THEME["link"], cursor="hand2")
                item_mark.pack(side="left")
                Tooltip(item_mark, t(note))
            job_row += (len(group_jobs) + 1) // 2
        # 只在**真的有灰项**时才说这句话：当前模式 / 功能开关下全都存在时，一个字都不显示，
        # 否则就是描述一个根本不存在的状态（用户会去找那些并不存在的灰项）。
        expose_gray_hint = ttk.Label(custom_box, text="", font=FONT_HINT,
                                     foreground=THEME["muted"], justify="left", wraplength=680)
        expose_gray_hint.pack(anchor="w", pady=(8, 0))

        # ================= 6. 自定义模式功能 =================
        feat_holder = section(6, "自定义模式功能", "逐项开关；关闭只停用入口或后台 Job，不删除已有数据。")
        headers = ("", "功能", "默认", "依赖", "效果", "")
        for col, text in enumerate(headers):
            tk.Label(feat_holder, text=text, font=FONT_BOLD, foreground=THEME["text2"]).grid(
                row=0, column=col, sticky="w", padx=(0, 14), pady=(4, 2))
        row_index = 1
        for group_name, keys in FEATURE_GROUPS:
            tk.Label(feat_holder, text=group_name, foreground=THEME["text"], font=FONT_BOLD).grid(
                row=row_index, column=0, columnspan=6, sticky="w", pady=(12, 4))
            row_index += 1
            for key in keys:
                item = FEATURES[key]
                box = ttk.Checkbutton(feat_holder, variable=feature_vars[key],
                                      command=lambda k=key: on_edit("feature", k, feature_vars[k].get()))
                box.grid(row=row_index, column=0, sticky="w", padx=(0, 14), pady=4)
                feature_widgets[key] = box
                name_box = ttk.Frame(feat_holder)
                name_box.grid(row=row_index, column=1, sticky="w", padx=(0, 14))
                tk.Label(name_box, text=t(item["name"]), font=FONT_UI, foreground=THEME["text"]).pack(side="left")
                marker = ttk.Label(name_box, text=" ?", foreground=THEME["link"], cursor="hand2")
                marker.pack(side="left")
                Tooltip(marker, f"{item['effect']}\n\n成本/性能：{item['impact']}")
                ttk.Label(feat_holder, text=t("开启") if item["official"] else t("关闭"), font=FONT_HINT).grid(
                    row=row_index, column=2, sticky="w", padx=(0, 14))
                ttk.Label(feat_holder, text=item["requires"], font=FONT_HINT, foreground=THEME["muted"]).grid(
                    row=row_index, column=3, sticky="w", padx=(0, 14))
                summary = t(item["effect"])
                summary = summary if len(summary) <= 46 else summary[:46] + "…"
                ttk.Label(feat_holder, text=summary, font=FONT_HINT, foreground=THEME["muted"]).grid(
                    row=row_index, column=4, sticky="w", padx=(0, 14))
                link = LinkLabel(feat_holder, "↺", lambda k=key: reset_feature(k))
                link.grid(row=row_index, column=5, sticky="w")
                Tooltip(link, t("把 ") + t(item["name"]) + t(" 恢复到基线值（该预设的标准值）"))
                reset_widgets[f"feature:{key}"] = link
                row_index += 1
        feature_note = ttk.Label(feat_holder, text="", font=FONT_HINT, foreground=THEME["muted"],
                                 wraplength=760, justify="left")
        feature_note.grid(row=row_index, column=0, columnspan=6, sticky="w", pady=(12, 0))

        # ================= 7. VM 隧道 =================
        vm_holder = section(7, "VM 隧道目标", "把 Windows 上的 ReMe 反向映射给虚拟机内的 Agent。")
        targets_data = deep_copy(CFG.get("targets", []))
        columns = ("enabled", "name", "connection", "remote_port", "key")
        tree = ttk.Treeview(vm_holder, columns=columns, show="headings", height=4, selectmode="browse")
        headings = {"enabled": "启用", "name": "名称", "connection": "SSH连接", "remote_port": "VM映射端口", "key": "密钥"}
        widths = {"enabled": 55, "name": 150, "connection": 280, "remote_port": 110, "key": 240}
        for key in columns:
            tree.heading(key, text=t(headings[key]))
            tree.column(key, width=widths[key], anchor="w")
        tree.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        vm_buttons = ttk.Frame(vm_holder)
        vm_buttons.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 4))

        def refresh_target_tree():
            tree.delete(*tree.get_children())
            for index, item in enumerate(targets_data):
                connection = f"{item.get('user')}@{item.get('host')}:{item.get('port', 22)}"
                key = str(item.get("key") or "")
                key_text = Path(key).name if key else ("~/.ssh（已发现）" if scan_local_keys() else "默认 ~/.ssh")
                tree.insert("", "end", iid=str(index),
                            values=(t("是") if item.get("enabled", True) else t("否"),
                                    item.get("name", "VM"), connection,
                                    item.get("remote_port", 22333), t(key_text)))

        def selected_index():
            selection = tree.selection()
            return int(selection[0]) if selection else None

        def add_vm():
            candidate = edit_target_dialog(root)
            if candidate:
                try:
                    validate_targets(targets_data + [candidate])
                    targets_data.append(candidate)
                    refresh_target_tree()
                    refresh_state()
                except ValueError as exc:
                    messagebox.showerror(APP_NAME, str(exc), parent=root)

        def edit_vm():
            index = selected_index()
            if index is None:
                messagebox.showinfo(APP_NAME, "请先选择一个VM目标", parent=root)
                return
            candidate = edit_target_dialog(root, targets_data[index])
            if candidate:
                proposed = targets_data[:index] + [candidate] + targets_data[index + 1:]
                try:
                    validate_targets(proposed)
                    targets_data[index] = candidate
                    refresh_target_tree()
                    refresh_state()
                except ValueError as exc:
                    messagebox.showerror(APP_NAME, str(exc), parent=root)

        def delete_vm():
            index = selected_index()
            if index is None:
                messagebox.showinfo(APP_NAME, "请先选择一个VM目标", parent=root)
                return
            if messagebox.askyesno(APP_NAME, f"确定删除 {targets_data[index]['name']}？", parent=root):
                targets_data.pop(index)
                refresh_target_tree()
                refresh_state()

        add_button = ttk.Button(vm_buttons, text="添加…", command=add_vm)
        add_button.pack(side="left")
        edit_button = ttk.Button(vm_buttons, text="编辑…", command=edit_vm)
        edit_button.pack(side="left", padx=(6, 0))
        delete_button = ttk.Button(vm_buttons, text="删除", command=delete_vm)
        delete_button.pack(side="left", padx=(6, 0))
        scan_button = ttk.Button(
            vm_buttons, text="扫描密钥…",
            command=lambda: (refresh_target_tree(),
                             messagebox.showinfo(APP_NAME, "本机 SSH 密钥扫描完成", parent=root)))
        scan_button.pack(side="left", padx=(6, 0))
        Tooltip(add_button, "添加一个 VM 目标；需要填写 SSH 用户名、主机、端口。")
        Tooltip(edit_button, "编辑选中的 VM 目标（先在上表里选中一行）。")
        Tooltip(delete_button, "删除选中的 VM 目标（不影响虚拟机本身）。")
        Tooltip(scan_button, "重新扫描本机 ~/.ssh 下可用的私钥，并刷新上表“密钥”列。")
        ttk.Label(vm_buttons, text="添加/编辑/删除作用于上表选中的那一行",
                  font=FONT_HINT, foreground=THEME["muted"]).pack(side="left", padx=(12, 0))

        def vm_button_fit() -> dict:
            """Whether each VM button is wide enough for its label (layout regression guard)."""
            import tkinter.font as tkfont
            font = tkfont.Font(font=FONT_UI)
            report = {}
            for widget in (add_button, edit_button, delete_button, scan_button):
                label = str(widget.cget("text"))
                report[label] = [int(widget.winfo_reqwidth()), int(font.measure(label) + 22)]
            return report

        refresh_target_tree()

        # ================= 底部固定栏 =================
        buttons = ttk.Frame(root)
        buttons.pack(fill="x", padx=12, pady=(6, 12))
        reset_all_button = ttk.Button(buttons, text="↺ 回到基线", command=lambda: reset_all(), state="disabled")
        reset_all_button.pack(side="left")
        Tooltip(reset_all_button, "把整份草稿恢复到基线（你本次的起点）。\n"
                                  "基线是“已保存配置”时，请用右侧的“放弃改动”。")
        footer_label = ttk.Label(buttons, text="", font=FONT_HINT, foreground=THEME["muted"])
        footer_label.pack(side="left", padx=10)
        toasts: list = []
        last_toast = {"text": ""}

        def toast(text: str, seconds: float = 3.0) -> None:
            """Small floating notice in the window's top-right corner, auto-dismissed."""
            text = t(text)
            last_toast["text"] = text
            for old in list(toasts):
                try:
                    old.destroy()
                except Exception:  # noqa: BLE001
                    pass
            toasts.clear()
            try:
                tip = tk.Toplevel(root)
                tip.wm_overrideredirect(True)
                tip.attributes("-topmost", True)
                frame = tk.Frame(tip, background=THEME["toast_bg"], padx=14, pady=9)
                frame.pack()
                tk.Label(frame, text=text, background=THEME["toast_bg"], foreground=THEME["toast_fg"],
                         font=FONT_UI, justify="left", wraplength=430).pack()
                root.update_idletasks()
                x = root.winfo_rootx() + max(12, root.winfo_width() - tip.winfo_reqwidth() - 26)
                y = root.winfo_rooty() + 52
                tip.wm_geometry(f"+{x}+{y}")
                toasts.append(tip)

                def dismiss():
                    if tip in toasts:
                        toasts.remove(tip)
                    try:
                        tip.destroy()
                    except Exception:  # noqa: BLE001
                        pass

                root.after(int(seconds * 1000), dismiss)
            except Exception as exc:  # noqa: BLE001 - a failed toast must not break the window
                log(f"toast failed: {exc}")

        def discard_all():
            if not messagebox.askyesno(APP_NAME, "放弃所有未保存的改动？", parent=root):
                return
            draft["mode"] = saved_snapshot[2]
            draft["features"] = deep_copy(saved_snapshot[0]["custom"])
            draft["llm"] = deep_copy(saved_snapshot[0]["llm"])
            draft["embedding"] = deep_copy(saved_snapshot[0]["embedding"])
            draft["pipeline"] = deep_copy(saved_snapshot[0]["pipeline"])
            draft["expose"] = deep_copy(saved_snapshot[0]["expose"])
            draft["reme_root"] = saved_snapshot[1]
            targets_data.clear()
            targets_data.extend(deep_copy(saved_snapshot[0].get("targets", [])))
            refresh_target_tree()
            apply_widgets()
            refresh_state()

        discard_button = ttk.Button(buttons, text="放弃改动", command=discard_all, state="disabled")
        discard_button.pack(side="right", padx=8)
        save_button = ttk.Button(buttons, text="验证并保存", command=lambda: save(), state="disabled")
        save_button.pack(side="right")

        # ================= 逻辑 =================
        def browse_root():
            selected = filedialog.askdirectory(initialdir=root_var.get(), title="选择ReMe安装根目录")
            if selected:
                root_var.set(selected)
                collect_widgets()
                refresh_state()

        def scan_root() -> None:
            """Look for existing installs; adopt the only hit, let the user pick among several."""
            found = scan_reme_installations()
            if not found:
                messagebox.showinfo(
                    APP_NAME,
                    "没有扫描到已安装的 ReMe。\n\n"
                    "可以点“复制安装提示词”，把它发给 DSH / Codex，让 agent 帮你装好并启动，"
                    "然后回到这里点“扫描…”确认。",
                    parent=root,
                )
                return
            if len(found) == 1:
                root_var.set(str(found[0]))
                collect_widgets()
                refresh_state()
                toast(f"已找到 ReMe：{found[0]}")
                return
            picked = choose_from_list(root, "选择 ReMe 安装目录",
                                      [str(path) for path in found], "扫描到多个 ReMe 安装：")
            if picked:
                root_var.set(picked)
                collect_widgets()
                refresh_state()
                toast(f"已切换 ReMe 目录：{picked}")

        def copy_install_prompt() -> None:
            prompt = reme_install_prompt(str(root_var.get().strip() or DEFAULT_REME_ROOT))
            root.clipboard_clear()
            root.clipboard_append(prompt)
            root.update_idletasks()
            toast("安装提示词已复制，可直接粘贴给 DSH / Codex")
            if messagebox.askyesno(APP_NAME, "安装提示词已复制到剪贴板。\n\n要现在看一下内容吗？", parent=root):
                messagebox.showinfo(APP_NAME, prompt, parent=root)

        def display_features() -> dict:
            return settings_display_features(draft)

        def on_mode_click(mode: str) -> None:
            """Switch the capability set only — everything the user filled in is preserved."""
            collect_widgets()
            previous_mode = draft["mode"]
            if not settings_load_mode(draft, mode, saved_snapshot[0], saved_snapshot[1], saved_snapshot[2]):
                apply_widgets()
                return
            toast(f"模式：{MODE_NAMES[previous_mode]} → {MODE_NAMES[mode]}"
                  f"（地址、模型、Key 等已保留；保存后生效）")
            apply_widgets()
            refresh_state()

        def on_auto_toggle() -> None:
            """Explicit「启用自动记忆与整理」switch: turns Auto Memory + Auto Dream on/off together."""
            collect_widgets()
            want = bool(auto_enable_var.get())
            was_mode = draft["mode"]
            degraded, _ = settings_apply_edit(draft, "feature", "auto_memory", want, saved_snapshot[0])
            settings_apply_edit(draft, "feature", "auto_dream", want, saved_snapshot[0])
            if degraded:
                toast(f"已开启自动记忆与整理 → 模式切换为{MODE_NAMES[draft['mode']]}"
                      "（需要【LLM 与模型】可用）" if want else "已关闭自动记忆与整理")
            else:
                toast("已开启自动记忆与整理" if want else "已关闭自动记忆与整理")
            apply_widgets()
            refresh_state()

        def undo_switch() -> None:
            draft["mode"] = saved_snapshot[2]
            draft["baseline"] = saved_snapshot[2] if saved_snapshot[2] != "custom" else BASELINE_SAVED
            draft["features"] = deep_copy(saved_snapshot[0]["custom"])
            draft["llm"] = deep_copy(saved_snapshot[0]["llm"])
            draft["embedding"] = deep_copy(saved_snapshot[0]["embedding"])
            draft["pipeline"] = deep_copy(saved_snapshot[0]["pipeline"])
            draft["expose"] = deep_copy(saved_snapshot[0]["expose"])
            toast("已撤销修改，回到已保存的配置")
            apply_widgets()
            refresh_state()

        def on_cron_choice() -> None:
            label = cron_choice_var.get()
            for expr, known in CRON_PRESETS:
                if label in (known, t(known)):   # 中英两种显示都要能反查到表达式
                    cron_custom_var.set(expr)
                    break
            else:
                cron_custom_var.set("")
            on_edit("pipeline", "dream_cron", cron_custom_var.get())

        def on_edit(section_name: str, key: str, value=None) -> None:
            """Apply one widget change; the mode label follows the values, not the other way round."""
            collect_widgets()  # 先把界面上的值（含刚输入的文字）收进草稿，避免被回写覆盖
            was_mode = draft["mode"]
            degraded, collapsed = settings_apply_edit(draft, section_name, key, value, saved_snapshot[0])
            if degraded:
                toast(f"已从{MODE_NAMES[was_mode]}转为自定义：只应用你刚改的这一项")
            elif collapsed:
                toast(f"配置已与{MODE_NAMES[collapsed]}完全一致 → 模式自动切换为{MODE_NAMES[collapsed]}")
            apply_widgets()
            refresh_state()

        def on_field_exit() -> None:
            """Leaving a text field counts as an edit: keep the typed value and refresh the counter."""
            collect_widgets()
            apply_widgets()
            refresh_state()

        def apply_widgets() -> None:
            mode_var.set(draft["mode"])
            root_var.set(draft["reme_root"])
            features = display_features()
            for key, var in feature_vars.items():
                var.set(bool(features.get(key)))
            llm = draft["llm"]
            llm_base_var.set(llm["base_url"])
            llm_model_var.set(llm["model"])
            llm_tokens_var.set(str(llm["max_tokens"]))
            llm_thinking_var.set(bool(llm["thinking_enable"]))
            llm_effort_var.set(EFFORT_LABELS.get(llm["reasoning_effort"], "不设置"))
            sync_effort_row()
            emb = draft["embedding"]
            emb_base_var.set(emb["base_url"])
            emb_model_var.set(emb["model"])
            emb_dims_var.set(str(emb["dimensions"]))
            pipe = draft["pipeline"]
            scan_days_var.set(str(pipe["scan_days"]))
            max_units_var.set(str(pipe["max_units"]))
            cron_custom_var.set(pipe["dream_cron"])
            labels = [t(label) for _expr, label in CRON_PRESETS]
            cron_choice_var.set(labels[0] if pipe["dream_cron"] == CRON_PRESETS[0][0] else
                                (labels[1] if pipe["dream_cron"] == CRON_PRESETS[1][0] else
                                 (labels[2] if pipe["dream_cron"] == CRON_PRESETS[2][0] else "自定义…")))
            expose_mode_var.set("custom" if draft["expose"]["custom"] else "official")
            auto_enable_var.set(bool(features.get("auto_memory")) and bool(features.get("auto_dream")))
            for job, var in expose_vars.items():
                var.set(job in draft["expose"]["jobs"])

        def collect_widgets() -> None:
            draft["reme_root"] = root_var.get().strip()
            draft["features"] = {key: var.get() for key, var in feature_vars.items()}
            draft["llm"].update(
                base_url=llm_base_var.get().strip(),
                model=llm_model_var.get().strip(),
                max_tokens=clamp_int(llm_tokens_var.get(), 512, 131072, 65536),
                thinking_enable=bool(llm_thinking_var.get()),
                reasoning_effort=EFFORT_VALUES.get(llm_effort_var.get(), ""),
            )
            draft["embedding"].update(
                base_url=emb_base_var.get().strip(),
                model=emb_model_var.get().strip(),
                dimensions=clamp_int(emb_dims_var.get(), 64, 8192, PRESET_EMBEDDING["dimensions"]),
            )
            draft["pipeline"].update(
                scan_days=clamp_int(scan_days_var.get(), 1, 14, 2),
                max_units=clamp_int(max_units_var.get(), 1, 20, 5),
                dream_cron=validate_cron(cron_custom_var.get() or cron_choice_var.get()),
            )
            draft["expose"] = {"custom": expose_mode_var.get() == "custom",
                               "jobs": [job for job, var in expose_vars.items() if var.get()]}

        def sync_effort_row() -> None:
            """重画档位行：可选项**只由 ReMe 那一层决定**（硬约束）。

            已经选中的值若不在合法集合里就清空并红字说明——绝不把它写进配置。
            端点声明的模型能力（来自「刷新模型」）只写进下方提示，**不用来禁用档位**。
            """
            for child in effort_row.winfo_children():
                child.destroy()
            effort_widgets.clear()
            options, reason, declared = effort_options(model_caps.get(llm_model_var.get().strip()))
            current = EFFORT_VALUES.get(llm_effort_var.get(), "")
            if not effort_is_allowed(current, options):
                if current:
                    effort_dropped["label"] = EFFORT_LABELS.get(current, current)
                    draft["llm"]["reasoning_effort"] = ""
                    llm_effort_var.set("不设置")
            else:
                effort_dropped["label"] = ""
            choices = [("", "不设置")] + [(value, EFFORT_LABELS[value])
                                         for value in options if value in EFFORT_LABELS]
            # 英文档位名更长（Very high）：按钮宽度按当前语言算，免得被裁掉
            width = max(6, max(len(t(label)) for _value, label in choices))
            for value, label in choices:
                button = ttk.Radiobutton(effort_row, text=t(label), value=label,
                                         variable=llm_effort_var, style="Segmented.Toolbutton",
                                         width=width,
                                         command=lambda v=value: on_edit("llm", "reasoning_effort", v))
                button.pack(side="left", padx=(0, 2))
                Tooltip(button, f"发给模型的参数：reasoning_effort={value or '（不发送）'}"
                                + ("\n默认：由模型自行决定" if not value else ""))
                effort_widgets.append(button)
            if effort_dropped["label"]:
                effort_note.configure(
                    text=t(f"原档位不被当前后台或模型接受，已清空为不设置：{effort_dropped['label']}"),
                    foreground=THEME["err"])
            elif declared:
                effort_note.configure(
                    text=t(EFFORT_REASON_NOTES["model_declared"])
                         + "、".join(EFFORT_LABELS.get(value, value) for value in declared)
                         + t(EFFORT_DECLARED_SUFFIX),
                    foreground=THEME["muted"])
            else:
                effort_note.configure(text=t(EFFORT_REASON_NOTES.get(reason, "")),
                                      foreground=THEME["muted"])

        def changed_items() -> list:
            return settings_changed_items(draft, saved_snapshot[0], saved_snapshot[1],
                                          saved_snapshot[2], targets_data)

        def enable(widget, on: bool) -> None:
            if not on:
                widget.configure(state="disabled")
            elif isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly")
            else:
                widget.configure(state="normal")

        def refresh_state() -> None:
            features = display_features()
            editable = draft["mode"] == "custom"
            model_features = any(features.get(key) for key in
                                 ("auto_memory", "auto_memory_cc", "auto_resource", "auto_dream", "chat"))

            if switch_note is not None:
                switch_note.configure(text=t(
                    "已转为自定义模式（基线：全功能预设）；保存后生效。"
                ) if (editable and draft["mode"] != saved_snapshot[2]) else "")

            service_up = service_is_healthy()
            llm_ready = bool(llm_base_var.get().strip() and llm_model_var.get().strip() and current_llm_key())
            gate = settings_gating(draft, service_up, llm_ready)
            installed = looks_like_reme_install(Path(str(draft["reme_root"] or "")) if draft["reme_root"] else reme_root())
            chips["服务"].configure(
                text=t("未安装") if not installed else (t("运行中") if service_up else t("已停止")),
                foreground=THEME["err"] if not installed else (THEME["ok"] if service_up else THEME["muted"]))
            for widget in llm_widgets:
                enable(widget, True)
            # 档位按钮按能力开关：模型不支持推理时整行不可点（只剩"不设置"）
            for widget in effort_widgets:
                enable(widget, bool(effort_options(model_caps.get(llm_model_var.get().strip()))[0]))
            for widget in emb_widgets[1:]:
                enable(widget, gate["embedding_fields"])
            for widget in dream_widgets:
                enable(widget, gate["dream_fields"])
            # 官方默认下把整块自定义内容收起来：没有可挑的东西，露出来只会让人以为必须配。
            # 用 grid_remove/grid 而不是 destroy：勾选状态要原样留着，切回来还是那份。
            expose_on = bool(draft["expose"]["custom"])
            if custom_box is not None:
                if expose_on:
                    custom_box.grid()
                else:
                    custom_box.grid_remove()
            for job, widget in job_widgets.items():
                enable(widget, gate["job_enabled"].get(job, False))
            grayed = [job for job in job_widgets if not gate["job_enabled"].get(job)]
            if expose_gray_hint is not None:
                # 只在**真的有灰项**时说话：全都存在时一个字都不显示，否则就是在描述一个
                # 根本不存在的状态，用户会去找那些并不存在的灰项。
                if grayed and expose_on:
                    names = "、".join(grayed[:8]) + ("…" if len(grayed) > 8 else "")
                    expose_gray_hint.configure(
                        text=t("有 {count} 项在当前模式或功能开关下不存在，已灰掉且不能勾："
                               ).format(count=len(grayed)) + names)
                    expose_gray_hint.pack(anchor="w", pady=(8, 0))
                else:
                    expose_gray_hint.pack_forget()
            if expose_hint is not None:
                # 只报「当前结果 + 具体数量」；该不该勾的判据在上面那条常驻说明里，不随状态变。
                # 计数写成句首的「已开放 N/M：」，两种状态因此完全平行，也不会被折行孤立。
                active = [job for job in job_widgets if gate["job_enabled"].get(job)]
                ticked = [job for job in active if job in draft["expose"]["jobs"]]
                if not active:
                    text = t("当前没有可对外暴露的 Job：MCP 功能关掉了，或者当前模式下这些 Job 都不存在。")
                    color = THEME["muted"]
                elif not expose_on:
                    text = (expose_open_prefix(len(active), len(active))
                            + t("下面这些 Job 全部对外开放，含会改动或删除记忆的那些——"
                                "ReMe 的 HTTP 没有鉴权，能连上 2333 的进程都能调。"))
                    color = THEME["warn"]
                elif not ticked:
                    # 一项都没勾＝不写白名单＝和上面不勾时一样是全部开放，所以计数写满而不是 0
                    text = (expose_open_prefix(len(active), len(active))
                            + t("一项都没勾＝不写白名单＝全部对外开放，和上面不勾时一样。"))
                    color = THEME["warn"]
                else:
                    text = (expose_open_prefix(len(ticked), len(active))
                            + t("外部只能调勾选的这些，其余的外部调不到，"
                                "但 ReMe 内部的索引维护与做梦照常运行。"))
                    missing = [name for name in ("health_check", "status") if name not in ticked]
                    if missing:
                        text += t(" 注意：health_check 与 status 没勾——helper 自己的健康探测、"
                                  "DSH 插件的状态卡片读的就是这两个，会显示成服务没起来。")
                        color = THEME["err"]
                    else:
                        color = THEME["ok"]
                expose_hint.configure(text=text, foreground=color)
            for widget in feature_widgets.values():
                enable(widget, True)

            reindex_scope_box.configure(values=gate["reindex_scopes"])
            if reindex_scope_var.get() == "embedding" and not gate["embedding_fields"]:
                reindex_scope_var.set("all")
            dream_button.configure(state="normal" if gate["dream_button"] else "disabled")
            reindex_button.configure(state="normal" if gate["reindex_button"] else "disabled")
            missing = []
            if not gate["dream_fields"]:
                missing.append("Auto Dream 未启用")
            if not llm_ready:
                missing.append("LLM 未就绪（地址 / 模型 / Key）")
            if not service_up:
                missing.append("服务未运行")
            auto_on = bool(features.get("auto_memory")) and bool(features.get("auto_dream"))
            auto_partial = (bool(features.get("auto_memory")) != bool(features.get("auto_dream")))
            if auto_on:
                auto_text = ("已开启：对话自动提炼为每日卡片，并按计划沉淀为长期记忆。"
                             + ("" if llm_ready else " ⚠ LLM 未就绪，现在还不会真正运行。"))
                auto_color = THEME["muted"] if llm_ready else THEME["warn"]
            elif auto_partial:
                auto_text = ("部分启用：" + ("仅 Auto Memory（没有整理）" if features.get("auto_memory")
                                            else "仅 Auto Dream（没有自动记录）")
                             + "；可在下方“自定义模式功能”里逐项调整。")
                auto_color = THEME["warn"]
            else:
                auto_text = ("未开启：记忆只由你手动写入（BM25 与关系检索仍可用）。"
                             "勾选后会自动转为自定义模式，并需要【LLM 与模型】可用。")
                auto_color = THEME["muted"]
            auto_hint.configure(text=t(auto_text), foreground=auto_color)

            root_path = Path(str(draft["reme_root"] or "")) if draft["reme_root"] else reme_root()
            if looks_like_reme_install(root_path):
                install_note.configure(text=t("已检测到 ReMe：") + str(root_path), foreground=THEME["ok"])
            else:
                found = scan_reme_installations()
                if found:
                    install_note.configure(
                        text=(t("这个目录里没有可用的 ReMe（需要 venv\\Scripts\\python.exe 与 reme 包）。")
                              + t("扫描到候选：") + str(found[0])
                              + t("（共 ") + str(len(found)) + t(" 个）—— 点“扫描…”采用。")),
                        foreground=THEME["warn"])
                else:
                    install_note.configure(
                        text=(t("未检测到 ReMe。先安装（Python 3.13 建 venv → pip install \"reme-ai[core]\" → ")
                              + t("reme start service.backend=http），或点“复制安装提示词”把它交给 DSH / Codex 安装。")),
                        foreground=THEME["warn"])
            pipe_hint.configure(text=t(
                "立即整理一次（auto_dream）：调用模型把 daily 沉淀为 digest，产生 token 费用。"
                + ("现在可用。" if gate["dream_button"] else "当前不可用 —— " + "、".join(missing) + "。")
                + "\n重建索引（reindex）：不调用模型、不产生费用，只需服务运行中"
                + ("（现在可用）。" if gate["reindex_button"] else "（当前不可用）。")
            ))

            feature_note.configure(text=t(
                f"自定义模式：已启用 {sum(1 for key in FEATURES if features.get(key))}/{len(FEATURES)} 项 → app-custom.yaml"
                if editable else
                f"{MODE_NAMES[draft['mode']]}（固定预设）：下表是该预设的能力；改动能力项会转为自定义模式。"
            ))
            if not model_features:
                llm_status.configure(text=t("未启用需要模型的能力，LLM 参数暂不影响运行。"), foreground=THEME["muted"])
            elif not (llm_base_var.get().strip() and llm_model_var.get().strip()):
                llm_status.configure(text=t("缺地址或模型名：填好后点“测试连接”。"), foreground=THEME["warn"])

            scan_days = clamp_int(scan_days_var.get(), 1, 14, 2)
            max_units = clamp_int(max_units_var.get(), 1, 20, 5)
            files, chars = daily_stats(scan_days)
            if features.get("auto_dream"):
                preview_label.configure(text=t(
                    f"{cron_echo(cron_custom_var.get() or cron_choice_var.get())}\n"
                    f"扫描范围：最近 {scan_days} 天的 daily（当前 {files} 个文件 / 约 {chars // 1000} 千字符）\n"
                    f"调用上界：1 次抽取 + 最多 {max_units} 次整理（每个 unit 一次）\n"
                    f"产出：最多 {max_units} 个长期节点 → digest/personal · procedure · wiki"
                ))
            else:
                preview_label.configure(text=t("Auto Dream 未启用：不会自动整理，也不会产生长期节点。"))

            emb_ok = bool(draft["embedding"]["probe_ok"])
            emb_status.configure(text=t(f"上次测试：{draft['embedding']['probe_detail']}"),
                                 foreground=THEME["ok"] if emb_ok else THEME["muted"])

            pending = changed_items()
            chips["模式"].configure(text=t(MODE_NAMES[draft["mode"]]), foreground=THEME["text"])
            chips["基线"].configure(text=t(settings_baseline_label(draft)), foreground=THEME["muted"])
            chips["服务"].configure(
                text=t("未安装") if not installed else (t("运行中") if service_up else t("已停止")),
                foreground=THEME["err"] if not installed else (THEME["ok"] if service_up else THEME["muted"]))
            # "就绪"必须是「填齐了**且**测过并通过」，不能只是字段非空——这里以前把
            # "什么都没测"显示成"就绪"，正好掩盖了会导致服务起不来的配置。
            llm_filled = bool(llm_base_var.get().strip() and llm_model_var.get().strip()
                              and current_llm_key())
            llm_probed = bool(draft["llm"].get("probe_ok"))
            chips["LLM"].configure(
                text=(t("未启用") if not model_features else
                      (t("就绪") if (llm_filled and llm_probed) else
                       (t("缺地址/Key") if not llm_filled else t("未通过测试")))),
                foreground=THEME["ok"] if (model_features and llm_filled and llm_probed)
                else THEME["muted"])
            chips["Embedding"].configure(
                text=(t("未启用") if not features.get("embedding") else (t("可用") if emb_ok else t("未通过测试"))),
                foreground=THEME["ok"] if (features.get("embedding") and emb_ok) else THEME["muted"])
            chips["未保存改动"].configure(text=str(len(pending)), foreground=THEME["warn"] if pending else THEME["muted"])

            if footer_label is not None:
                footer_label.configure(
                    text=t("没有未保存的改动" if not pending else
                           f"待保存：{'、'.join(pending[:4])}" + ("…" if len(pending) > 4 else "")),
                    foreground=THEME["muted"])
            if save_button is not None:
                save_button.configure(state="normal" if (pending and installed) else "disabled")
                if not installed:
                    Tooltip.update_text(save_button, "未检测到 ReMe 安装：请先安装（或点上方“复制安装提示词”）")
                else:
                    Tooltip.update_text(save_button, "把待保存改动写入配置并重启服务（窗口不会关闭）")
            if discard_button is not None:
                discard_button.configure(state="normal" if pending else "disabled")

            # 固定预设下也可能有被调过的参数，所以这里一视同仁地按“与基线是否有差异”判断。
            resettable = settings_resettable(draft, saved_snapshot[0])
            for name, widget in reset_widgets.items():
                on = name in resettable
                if isinstance(widget, LinkLabel):
                    widget.set_enabled(on)
                    if not editable:
                        widget.configure(font=widget.font_base)
                else:
                    widget.configure(state="normal" if on else "disabled")
            if reset_all_button is not None:
                baseline_is_saved = draft.get("baseline", BASELINE_SAVED) == BASELINE_SAVED
                reset_all_button.configure(
                    state="normal" if (resettable and not baseline_is_saved) else "disabled")

        def env_updates_for_save() -> dict:
            """保存时要写进 .env 的值（在 commit_draft() 之后调用）。

            密钥单独一条规则：**没动过字段就不写**。字段里放的是定长占位符，
            照搬会拿 40 个星号覆盖掉 .env 里的真 Key。
            """
            updates: dict = {}
            if CFG["llm"]["base_url"]:
                updates["LLM_BASE_URL"] = CFG["llm"]["base_url"]
                updates["LLM_BACKEND"] = "openai"
            if CFG["llm"]["model"]:
                updates["LLM_MODEL_NAME"] = CFG["llm"]["model"]
            if not key_field_untouched(llm_key_var.get()):
                updates["LLM_API_KEY"] = llm_key_var.get().strip()
            if CFG["embedding"]["base_url"]:
                updates["EMBEDDING_BASE_URL"] = CFG["embedding"]["base_url"]
                updates["EMBEDDING_BACKEND"] = "openai"
            if CFG["embedding"]["model"]:
                updates["EMBEDDING_MODEL_NAME"] = CFG["embedding"]["model"]
            if not key_field_untouched(emb_key_var.get()):
                updates["EMBEDDING_API_KEY"] = emb_key_var.get().strip()
            return updates

        def current_llm_key() -> str:
            """测试连接要用的 Key：字段没被动过（还是占位符）就用 .env 里存的那份。"""
            return key_field_value(llm_key_var.get(), str(read_env_values().get("LLM_API_KEY") or "").strip())

        def current_emb_key() -> str:
            return key_field_value(emb_key_var.get(), str(read_env_values().get("EMBEDDING_API_KEY") or "").strip())

        def reset_feature(key: str) -> None:
            collect_widgets()
            settings_reset_feature(draft, key, saved_snapshot[0])
            collapsed = settings_collapse_mode(draft)
            toast(f"{FEATURES[key]['name']} 已回到基线；模式：{MODE_NAMES[collapsed]}" if collapsed
                  else f"{FEATURES[key]['name']} 已回到基线")
            apply_widgets()
            refresh_state()

        def reset_section(section_name: str) -> None:
            collect_widgets()
            settings_reset_section(draft, section_name, saved_snapshot[0])
            collapsed = settings_collapse_mode(draft)
            label = {"llm": "LLM 参数", "embedding": "Embedding", "pipeline": "记忆管道",
                     "expose": "MCP 暴露"}.get(section_name, section_name)
            toast(f"{label} 已回到基线（{settings_baseline_label(draft)}）"
                  + (f"；模式自动切换为{MODE_NAMES[collapsed]}" if collapsed else ""))
            apply_widgets()
            refresh_state()

        def reset_all() -> None:
            collect_widgets()
            if not messagebox.askyesno(
                APP_NAME,
                f"回到基线（{settings_baseline_label(draft)}）？\n\n该操作只改草稿，保存后才生效；"
                "地址与 Key 不受影响。",
                parent=root,
            ):
                return
            settings_reset_all(draft, saved_snapshot[0])
            collapsed = settings_collapse_mode(draft)
            toast(f"已回到基线（{settings_baseline_label(draft)}）"
                  + (f"；模式自动切换为{MODE_NAMES[collapsed]}" if collapsed else ""))
            apply_widgets()
            refresh_state()

        def switch_theme_here() -> None:
            """Toggle the theme from inside the console, then keep working in this window."""
            toggle_theme()
            if PENDING_THEME["dirty"]:
                PENDING_THEME["dirty"] = False
                apply_theme()
                restyle_widgets(root)
            theme_button.configure(text=t("深色") if theme_name() == "light" else t("浅色"))
            apply_widgets()
            refresh_state()
            refresh_dream_history()

        def commit_draft() -> None:
            """Move the window's draft into the live config (the source of truth for saving)."""
            CFG["reme_root"] = draft["reme_root"]
            CFG["custom"] = deep_copy(draft["features"])
            CFG["llm"] = deep_copy(draft["llm"])
            CFG["embedding"] = deep_copy(draft["embedding"])
            CFG["pipeline"] = deep_copy(draft["pipeline"])
            CFG["expose"] = deep_copy(draft["expose"])
            CFG["targets"] = deep_copy(targets_data)

        def apply_saved_state(detail: str) -> None:
            """After a successful save: adopt the new baseline and keep the window open."""
            commit_draft()
            CFG["mode"] = draft["mode"]  # 真实保存流程里 switch_mode / save_config 已把它落盘
            saved_snapshot[0] = deep_copy(CFG)
            saved_snapshot[1] = str(reme_root())
            saved_snapshot[2] = CFG["mode"]
            apply_widgets()
            refresh_state()
            toast(f"已保存：{detail}（窗口保持打开）", seconds=6)

        def set_llm_status(ok: bool, text: str) -> None:
            llm_status.configure(text=("✔ " if ok else "✘ ") + t(text),
                                 foreground=THEME["ok"] if ok else THEME["err"])

        def refresh_models() -> None:
            set_llm_status(True, "正在从端点读取模型列表…")

            def done(ok, value) -> None:
                if not ok:
                    set_llm_status(False, str(value))
                    return
                ids, caps = value
                model_caps.clear()
                model_caps.update(caps)
                llm_model_box.configure(values=ids)
                sync_effort_row()
                # 措辞刻意避开「，其中 」这种通用片段：i18n 按最长片段替换，通用词会误伤别的句子
                set_llm_status(True, f"读取到 {len(ids)} 个模型" + ("（含能力信息）" if caps else ""))

            submit(lambda: fetch_models_detailed(llm_base_var.get().strip(), current_llm_key()), done)

        def run_test() -> None:
            """Test only when the request could actually succeed: no key, no request."""
            collect_widgets()
            base_url = llm_base_var.get().strip()
            model = llm_model_var.get().strip()
            if not base_url or not model:
                messagebox.showwarning(APP_NAME, "请先填写 Base URL 与模型名。", parent=root)
                set_llm_status(False, "缺少 Base URL 或模型名：未测试")
                return
            if not current_llm_key():
                messagebox.showwarning(APP_NAME, "需要 LLM_API_KEY（本地网关可填任意值，例如 sk-local）。",
                                       parent=root)
                set_llm_status(False, "需要 LLM_API_KEY：未测试")
                return
            effort = EFFORT_VALUES.get(llm_effort_var.get(), "")
            set_llm_status(True, "正在测试（最长 60s）…")

            def done(ok, message) -> None:
                # 与 embedding 对齐：结论落进草稿，状态条才有据可依，保存时也会持久化
                draft["llm"]["probe_ok"] = bool(ok)
                draft["llm"]["probe_detail"] = message
                set_llm_status(ok, message)
                refresh_state()

            submit(lambda: test_llm(base_url, model, current_llm_key(),
                                    bool(llm_thinking_var.get()), effort), done)

        def run_emb_test() -> None:
            """Same rule for embeddings: a missing key is reported instead of a failed call."""
            collect_widgets()
            base_url = emb_base_var.get().strip()
            model = emb_model_var.get().strip()
            if not base_url or not model:
                messagebox.showwarning(APP_NAME, "请先填写 Embedding 的地址与模型名。", parent=root)
                emb_status.configure(text=t("✘ 缺少地址或模型名：未测试"), foreground=THEME["err"])
                return
            if not current_emb_key():
                messagebox.showwarning(APP_NAME, "需要 EMBEDDING_API_KEY。", parent=root)
                emb_status.configure(text=t("✘ 需要 EMBEDDING_API_KEY：未测试"), foreground=THEME["err"])
                return
            emb_status.configure(text=t("正在测试 Embedding（最长 45s）…"), foreground=THEME["muted"])
            dims = clamp_int(emb_dims_var.get(), 64, 8192, PRESET_EMBEDDING["dimensions"])

            def done(ok, message, probe_ok=False):
                draft["embedding"]["probe_ok"] = bool(probe_ok)
                draft["embedding"]["probe_detail"] = message
                emb_status.configure(text=("✔ " if ok else "✘ ") + t(message),
                                     foreground=THEME["ok"] if ok else THEME["warn"])
                refresh_state()

            submit(lambda: test_embedding(emb_base_var.get().strip(), emb_model_var.get().strip(),
                                          current_emb_key(), dims),
                   lambda ok, message, *rest: done(ok, message, rest[0] if rest else False))

        def set_pipe_status(ok: bool, text: str) -> None:
            pipe_status.configure(text=("✔ " if ok else "✘ ") + t(text),
                                  foreground=THEME["ok"] if ok else THEME["err"])

        def begin_dream() -> None:
            """Lock the job buttons while a dream is running (one run at a time from here)."""
            dream_button.configure(state="disabled", text=t("整理中…"))
            reindex_button.configure(state="disabled")
            set_pipe_status(True, "auto_dream 运行中（可能数分钟，期间按钮已禁用）…")

        def finish_dream(ok: bool, message: str) -> None:
            set_pipe_status(ok, message)
            dream_button.configure(text=t("立即整理一次"))
            refresh_state()
            refresh_dream_history()

        def run_dream_now() -> None:
            if not messagebox.askyesno(
                APP_NAME,
                "立即执行一次 auto_dream？\n\n会调用模型并修改 ReMe workspace（digest/ 与 interests.yaml）。",
                parent=root,
            ):
                return
            begin_dream()
            submit(lambda: run_reme_job("auto_dream", {
                "scan_days": clamp_int(scan_days_var.get(), 1, 14, 2),
                "max_units": clamp_int(max_units_var.get(), 1, 20, 5),
            }), finish_dream)

        def refresh_dream_history() -> None:
            """Show the last dream outcome parsed from ReMe's logs."""
            ok, detail = last_dream_summary()
            dream_history.configure(text=("" if ok else "· ") + t(detail),
                                    foreground=THEME["muted"] if ok else THEME["warn"])

        def run_reindex_now() -> None:
            scope = reindex_scope_var.get()
            note = "（embedding 范围会重新计算全库向量，可能产生费用）" if scope == "embedding" else ""
            if not messagebox.askyesno(APP_NAME, f"重建索引 scope={scope}？{note}", parent=root):
                return
            set_pipe_status(True, f"reindex({scope}) 运行中…")
            submit(lambda: run_reme_job("reindex", {"scope": scope}), set_pipe_status)

        def save() -> None:
            collect_widgets()
            pending = changed_items()
            if not pending:
                return
            features = draft["features"] if draft["mode"] == "custom" else preset_features(draft["mode"])
            if features.get("embedding") and not draft["embedding"]["probe_ok"]:
                if not messagebox.askyesno(APP_NAME, "Embedding 尚未通过测试，启用后很可能不生效。\n\n仍要保存吗？", parent=root):
                    return
            was_running = service_is_healthy()
            if was_running and Path(draft["reme_root"]).resolve() != reme_root().resolve():
                messagebox.showerror(APP_NAME, "ReMe运行中不能切换安装根目录；请先停止服务", parent=root)
                return
            if was_running and not messagebox.askyesno(
                APP_NAME, f"保存会重启 ReMe（约 10 秒）。\n\n待保存改动：{len(pending)} 项。继续？", parent=root
            ):
                return
            old_cfg = deep_copy(CFG)
            env_backup = env_file_text()
            try:
                validate_targets(targets_data)
                commit_draft()
                env_updates = env_updates_for_save()
                if env_updates:
                    write_env_values(env_updates)
                requested_mode = draft["mode"]
                valid, detail = validate_install(requested_mode)
                if not valid:
                    raise ValueError(detail)
                tunnels_were_running = any(TUNNEL_STATE.values())
                if tunnels_were_running:
                    stop_all_tunnels()
                old_mode = old_cfg["mode"]
                CFG["mode"] = old_mode
                save_config()
                if requested_mode != old_mode:
                    ok, switch_detail = switch_mode(requested_mode)
                    if not ok:
                        raise ValueError(switch_detail)
                else:
                    CFG["mode"] = requested_mode
                    save_config()
                    if was_running:
                        stop_service()
                        ok, start_detail = start_service(requested_mode)
                        if not ok:
                            raise ValueError(start_detail)
                        detail = detail + "；服务已按新配置重启"
                if tunnels_were_running and service_is_healthy():
                    tunnel_ok, tunnel_detail = start_all_tunnels()
                    if not tunnel_ok:
                        raise ValueError(tunnel_detail)
                apply_saved_state(detail)
                messagebox.showinfo(APP_NAME, "配置已保存。\n" + detail + "\n\n窗口保持打开，可继续调整。", parent=root)
                if TRAY_ICON:
                    refresh_tray_menu()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                changed = CFG != old_cfg
                CFG.clear()
                CFG.update(old_cfg)
                try:
                    write_env_text(env_backup)
                except Exception as env_exc:  # noqa: BLE001
                    log(f"env rollback failed: {env_exc}")
                if changed:
                    save_config()
                    if was_running:
                        stop_service()
                        start_service(old_cfg["mode"])
                messagebox.showerror(APP_NAME, str(exc), parent=root)

        apply_widgets()
        collect_widgets()   # 草稿对齐窗口显示值：此后所有判定都以窗口为准
        refresh_state()
        refresh_dream_history()
        translate_tree(root)
        restyle_widgets(root)   # plain tk widgets need the palette applied at build time too
        if env_merge["corrected"]:
            toast("已按 .env 校正：" + "、".join(env_merge["corrected"])
                  + "（ReMe 读的是 .env，保存后会写回配置）", seconds=6.5)
        elif env_merge["filled"]:
            toast("已从 .env 补全：" + "、".join(env_merge["filled"]) + "（保存后会写入配置文件）", seconds=5.5)
        if harness is not None:
            try:
                harness({
                    "root": root,
                    "set_mode": lambda mode: on_mode_click(mode),
                    "toggle_auto": lambda value: (auto_enable_var.set(bool(value)), on_auto_toggle()),
                    "auto_enabled": lambda: bool(auto_enable_var.get()),
                    "edit": lambda section, key, value: on_edit(section, key, value),
                    "run_llm_test": lambda: run_test(),
                    "run_emb_test": lambda: run_emb_test(),
                    "vm_button_fit": vm_button_fit,
                    "install_note": lambda: install_note.cget("text"),
                    "scan_installations": lambda: [str(path) for path in scan_reme_installations()],
                    "install_prompt": lambda: reme_install_prompt(str(root_var.get().strip() or DEFAULT_REME_ROOT)),
                    "copy_prompt": lambda: copy_install_prompt(),
                    "set_root": lambda value: (root_var.set(value), collect_widgets(), refresh_state()),
                    "apply_saved_state": lambda: apply_saved_state("（测试）"),
                    "window_alive": lambda: bool(root.winfo_exists()),
                    "window_title": lambda: str(root.title()),
                    "theme": lambda: theme_name(),
                    "ui_lang": lambda: ui_lang(),
                    "toggle_theme": lambda: switch_theme_here(),
                    "palette": lambda: dict(THEME),
                    "translated": lambda text: t(text),
                    "dream_history": lambda: dream_history.cget("text"),
                    "refresh_dream_history": lambda: refresh_dream_history(),
                    "dream_button": lambda: str(dream_button.cget("state")),
                    "dream_button_text": lambda: str(dream_button.cget("text")),
                    "begin_dream": lambda: begin_dream(),
                    "finish_dream": lambda ok, message: finish_dream(ok, message),
                    "env_filled": lambda: list(env_merge["filled"]),
                    "key_masked": lambda name: str(
                        {"llm": llm_key_entry, "emb": emb_key_entry}[name].cget("show")) == "*",
                    "reveal_key": lambda name: {
                        "llm": llm_key_toggle, "emb": emb_key_toggle}[name].invoke(),
                    "key_visible": lambda name: not str(
                        {"llm": llm_key_entry, "emb": emb_key_entry}[name].cget("show")),
                    "key_toggle_enabled": lambda name: str(
                        {"llm": llm_key_toggle, "emb": emb_key_toggle}[name].cget("state")) != "disabled",
                    "key_entry": lambda name: {"llm": llm_key_entry, "emb": emb_key_entry}[name],
                    "effective_key": lambda name: {"llm": current_llm_key(), "emb": current_emb_key()}[name],
                    "placeholder": lambda: KEY_MASK_PLACEHOLDER,
                    "env_updates": lambda: env_updates_for_save(),
                    "env_corrected": lambda: list(env_merge["corrected"]),
                    "reset_section": lambda name: reset_section(name),
                    "reset_feature": lambda key: reset_feature(key),
                    "mode": lambda: draft["mode"],
                    "baseline": lambda: draft.get("baseline"),
                    "baseline_label": lambda: settings_baseline_label(draft),
                    "last_toast": lambda: last_toast["text"],
                    "draft": lambda: deep_copy(draft),
                    "display_features": lambda: dict(display_features()),
                    "resettable": lambda: set(settings_resettable(draft, saved_snapshot[0])),
                    "collapse": lambda: settings_collapse_mode(draft),
                    "reset_links": lambda: {name: getattr(widget, "enabled", None)
                                            for name, widget in reset_widgets.items()},
                    "set_field": lambda name, value: {
                        "llm_base": llm_base_var, "llm_model": llm_model_var, "llm_key": llm_key_var,
                        "llm_tokens": llm_tokens_var, "emb_base": emb_base_var, "emb_model": emb_model_var,
                        "emb_key": emb_key_var, "emb_dims": emb_dims_var,
                    }[name].set(value),
                    "field": lambda name: {
                        "llm_base": llm_base_var, "llm_model": llm_model_var, "llm_key": llm_key_var,
                        "llm_tokens": llm_tokens_var, "emb_base": emb_base_var, "emb_model": emb_model_var,
                        "emb_key": emb_key_var, "emb_dims": emb_dims_var,
                    }[name].get(),
                    "gate": lambda: settings_gating(
                        draft, service_is_healthy(),
                        bool(llm_base_var.get().strip() and llm_model_var.get().strip() and current_llm_key())),
                    "ui_state": lambda: {
                        "emb_fields": [str(w.cget("state")) for w in emb_widgets[1:]],
                        "dream_fields": [str(w.cget("state")) for w in dream_widgets],
                        "jobs": {job: str(widget.cget("state")) for job, widget in job_widgets.items()},
                        "dream_button": str(dream_button.cget("state")),
                        "reindex_button": str(reindex_button.cget("state")),
                        "save_button": str(save_button.cget("state")),
                        "reset_all_button": str(reset_all_button.cget("state")),
                        "footer": footer_label.cget("text"),
                        "llm_status": llm_status.cget("text"),
                        "emb_status": emb_status.cget("text"),
                        "chips": {name: widget.cget("text") for name, widget in chips.items()},
                    },
                    "close": root.destroy,
                })
            except Exception as exc:  # noqa: BLE001 - a broken harness must not break the window
                log(f"settings harness failed: {exc}")
        if autoclose_ms:
            root.after(autoclose_ms, root.destroy)
        root.after(80, lambda: canvas.yview_moveto(0.0))

    ui()   # 在 UI 线程里同步构建，不做 mainloop：事件循环由常驻的根窗口提供

def status_text(_item=None) -> str:
    state = state_copy()
    names = {"stopped": "已停止", "starting": "启动中", "running": "运行中", "stopping": "停止中", "error": "异常"}
    return t("ReMe状态：") + t(names.get(state["phase"], state["phase"]))


def mode_text(_item=None) -> str:
    return t("当前模式：") + t(MODE_NAMES[CFG["mode"]]) + t("（只读，请在 ReMe 控制台里修改）")


def tunnel_text(_item=None) -> str:
    targets = [target for target in CFG.get("targets", []) if target.get("enabled", True)]
    connected = sum(1 for target in targets if TUNNEL_STATE.get(target_key(target)))
    return t("VM隧道：") + f"{connected}/{len(targets)}"


def attach_dialog(parent, dialog) -> None:
    """把对话框挂到父窗口上 —— **只在父窗口真的可见时才挂**。

    Tk 的规矩：master 处于 withdrawn 状态时，设成它 transient 的 Toplevel 会**跟着被
    withdraw**，而且 `deiconify()` 也救不回来。实测三个变体（master 为隐藏根窗口）：

        transient(parent)              → ismapped=0  viewable=0  state=withdrawn
        不设 transient                 → ismapped=1  viewable=1  state=normal
        transient + deiconify()        → ismapped=0  viewable=0  state=withdrawn

    本应用的常驻根窗口**一直是隐藏的**（它只当 Tk 解释器用，见 ui_thread_main），而控制台
    没开着时 `ui_parent()` 返回的正是它 —— 所以「无脑 transient」的后果就是**对话框永不
    显示**，用户点了菜单什么都不出现。transient 只是「置顶于父窗口 + 不进任务栏」的
    锦上添花，父窗口不可见时它毫无意义，因此直接跳过。
    """
    try:
        if parent is not None and parent.winfo_exists() and parent.winfo_viewable():
            dialog.transient(parent)
    except tk.TclError:
        pass


def ui_dialog(title: str, message: str, buttons: list[tuple[str, object]]) -> None:
    """模态对话框：标题 + 正文 + 按钮组（每个按钮 = 文案 + 回调，回调可为 None）。

    用在**用户主动发起、并且会等着看结果**的动作上（检查更新、执行更新）。这类动作用
    气泡不合适：气泡会被系统的专注助手吞掉；而「已经是最新」本来就没有别的反馈，
    用户只会以为点了没反应。更新成功尤其如此——进程马上就要退出，气泡根本来不及被看见
    （实测用户就是因为这个以为更新失败了）。右键菜单项照旧保留，只是结论走对话框。
    """
    def build() -> None:
        parent = ui_parent()
        dialog = tk.Toplevel(parent)
        dialog.title(f"{t(APP_NAME)} · {title}")
        attach_dialog(parent, dialog)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=message, font=FONT_UI, wraplength=460,
                  justify="left").pack(anchor="w", fill="x")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(16, 0))

        def pick(action) -> None:
            dialog.destroy()
            if callable(action):
                action()

        for label, action in reversed(buttons):
            ttk.Button(row, text=label,
                       command=lambda a=action: pick(a)).pack(side="right", padx=(6, 0))
        dialog.update_idletasks()
        dialog.grab_set()
        dialog.focus_force()

    ui_post(build)


def reme_version_text(_item=None) -> str:
    """ReMe（服务）版本行。只反映 ReMe **自己**的更新结论。"""
    version = reme_versions().get("reme-ai", "")
    if not version:
        return t("ReMe版本：") + t("未安装")
    text = t("ReMe版本：") + version
    if REME_UPDATE_STATE.get("checked_for") != version:
        return text
    if REME_UPDATE_STATE.get("error"):
        return text + t("（检查更新失败）")
    latest = str(REME_UPDATE_STATE.get("latest") or "")
    if latest and version_is_newer(latest, version):
        return text + t("（有新版 ") + latest + "）"
    return text + t("（已是最新）")


def helper_version_text(_item=None) -> str:
    """ReMe 助手自己的版本行 —— 以前它和 ReMe 的结论共用一份状态，两件事混成一句。"""
    text = t("ReMe助手版本：") + VERSION
    if not HELPER_UPDATE_STATE.get("checked"):
        return text
    if HELPER_UPDATE_STATE.get("detail"):
        return text + t("（检查更新失败）")
    if HELPER_UPDATE_STATE.get("newer"):
        return text + t("（有新版 ") + str(HELPER_UPDATE_STATE.get("latest") or "") + "）"
    return text + t("（已是最新）")


def tray_check_reme_update() -> None:
    """托盘「检查 ReMe 更新…」：后台查询，结论用对话框呈现。"""
    def work() -> None:
        current = reme_versions().get("reme-ai", "")
        ok, detail = check_reme_update()
        if not ok:
            ui_dialog(t("检查 ReMe 更新"), detail,
                      [(t("复制 ReMe 更新步骤（交给 AI 执行）"), copy_upgrade_prompt_from_tray),
                       (t("关闭"), None)])
            return
        latest = str(REME_UPDATE_STATE.get("latest") or "")
        if latest and version_is_newer(latest, current):
            ui_dialog(t("检查 ReMe 更新"),
                      t("ReMe 有新版本 ") + latest + t("（本机 ") + current + t("）。") + "\n\n"
                      + t("更新 ReMe 会动配置、依赖与配套工具，所以由 AI 按步骤执行："
                          "点下面的按钮复制提示词，粘贴给 AI 即可。"),
                      [(t("复制 ReMe 更新步骤（交给 AI 执行）"), copy_upgrade_prompt_from_tray),
                       (t("稍后"), None)])
        else:
            ui_dialog(t("检查 ReMe 更新"),
                      t("ReMe 已是最新版本（") + current + t("）。"),
                      [(t("好"), None)])

    threading.Thread(target=work, daemon=True).start()


def tray_check_helper_update() -> None:
    """托盘「检查 ReMe 助手更新…」：后台查询，结论用对话框呈现。"""
    def work() -> None:
        ok, detail = check_helper_update()
        if not ok:
            ui_dialog(t("检查 ReMe 助手更新"), detail,
                      [(t("复制 ReMe 助手更新步骤（交给 AI 执行）"),
                        copy_helper_upgrade_prompt_from_tray),
                       (t("关闭"), None)])
            return
        if not HELPER_UPDATE_STATE.get("newer"):
            ui_dialog(t("检查 ReMe 助手更新"), t("已是最新版本") + f"（{VERSION}）",
                      [(t("好"), None)])
            return
        latest = str(HELPER_UPDATE_STATE.get("latest") or "")
        ui_dialog(t("检查 ReMe 助手更新"),
                  t("有新版本 ") + latest + t("（本机 ") + VERSION + t("）。") + "\n\n"
                  + t("点「立即更新」会自动下载、校验，把当前版本留在 _backup，然后重启。"),
                  [(t("立即更新"), run_helper_update),
                   (t("稍后"), None)])

    threading.Thread(target=work, daemon=True).start()


def run_helper_update() -> None:
    """下载 → 校验 → 交给独立进程替换，然后本进程退出。结论全程走对话框。"""
    left = {"done": False}

    def leave() -> None:
        if left["done"]:
            return
        left["done"] = True
        if TRAY_ICON is not None:
            shutdown_tray(TRAY_ICON)

    def work() -> None:
        ok, detail = download_and_apply_helper_update()
        if not ok:
            ui_dialog(t("更新 ReMe 助手"), detail,
                      [(t("复制 ReMe 助手更新步骤（交给 AI 执行）"),
                        copy_helper_upgrade_prompt_from_tray),
                       (t("关闭"), None)])
            return
        ui_dialog(t("更新 ReMe 助手"),
                  detail + "\n\n" + t("替换完成后新版本会自己启动；点「立即重启」马上开始。"),
                  [(t("立即重启"), leave)])
        # 没人点也要走：更新器正等着这个进程退出才能替换文件。
        threading.Timer(30.0, leave).start()

    threading.Thread(target=work, daemon=True).start()


def copy_upgrade_prompt_from_tray() -> None:
    """把「更新步骤」提示词放进剪贴板。

    刻意**不做**一键升级：升级会动配置、依赖和配套工具，必须先让 AI 分析并等用户确认。
    """
    def work() -> None:
        copied = False
        try:
            prompt = reme_upgrade_prompt(str(CFG.get("reme_root") or DEFAULT_REME_ROOT))
            copied = copy_to_clipboard(prompt)
        except Exception as exc:  # noqa: BLE001
            log(f"tray copy upgrade prompt failed: {exc}")
        notify("更新步骤已复制，粘贴给 AI 完成更新" if copied
               else "复制失败，请稍后再试")

    ui_post(work)   # 剪贴板要一个活着的 Tk 窗口 → 只能在 UI 线程里做


def copy_prompt_from_tray() -> None:
    """Tray shortcut: put the install prompt on the clipboard and say so."""
    def work() -> None:
        copied = False
        try:
            prompt = reme_install_prompt(str(CFG.get("reme_root") or DEFAULT_REME_ROOT))
            copied = copy_to_clipboard(prompt)
        except Exception as exc:  # noqa: BLE001
            log(f"tray copy prompt failed: {exc}")
        notify("安装提示词已复制，粘贴给 DSH / Codex 即可" if copied else "复制失败，请在控制台里点“复制安装提示词”")

    ui_post(work)   # 剪贴板要一个活着的 Tk 窗口 → 只能在 UI 线程里做


def menu_text(source: str):
    """托盘菜单项文案（延迟到「重建菜单」时求值）。

    pystray 的 win32 后端在创建菜单时就调用 text/enabled/checked 这些回调，所以
    语言或状态一变就得重建菜单——切换语言时必须 refresh_tray_menu()，否则右键菜单
    会一直停在启动时的语言（这正是之前「切了英文右键还是中文」的原因）。
    """
    return lambda _item: t(source)


MENU_DIRTY = {"dirty": False}


GUI_INMENUMODE = 0x00000004


def menu_is_open() -> bool:
    """系统弹出菜单是否正开着。

    开着的时候重建菜单会把它关掉（pystray 的 _update_menu 是 DestroyMenu+CreatePopupMenu），
    表现就是「鼠标滑着滑着突然失焦」。所以先问一句。

    探测方式：菜单模态标记（GUI_INMENUMODE）挂在**调用 TrackPopupMenu 的那个线程**上，
    而托盘窗口并不会因此变成前台窗口（实测过），所以遍历本进程所有线程去问；
    顺带把「前台窗口就是系统菜单类 #32768」这条也留作兜底。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]

        user32 = ctypes.windll.user32
        for thread in threading.enumerate():
            thread_id = getattr(thread, "native_id", None)
            if not thread_id:
                continue
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not user32.GetGUIThreadInfo(int(thread_id), ctypes.byref(info)):
                continue
            if info.flags & GUI_INMENUMODE:
                return True
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            name = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hwnd, name, 32)
            if name.value == "#32768":
                return True
        return False
    except Exception:  # noqa: BLE001 - 探测失败就当没开着
        return False


def refresh_tray_menu(force: bool = False) -> None:
    """重画托盘菜单；菜单正开着就推迟，避免把它关掉。"""
    if TRAY_ICON is None:
        return
    if not force and menu_is_open():
        MENU_DIRTY["dirty"] = True
        return
    MENU_DIRTY["dirty"] = False
    try:
        TRAY_ICON.menu = build_menu()
    except Exception as exc:  # noqa: BLE001 - 托盘不该因为菜单出错而崩
        log(f"tray menu refresh failed: {exc}")


def menu_refresh_loop() -> None:
    """把「菜单开着时被推迟的重画」补上。"""
    while not STOP_EVENT.wait(1.5):
        if MENU_DIRTY["dirty"]:
            refresh_tray_menu()


def tray_signature() -> tuple:
    """菜单上会显示出来的状态；只有它变了才值得重画菜单。"""
    state = state_copy()
    targets = CFG.get("targets", [])
    connected = sum(1 for target in targets
                    if target.get("enabled", True) and TUNNEL_STATE.get(target_key(target)))
    return (state.get("phase"), bool(state.get("healthy")), connected, len(targets),
            reme_installed(), reme_versions().get("reme-ai", ""), theme_name(), ui_lang(),
            bool(CFG.get("start_tunnels_with_reme")), bool(CFG.get("start_on_launch")))


def build_menu() -> pystray.Menu:
    return pystray.Menu(
        # 分组顺序 = 使用频率：状态(只读) → 控制台 → 服务 → VM 隧道 → 打开 → 设置 → 退出。
        # 每个区内部也按常用度排；「未检测到 ReMe」只在该出现的时候出现。
        pystray.MenuItem(status_text, None, enabled=False),
        # 两个版本行分开：ReMe（服务）在前，ReMe 助手（本工具）在后。
        # 以前只有一行「ReMe版本」，助手的更新结论也被贴在上面，两件事混成一句。
        pystray.MenuItem(reme_version_text, None, enabled=False),
        pystray.MenuItem(helper_version_text, None, enabled=False),
        pystray.MenuItem(mode_text, None, enabled=False),
        pystray.MenuItem(tunnel_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        # 分区与版本行同序：先 ReMe，再 ReMe 助手；每区最后一项都是「交给 AI」的兜底。
        # 检查与更新都弹对话框（用户主动点了这一项，他会等着看结果）。
        pystray.MenuItem(menu_text("检查 ReMe 更新…"),
                         lambda _icon, _item: tray_check_reme_update(),
                         enabled=lambda _item: reme_installed()),
        pystray.MenuItem(menu_text("复制 ReMe 更新步骤（交给 AI 执行）"),
                         lambda _icon, _item: copy_upgrade_prompt_from_tray(),
                         enabled=lambda _item: reme_installed()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(menu_text("检查 ReMe 助手更新…"),
                         lambda _icon, _item: tray_check_helper_update()),
        pystray.MenuItem(menu_text("下载并更新 ReMe 助手"),
                         lambda _icon, _item: run_helper_update(),
                         enabled=lambda _item: bool(HELPER_UPDATE_STATE.get("newer"))),
        pystray.MenuItem(menu_text("复制 ReMe 助手更新步骤（交给 AI 执行）"),
                         lambda _icon, _item: copy_helper_upgrade_prompt_from_tray()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(menu_text("ReMe 控制台…"), lambda _icon, _item: show_settings(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(menu_text("启动ReMe"), lambda _icon, _item: run_action(start_service),
                         enabled=lambda _item: reme_installed() and not service_is_healthy()),
        pystray.MenuItem(menu_text("停止ReMe"), lambda _icon, _item: run_action(stop_service), enabled=lambda _item: service_is_healthy()),
        pystray.MenuItem(menu_text("重启ReMe"), lambda _icon, _item: run_action(restart_service), enabled=lambda _item: service_is_healthy()),
        pystray.MenuItem(menu_text("打开ReMe Studio"), lambda _icon, _item: webbrowser.open("http://127.0.0.1:2333/"), enabled=lambda _item: service_is_healthy()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(menu_text("VM目标"), build_targets_menu()),
        pystray.MenuItem(menu_text("启动全部VM隧道"), lambda _icon, _item: run_action(start_all_tunnels), enabled=lambda _item: service_is_healthy()),
        pystray.MenuItem(menu_text("停止全部VM隧道"), lambda _icon, _item: run_action(stop_all_tunnels)),
        pystray.MenuItem(menu_text("ReMe启动后启动隧道"), toggle_tunnels_on_start, checked=lambda _item: bool(CFG.get("start_tunnels_with_reme"))),
        pystray.Menu.SEPARATOR,
        # 配置都在控制台里改，托盘不再堆一排「打开本地文件」：常用的 workspace 留一个，
        # 其余（目录 / .env / 官方 default / 当前配置 / 日志 / 说明）收进「打开指引」。
        pystray.MenuItem(menu_text("打开 workspace"), lambda _icon, _item: open_path(reme_root() / "workspace")),
        pystray.MenuItem(menu_text("打开指引（文件在哪）…"), lambda _icon, _item: show_path_guide()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(menu_text("深色模式"), toggle_theme, checked=lambda _item: theme_name() == "dark"),
        pystray.MenuItem(menu_text("English / 中文"), toggle_language),
        pystray.MenuItem(menu_text("启动工具时启动ReMe"), toggle_start_on_launch, checked=lambda _item: bool(CFG.get("start_on_launch"))),
        pystray.MenuItem(menu_text("开机自启"), toggle_autostart, checked=lambda _item: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(menu_text("未检测到 ReMe —— 复制安装提示词"),
                         lambda _icon, _item: copy_prompt_from_tray(),
                         visible=lambda _item: not reme_installed()),
        pystray.MenuItem(menu_text("退出"), quit_app),
    )


def icon_font(size: int):
    """图标里的那个「R」用 TrueType 渲染；一个都取不到就退回 Pillow 自带字体。"""
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"):
        path = Path(os.environ.get("WINDIR") or r"C:\Windows") / "Fonts" / name
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)     # Pillow ≥ 10.1 的可缩放默认字体
    except TypeError:
        return ImageFont.load_default()


def make_icon(running: bool = True, tunnels: bool = False, size: int = 64) -> Image.Image:
    """托盘与 exe 共用的图标：圆底 + 「R」。

    坐标全部按比例算——同一个函数既要喂 16px 的 .ico 帧，也要喂 64px 的托盘图标；
    写死像素的话小尺寸会糊成一团。
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = "#26a269" if running else "#6c757d"
    margin = max(1, round(size * 0.10))
    ring = max(1, round(size * 0.045))
    draw.ellipse((margin, margin, size - margin - 1, size - margin - 1),
                 fill=color, outline="#f6f5f4", width=ring)
    font = icon_font(max(7, round(size * 0.58)))
    left, top, right, bottom = draw.textbbox((0, 0), "R", font=font)
    draw.text(((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
              "R", font=font, fill="white")
    if tunnels:
        dot = max(4, round(size * 0.26))
        draw.ellipse((size - dot - 1, size - dot - 1, size - 1, size - 1),
                     fill="#f5c211", outline="#ffffff", width=max(1, round(size * 0.03)))
    return image


def write_app_icon() -> Path:
    """生成 exe 用的多尺寸 .ico。

    每一帧单独按目标尺寸渲染，不靠缩放：256px 缩到 16px 的话那个「R」会糊。
    """
    frames = [make_icon(True, False, size) for size in ICON_SIZES]
    frames[-1].save(ICON_PATH, format="ICO",
                    sizes=[(size, size) for size in ICON_SIZES],
                    append_images=frames[:-1])
    return ICON_PATH


def icon_path() -> Path | None:
    """找到随包分发的 .ico。

    PyInstaller 6 的 onedir 会把 ``--add-data`` 放进 ``_internal\\``，不在 exe 旁边；
    源码运行时就在脚本目录。三处都找一遍，找不到就返回 None——窗口图标不是必需品。
    """
    candidates = [ICON_PATH, APP_DIR / "_internal" / ICON_PATH.name]
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        candidates.append(Path(bundle) / ICON_PATH.name)
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def apply_window_icon(root) -> None:
    """给窗口装上同一个图标。取不到文件就算了——源码运行或非 Windows 都可能没有。"""
    try:
        path = icon_path()
        if path is not None:
            # default= 会让此后新建的 Toplevel 也用这个图标，所以只需在根窗口设一次
            root.iconbitmap(default=str(path))
    except Exception as exc:  # noqa: BLE001 - 图标失败绝不能影响启动
        log(f"window icon failed: {exc}")


def monitor_loop() -> None:
    """定时探测服务与隧道。

    注意：以前这里每轮都无条件重画托盘菜单，而重画 = 销毁并重建菜单句柄——用户右键菜单
    正开着时就会「突然失焦」。现在只在菜单显示内容真的变了（状态签名不同）时才重画，
    而且 menu_is_open() 时会推迟。

    **第一轮立即执行**（先探测、后等待）。`refresh_tunnels()` 要给每台 VM 起 ssh 并等
    探测结果，VM 不在线时实测要 20 秒以上；它以前是启动路径上的**同步**调用、挡在托盘
    图标创建之前，于是那 20 多秒里进程活着却**没有任何托盘图标**——纯托盘应用这段时间
    完全无法操作，用户看到的往往还是上一次被杀掉的实例留下的幽灵图标，点了毫无反应。
    现在图标先立起来，真实状态由这里的第一轮在后台补上。
    """
    interval = CFG.get("probe_interval_sec", 20)
    last_signature = None
    last_icon = None
    while True:
        before = state_copy()
        refresh_service_state()
        refresh_tunnels()
        after = state_copy()
        if before.get("phase") != after.get("phase"):
            log(f"state changed {before.get('phase')} -> {after.get('phase')}")
        if TRAY_ICON is not None:
            icon_state = (bool(after["healthy"]), any(TUNNEL_STATE.values()))
            # 图标还没注册进外壳时改它没有意义：pystray 会发 NIM_MODIFY，而外壳里还没有
            # 这条记录，必然返回失败。**不要在 visible 之前更新 last_icon**，否则这一轮
            # 的比对结果被吃掉，真正生效的那次就永远不来了。
            if icon_state != last_icon and TRAY_ICON.visible:
                last_icon = icon_state
                TRAY_ICON.icon = make_icon(*icon_state)
            signature = tray_signature()
            if signature != last_signature:
                last_signature = signature
                refresh_tray_menu()
        # 等待放在最后：第一轮必须立刻探测（见上面的说明）
        if STOP_EVENT.wait(interval):
            return


def quit_watch_loop() -> None:
    """`--quit` 的接收端：轮询请求文件，发现就删掉它并走退出路径。

    为什么**单开一个循环**：monitor_loop 的节拍是 `probe_interval_sec`（默认 20 s），
    满足不了「`--quit` 后 2 秒内退出」的判据；这里用 1.0 s，且不碰探测节拍。
    """
    while not STOP_EVENT.wait(1.0):
        try:
            if not QUIT_REQUEST_PATH.exists():
                continue
            QUIT_REQUEST_PATH.unlink()
        except OSError as exc:  # noqa: BLE001 - 读不到就下一轮再看，别把线程弄死
            log(f"quit request unreadable: {exc}")
            continue
        log("quit requested via --quit")
        if TRAY_ICON is not None:
            shutdown_tray(TRAY_ICON)
        return


def refresh_aux_windows() -> None:
    """语言切换后刷新辅助窗口：指引窗口整体重建，说明文档只换标题。

    （说明文档的内容是磁盘上的中文 Markdown，本来就按原文显示。）
    """
    for win in list(AUX_WINDOWS):
        try:
            if not win.winfo_exists():
                continue
            if win is GUIDE_WINDOW.get("win"):
                win.destroy()
                _open_path_guide()
            else:
                win.title(app_title() + t(" · 控制台说明"))
        except tk.TclError:
            pass


def close_settings_window() -> None:
    """关闭控制台（可从任意线程调用，真正的 destroy 在 UI 线程里执行）。

    跨线程销毁 Tk 对象会让解释器崩掉（"Tcl_AsyncDelete: async handler deleted by the
    wrong thread"），跨线程调用 Tcl 更会永久挂死调用方（托盘线程），所以统一走队列。
    """
    def work() -> None:
        win = UI_HOST.get("win")
        if win is None:
            return
        try:
            win.destroy()
        except tk.TclError:
            pass
        if UI_HOST.get("win") is win:
            UI_HOST["win"] = None

    if in_ui_thread():
        work()
    else:
        ui_post(work)


def request_quit() -> int:
    """`--quit`：请正在运行的实例退出。

    它自己不清理任何东西 —— 只写一个请求文件，由运行中的实例在 quit_watch_loop 里接手、
    走 shutdown_tray()（摘隧道、停掉自己启动的 ReMe）。没有实例在跑时也返回 0：要达成的
    目标是「确保没有实例在跑」，而它已经成立。
    """
    running = not single_instance_free()
    try:
        QUIT_REQUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUIT_REQUEST_PATH.write_text(time.strftime("%Y-%m-%dT%H:%M:%S\n"), encoding="utf-8")
    except OSError as exc:
        log(f"--quit: cannot write {QUIT_REQUEST_PATH}: {exc}")
        print(f"cannot write the quit request: {exc}")
        return 1
    if running:
        detail = f"{APP_ID} is running; asked it to quit (gone within ~2 s)"
    else:
        detail = f"no running {APP_ID} instance found - nothing to stop"
        try:
            QUIT_REQUEST_PATH.unlink()
        except OSError:
            pass
    log(f"--quit: {detail}")
    print(detail)
    return 0


def begin_shutdown() -> None:
    """退出的第一步：停掉探测、摘掉隧道、停掉「自己启动的」那个 ReMe。

    抽出来是为了让托盘菜单退出与 `--quit` **走同一条清理路径** —— 不许有第二套关闭逻辑。
    """
    STOP_EVENT.set()
    stop_all_tunnels()
    if SERVICE_PROCESS is not None:
        stop_service()


def shutdown_tray(icon) -> None:
    """走完整退出路径（菜单项与 quit_watch_loop 共用）。"""
    begin_shutdown()

    def finish() -> None:
        host = UI_HOST.get("root")
        try:
            if host is not None:
                host.destroy()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)   # Tk 解释器已关闭：直接退出，避开 Tcl 线程析构竞态

    if UI_HOST.get("root") is not None:
        ui_post(finish)
        threading.Timer(4.0, lambda: os._exit(0)).start()   # UI 线程没响应也要能退出
    icon.stop()


def quit_app(icon, _item) -> None:
    """托盘菜单的「退出」。"""
    shutdown_tray(icon)


# ---------------------------------------------------------------------------
# 在线自更新（W4）
#
# 三段：查（GitHub Releases API）→ 下并校验（zip + sha256）→ 换（独立进程 + 自己退出）。
# 为什么非要"独立进程"：**Windows 上正在运行的 exe 与已加载的 DLL 换不掉**。所以流程是
# 先起一个 .bat，再由主进程走 shutdown_tray() 退出；.bat 等进程消失后铺文件、重启、自删。
# 这也是 tufup（PyUpdater 的继任者）在 Windows 上的做法。
#
# 配置已经不在安装目录了（见 CONFIG_PATH），所以这里可以整目录铺过去，不必给任何文件写例外。
# ---------------------------------------------------------------------------
HELPER_RELEASES_API = f"https://api.github.com/repos/KenneLu/{APP_ID}/releases/latest"
HELPER_ASSET_SUFFIX = "-windows-x64.zip"
HELPER_EXE = f"{APP_ID}.exe"
HELPER_UPDATE_LOG = LOCAL_DATA_DIR / "update.log"
# 旧版本备份放**用户数据目录**，不放安装目录里：
#   * 安装目录那份要用 robocopy /purge 清掉上一版的残留文件，备份若在里面就会被一起删；
#   * 而且备份若在 install 下，`robocopy install install\_backup /e` 会扫到自己的输出。
HELPER_UPDATE_BACKUP = LOCAL_DATA_DIR / "_backup"
# 等旧进程退出的上限：120 次 × 约 1 秒（`ping -n 2` 的节奏）
HELPER_UPDATE_WAIT = 120

# ReMe 助手自己的更新状态。**必须与 REME_UPDATE_STATE 分开**：这两个字典以前都叫
# UPDATE_STATE，后者在模块加载时把前者覆盖掉，于是两个检查共用一份 `latest`——
# 查完 ReMe 再查助手，助手的新版本号会显示在 **ReMe 版本行**上（用户看到
# 「ReMe版本：0.4.1.11（有新版 v1.0.12）」），而两条升级提示词也会互相拿到对方的
# 版本号当作升级目标。
HELPER_UPDATE_STATE: dict = {"checked": False, "latest": "", "newer": False, "detail": ""}

# .bat 模板。**ASCII-only**：cmd.exe 按机器 ANSI 代码页解析 .bat，中文注释会变乱码甚至
# 吃掉命令（build.bat 顶上写着同一条纪律）。解释一律留在 Python 侧。
# 刻意**不用括号块**：cmd 对块内 errorlevel 的解析不可靠，全程 goto 流程。
# 等待循环还刻意**不用管道**——理由写在循环上方，那是实测出来的。
# ⚠️ 等待循环用 `{exe}`（= HELPER_EXE）这个**镜像名**判断旧进程有没有退出。对当前所有
# 版本都是对的：更新器是 1.0.7 才有的，而 1.0.7 起 exe 就定名 reme-helper.exe，各版本
# 同名。**若以后重新引入带版本号的 exe 名，这里会误判成"旧进程已退出"并去覆盖被锁住的
# 文件**——改 HELPER_EXE 或改 exe 命名规则之前先回来看这条。
HELPER_UPDATE_BAT = r"""@echo off
setlocal
set "INSTALL={install}"
set "STAGE={stage}"
set "BACKUP={backup}"
set "LOG={log}"
echo [{stamp}] start install=%INSTALL% backup=%BACKUP% >> "%LOG%"
set "POLL=%LOG%.poll"
set /a tries=0
:wait
rem NO PIPE HERE, on purpose. This script is spawned with DETACHED_PROCESS and
rem therefore has no console, and in that context "tasklist | find" NEVER
rem RETURNS: find.exe blocks on stdin forever. The update then silently does not
rem happen - the app quits, the tray has already said "update started", and
rem nothing else ever occurs. Verified by spawning this exact script both ways:
rem with a console the pipeline finishes in 0.13s, detached it hangs
rem indefinitely. Sending the child's stdio to DEVNULL does not help; removing
rem the pipe does. So tasklist writes to a file and find reads that file.
tasklist /fi "imagename eq {exe}" /nh > "%POLL%" 2>nul
find /i "{exe}" "%POLL%" >nul
if errorlevel 1 goto gone
set /a tries+=1
if %tries% geq {limit} goto giveup
ping -n 2 127.0.0.1 >nul
goto wait
:gone
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
robocopy "%INSTALL%" "%BACKUP%" /e /njh /njs /nfl /ndl >nul
rem /purge also removes files the previous version left behind. The backup is
rem deliberately outside INSTALL, otherwise /purge would delete it too.
robocopy "%STAGE%" "%INSTALL%" /e /purge /njh /njs /nfl /ndl >> "%LOG%" 2>&1
echo [{stamp}] copied rc=%ERRORLEVEL% >> "%LOG%"
start "" "%INSTALL%\{exe}"
echo [{stamp}] done >> "%LOG%"
goto cleanup
:giveup
echo [{stamp}] aborted: {exe} still running after {limit}s >> "%LOG%"
:cleanup
del "%POLL%" >nul 2>nul
(goto) 2>nul & del "%~f0"
"""


def parse_version(text: str) -> tuple:
    """``'v1.0.7'`` → ``(1, 0, 7)``。取不到数字就给 ``(0,)``，**绝不抛**。"""
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(part) for part in parts[:3]) or (0,)


def _http_text(url: str, timeout: float = 8.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_ID}/{VERSION}",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def helper_latest_release() -> dict:
    """``GET releases/latest`` → ``{"tag", "zip", "sha256"}``。失败抛异常，调用方转成人话。"""
    data = json.loads(_http_text(HELPER_RELEASES_API))
    tag = str(data.get("tag_name") or "").strip()
    zip_url = sha_url = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.endswith(HELPER_ASSET_SUFFIX + ".sha256"):
            sha_url = url
        elif name.endswith(HELPER_ASSET_SUFFIX):
            zip_url = url
    if not tag or not zip_url:
        raise RuntimeError(t("发布页上没有可下载的 zip"))
    return {"tag": tag, "zip": zip_url, "sha256": sha_url}


def check_helper_update() -> tuple[bool, str]:
    """托盘「检查 ReMe 助手更新」：**只查、只提示**，绝不自动替换。

    刻意与 ReMe 的检查保持同一种交互（只提示、不升级）：升级会动配置与配套工具，
    该由用户决定什么时候做。
    """
    try:
        latest = helper_latest_release()
    except Exception as exc:  # noqa: BLE001 - 网络问题不该弄崩托盘
        HELPER_UPDATE_STATE.update(checked=True, latest="", newer=False, detail=str(exc))
        return False, t("检查更新失败：") + str(exc)
    newer = parse_version(latest["tag"]) > parse_version(VERSION)
    HELPER_UPDATE_STATE.update(checked=True, latest=latest["tag"], newer=newer, detail="")
    if newer:
        return True, t("有新版本，点「下载并更新」会自动替换并重启") + f"（{latest['tag']}）"
    return True, t("已是最新版本") + f"（{VERSION}）"


def download_and_apply_helper_update() -> tuple[bool, str]:
    """托盘「下载并更新」：下载 → 校验 sha256 → 解压 → 起 updater。

    它**不负责退出**：调用方看到 True 之后自己去 `shutdown_tray()`，好让托盘先把结果提示出来。
    """
    try:
        latest = helper_latest_release()
    except Exception as exc:  # noqa: BLE001
        return False, t("检查更新失败：") + str(exc)
    work = Path(tempfile.mkdtemp(prefix=f"{APP_ID}-update-"))
    zip_path = work / f"{APP_ID}{HELPER_ASSET_SUFFIX}"
    try:
        request = urllib.request.Request(latest["zip"],
                                         headers={"User-Agent": f"{APP_ID}/{VERSION}"})
        with urllib.request.urlopen(request, timeout=60.0) as response, zip_path.open("wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as exc:  # noqa: BLE001
        return False, t("下载更新包失败：") + str(exc)
    if latest["sha256"]:
        try:
            wanted = _http_text(latest["sha256"]).split()[0].strip().lower()
            actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        except Exception as exc:  # noqa: BLE001
            return False, t("校验更新包失败：") + str(exc)
        if wanted != actual:
            return False, t("更新包校验失败：sha256 对不上")
    stage = work / "stage"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(stage)
    except Exception as exc:  # noqa: BLE001
        return False, t("解压更新包失败：") + str(exc)
    if not (stage / HELPER_EXE).is_file():
        return False, t("更新包里没有 ") + HELPER_EXE
    text = HELPER_UPDATE_BAT.format(
        install=APP_DIR, stage=stage, backup=HELPER_UPDATE_BACKUP,
        log=HELPER_UPDATE_LOG, exe=HELPER_EXE,
        limit=HELPER_UPDATE_WAIT, stamp=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    script = Path(tempfile.gettempdir()) / f"{APP_ID}-update.bat"
    try:
        # cmd.exe 按机器 ANSI 代码页解析 .bat ⇒ 按 ANSI 落盘（安装路径里可能有中文）
        script.write_text(text, encoding="mbcs", errors="replace")
    except (LookupError, UnicodeError):
        script.write_text(text, encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=flags, close_fds=True)
    except OSError as exc:
        return False, t("启动更新程序失败：") + str(exc)
    log(f"update staged: {stage} -> {APP_DIR} (tag {latest['tag']}, bat {script})")
    return True, t("更新已开始，本窗口会关闭；新版本会自己起来")


def helper_upgrade_prompt(target: str = "") -> str:
    """给 AI 的**助手自己**更新提示词：两段式 —— 先只分析回报，等用户说「执行」才动手。

    与 `reme_upgrade_prompt` 的区别只是升级对象（那个升 **ReMe**，这个升 **助手本身**），
    但**不能互相复用**：牵动的东西、回滚方式都不一样。
    """
    root = str(APP_DIR)
    latest = (target or HELPER_UPDATE_STATE.get("latest")
              or t("（还没查过，请自行查 GitHub Releases 的最新 tag）"))
    running = t("运行中") if service_is_healthy() else t("已停止")
    return "\n".join([
        t("请帮我更新这台机器上的 ReMe 助手（Windows 托盘工具）。"),
        t("先只做分析，把方案报给我；等我说「执行」再动手。"),
        "",
        t("## 现状"),
        f"- {t('当前版本：')}{VERSION}",
        f"- {t('目标版本：')}{latest}",
        f"- {t('安装目录：')}{root}{t('（exe 固定叫 reme-helper.exe，名字不带版本号）')}",
        f"- {t('配置与日志：')}%LOCALAPPDATA%\\reme-helper\\{t('（已不在安装目录里）')}",
        f"- {t('ReMe 服务：')}http://127.0.0.1:2333{t('，当前')}{running}",
        f"- {t('开机自启：')}HKCU\\...\\Run{t(' 的 reme-helper 值，存的是 exe 的完整路径')}",
        "",
        t("## 第一阶段：只分析，不动手"),
        t("允许：读源码与 CHANGELOG、读配置、拉 GitHub Release 的元数据与 sha256。"),
        t("在我说「执行」之前：不要下载替换、不要停止服务、不要改注册表。"),
        t("请按这个格式回报："),
        t("1. 版本与来源：当前 → 目标，数据从哪来"),
        t("2. 新版有哪些变化（读 CHANGELOG.md）"),
        t("3. 影响面：配置格式变没变、自启指向的 exe 路径会不会变、ReMe 与隧道要不要重启"),
        t("4. 更新步骤：编号、简明、每一步带决策点"),
        t("5. 风险与回滚：回滚要给出一条具体命令"),
        t("6. 结论：有问题就列出来；没问题就说「没有问题」，然后停下等我回复「执行」"),
        "",
        t("## 第二阶段：我说「执行」之后"),
        t("1. 先备份整个安装目录（更新脚本自己也会备份到 %LOCALAPPDATA%\\reme-helper\\_backup）"),
        t("2. 退出运行中的助手：reme-helper.exe --quit"),
        t("3. 下载 zip 与 .sha256，校验通过再解压"),
        t("4. 把解压结果铺到安装目录，重启 reme-helper.exe"),
        t("5. 验证：health_check 通过、托盘版本行显示新版本"),
        t("6. 回报新版本号"),
        "",
        t("## 硬约束"),
        t("- 不要改 %LOCALAPPDATA%\\reme-helper\\config.json 的内容（需要时只备份）"),
        t("- 不要动 ReMe 的 workspace 与 .env"),
        t("- 任何一步失败就停下来告诉我，不要自行绕过"),
    ])


def copy_helper_upgrade_prompt_from_tray() -> None:
    """托盘：把「助手自己的更新步骤」放进剪贴板。

    与 ReMe 那条一样，刻意**不做**一键升级：更新会动安装目录与自启注册表，
    必须先让 AI 分析并等用户确认。
    """
    def work() -> None:
        copied = False
        try:
            copied = copy_to_clipboard(helper_upgrade_prompt())
        except Exception as exc:  # noqa: BLE001
            log(f"tray copy helper upgrade prompt failed: {exc}")
        notify("助手更新步骤已复制，粘贴给 AI 完成更新" if copied else "复制失败，请稍后再试")

    ui_post(work)   # 剪贴板要一个活着的 Tk 窗口 → 只能在 UI 线程里做


def smoke() -> int:
    output = DIAG_LOG_DIR / "smoke.log"
    output.parent.mkdir(parents=True, exist_ok=True)   # 发布包里没有 log/，必须自建
    # 具名检查，和 release_check 一致：失败时日志直接写出**哪一个**挂了。
    # 以前是个裸的 True/False 列表，CI 上只留下 checks=[True, True, ...]，
    # 定位失败项只能靠手数下标——第一次发版就是这么卡住的。
    checks: list[tuple[str, bool]] = []

    def check(name: str, value: object) -> None:
        checks.append((name, bool(value)))

    try:
        cfg = load_config()
        check("mode known", cfg.get("mode") in MODE_NAMES)
        check("custom keys", all(key in cfg.get("custom", {}) for key in FEATURES))
        check("llm keys", all(key in cfg.get("llm", {}) for key in ("base_url", "model", "max_tokens", "thinking_enable", "reasoning_effort")))
        check("pipeline keys", all(key in cfg.get("pipeline", {}) for key in ("scan_days", "max_units", "dream_cron")))
        check("embedding keys", all(key in cfg.get("embedding", {}) for key in ("base_url", "model", "dimensions", "probe_ok")))
        check("expose keys", all(key in cfg.get("expose", {}) for key in ("custom", "jobs")))
        check("presets differ", preset_features("minimal")["auto_dream"] is False and preset_features("full")["auto_dream"] is True)
        check("cron echo ok", cron_echo("0 23 * * *").startswith("下次整理："))
        check("cron echo rejects", cron_echo("bad cron").startswith("cron 格式不正确"))
        check("official default readable", bool(yaml.safe_load(official_default_path().read_text(encoding="utf-8"))))
        # 图标必须真的随包分发且找得到：否则窗口又会退回 Tk 的默认图标
        check("icon asset", icon_path() is not None)
        # 三种模式都要能从官方包推导出来：别人装了官方 ReMe 时 config/ 里一份都没有。
        # 全部写进临时目录，不去动用户正在用的那三份。
        with tempfile.TemporaryDirectory(prefix="reme-helper-modes-") as temp:
            for mode_name in MODE_ORDER:
                path = generate_mode_config(mode_name, Path(temp) / f"{mode_name}.yaml")
                made = yaml.safe_load(path.read_text(encoding="utf-8"))
                check(f"{mode_name}: generated", isinstance(made, dict) and bool(made))
                if mode_name == "full":
                    check(f"{mode_name}: extends default", made.get("extends") == "default")
                else:
                    check(f"{mode_name}: standalone", "extends" not in made)
                    check(f"{mode_name}: job set", set(made.get("jobs") or {}) == existing_job_names(mode_name))
                check(f"{mode_name}: mcp path", bool((made.get("service") or {}).get("mcp_path")))
        with tempfile.TemporaryDirectory(prefix="reme-helper-smoke-") as temp:
            old_mode = CFG["mode"]
            old_custom = deep_copy(CFG["custom"])
            old_expose = deep_copy(CFG["expose"])
            CFG["mode"] = "custom"
            CFG["custom"]["auto_memory"] = True
            CFG["expose"]["custom"] = True
            generated = generate_custom_config(Path(temp) / "app-custom.yaml")
            parsed = yaml.safe_load(generated.read_text(encoding="utf-8"))
            check("workspace dir", parsed["workspace_dir"].endswith("/workspace"))
            dream_cron = parsed["jobs"]["dream_cron"]
            check("dream cron", dream_cron["cron"] == CFG["pipeline"]["dream_cron"])
            check("scan days", dream_cron["steps"][0]["scan_days"] == CFG["pipeline"]["scan_days"])
            check("max units", dream_cron["steps"][0]["max_units"] == CFG["pipeline"]["max_units"])
            parameters = parsed["components"]["as_llm"]["default"]["parameters"]
            check("max tokens", parameters["max_tokens"] == CFG["llm"]["max_tokens"])
            check("thinking enable", parameters["thinking_enable"] == CFG["llm"]["thinking_enable"])
            # 白名单的不变量：每个名字都得**这份配置里真实存在**、且服务层加得进去。
            # 名字对不上时 base_service.add_jobs() 是 raise KeyError，ReMe 直接起不来；
            # 这条断言以前写成「等于 CFG 里存的那份」，等于把 bug 也一起断言进去了。
            allowed = parsed["service"]["jobs"]
            check("allowlist non-empty", bool(allowed))
            check("allowlist exists in jobs", all(name in parsed["jobs"] for name in allowed))
            check("allowlist not background", all((parsed["jobs"].get(name) or {}).get("backend")
                                                  not in ("background", "cron") for name in allowed))
            check("allowlist exposed", all(name in CFG["expose"]["jobs"] for name in allowed))
            check("health/status exposed", "health_check" in allowed and "status" in allowed)
            CFG["mode"] = old_mode
            CFG["custom"] = old_custom
            CFG["expose"] = old_expose
        check("reme exe", reme_exe().is_file())
        check("reme venv python", reme_python().is_file())
        # 这里**不**断言 mode_config_path(...) 存在。那三个文件是应用按需写进
        # **用户自己的** ReMe 根目录的，官方 wheel 一份都不带（只有 default /
        # beam / demo / lme）。断言它们存在，在开发机上（应用早就写过）为真，
        # 在任何干净机器上必假——第一次发版的 CI 就是栽在这一条上。
        # 真正的检查是上面那个临时目录块：三种模式都要能**只靠官方包**推出来。
        # 接入文档要真的随包分发：中英两份齐、正文完整、占位符已被现场值替换、
        # 附录 A 的捕获脚本已拼进去。少任何一项，用户点「阅读接入文档」时才报错，
        # 那时人已经在别的机器上了。
        doc_dir = doc_file_dir()
        check("doc dir", doc_dir.is_dir())
        for lang in ("zh", "en"):
            check(f"doc {lang} integration",
                  (doc_dir / lang / INTEGRATION_DOC_NAME).is_file()
                  and (doc_dir / lang / INTEGRATION_DOC_NAME).stat().st_size > 8000)
            check(f"doc {lang} config", (doc_dir / lang / CONFIG_DOC_NAME).is_file())
        check("doc capture script", (doc_dir / INTEGRATION_DOC_SCRIPT).is_file())
        doc_text = integration_doc_markdown()
        check("doc text length", len(doc_text) > SETUP_GUIDE_MIN_CHARS)
        check("doc placeholders filled", "<REME_PORT>" not in doc_text and "<REME_WORKSPACE>" not in doc_text)
        check("doc has codex+mcp", "codex exec" in doc_text and "mcp_servers.reme" in doc_text)
        check("doc has capture.mjs", "capture.mjs" in doc_text)
        failed = [name for name, ok in checks if not ok]
        detail = "PASS" if not failed else "FAIL missing=" + ",".join(failed)
    except Exception as exc:  # noqa: BLE001 - 通过日志文件上报
        detail = f"FAIL {type(exc).__name__}: {exc}"
    output.write_text(f"reme-helper smoke: {detail}\n", encoding="utf-8")
    # 同时打到 stdout：CI 上这个日志文件会随 runner 一起消失，只写盘的失败
    # 等于没人看得见。release_check 一直这么做，smoke 之前漏了。
    print(f"reme-helper smoke: {detail}")
    return 0 if detail == "PASS" else 1


def release_check() -> int:
    """在发布目录里跑一遍「这份包能不能直接发」的检查，产 release.log。

    打包版专用：它验证的是**打包产物**而不是源码——冻结环境、出厂配置模板，
    以及托盘图标在这台机器上真的画得出来。构建脚本据此把「发了才发现」的问题
    挡在 [DONE] 之前。
    """
    output = DIAG_LOG_DIR / "release.log"
    output.parent.mkdir(parents=True, exist_ok=True)   # 同上：发布包里没有 log/
    checks = []
    detail = ""
    try:
        checks.append(("frozen", bool(getattr(sys, "frozen", False))))
        # 配置现在住在用户数据目录。打包自检跑在发布目录里，且 build.bat 用
        # REME_HELPER_CONFIG 指向随包的出厂模板，所以这里断言的是「模板读得到」——
        # 若它读到开发机上的活配置，下面几条 llm empty / no personal targets 必然失败。
        checks.append(("config loaded", CONFIG_PATH.is_file()))
        checks.append(("app_dir == exe dir", Path(sys.executable).parent == APP_DIR))
        # 出厂模板的形状：其余键都在，且没有把开发机的数据带出去。
        # 注意 targets 不能断言「为空」——载入时会把空列表规范化成示例目标，
        # 所以这里断言的是「没有真实目标」，而不是「没有目标」。
        checks.append(("llm empty", not CFG["llm"].get("base_url") and not CFG["llm"].get("model")))
        targets = CFG.get("targets") or []
        personal = [entry for entry in targets
                    if entry.get("host") not in ("", "192.168.1.100") or entry.get("user") not in ("", "ubuntu")]
        checks.append(("no personal targets", not personal))
        checks.append(("no autostart", not CFG.get("start_on_launch") and not CFG.get("autostart")))
        checks.append(("probe not remembered",
                       not CFG["llm"].get("probe_ok") and not CFG["embedding"].get("probe_ok")))
        checks.append(("icon asset", icon_path() is not None))
        # 托盘与菜单的构造路径（打包后最容易缺资源的地方）
        icon = make_icon(True, False)
        checks.append(("icon drawn", icon is not None and icon.size[0] > 0))
        tray = pystray.Icon(APP_ID, icon, t(APP_NAME), build_menu())
        checks.append(("menu built", tray is not None))
        # 此刻没有别的托盘实例在跑（只探测，不占锁）
        checks.append(("no other instance", single_instance_free()))
        # 服务探测：不要求 ReMe 在跑，但必须能给出结论而不是抛异常
        checks.append(("service probe", isinstance(service_is_healthy(), bool)))
        doc = integration_doc_markdown()
        checks.append(("setup guide bundled", len(doc) > 20000 and "<REME_PORT>" not in doc))
        failed = [name for name, ok in checks if not ok]
        detail = "PASS" if not failed else "FAIL missing=" + ",".join(failed)
    except Exception as exc:  # noqa: BLE001 - 通过日志文件上报
        detail = f"FAIL {type(exc).__name__}: {exc}"
    output.write_text(f"reme-helper release: {detail}\n", encoding="utf-8")
    print(f"reme-helper release: {detail}")
    return 0 if detail == "PASS" else 1


def enable_dpi_awareness() -> None:
    """Let Windows draw the window natively instead of bitmap-stretching it.

    Without this, dragging or resizing the window feels laggy and the UI looks blurry on
    displays that use a scaling factor above 100%.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except Exception:  # noqa: BLE001 - older Windows builds expose only the user32 entry
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception as exc:  # noqa: BLE001 - never block startup for this
        log(f"dpi awareness failed: {exc}")


def lang_audit() -> int:
    """审查中英对照表：列出没翻的中文，并生成左右对照的 i18n_review.md。"""
    report = i18n.audit([Path(__file__), Path(__file__).resolve().parent / "guide.py"])
    review = DIAG_LOG_DIR / "i18n_review.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text(i18n.review_markdown(), encoding="utf-8")
    lines = [f"entries={len(i18n.TEXT)} missing={len(report['missing'])} "
             f"unused={len(report['table_only'])} duplicates={report['duplicates']} "
             f"empty_en={report['empty_en']} cjk_en={report['cjk_en']}", ""]
    lines += ["== 未覆盖 =="] + [f"{name}:{line}: {value}" for name, line, value in report["missing"]]
    lines += ["", "== 表里没被用上 =="] + list(report["table_only"])
    output = DIAG_LOG_DIR / "lang-audit.log"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        print(line)
    print(f"对照表已生成：{review}")
    return 0 if not (report["missing"] or report["duplicates"] or report["empty_en"]
                     or report["cjk_en"]) else 1


def ui_check() -> int:
    """Build the console window for real, then close it: catches layout/widget errors.

    Waits for the window to appear and fails on any exception raised inside the UI thread,
    so a silent "clicking the tray does nothing" regression turns into a red build.
    """
    output = DIAG_LOG_DIR / "ui-check.log"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        show_settings(autoclose_ms=2500)
        deadline = time.time() + 25
        while time.time() < deadline and UI_HOST.get("win") is None:
            time.sleep(0.1)
        appeared = UI_HOST.get("win") is not None
        time.sleep(0.4)
        close_settings_window()
        time.sleep(0.3)
        errors = list(UI_ERRORS)
        ok = appeared and not errors
        detail = "PASS" if ok else ("FAIL window=%s errors=%s" % (appeared, errors[:3]))
        output.write_text(f"reme-helper ui-check: {detail}\n", encoding="utf-8")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 - reported through the log file
        output.write_text(f"reme-helper ui-check: FAIL {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return 1


SINGLE_INSTANCE_HANDLE = None    # 必须留在模块级：句柄被回收就等于放锁
SINGLE_INSTANCE_NAME = APP_ID + "-tray"


def single_instance_free() -> bool:
    """探一下托盘互斥体现在是否空着，**不持有**它。

    诊断参数（如 --release）用它来判断「此刻没有别的实例在跑」，
    自己不能顺手把锁占住——否则自检进程退出前，用户紧接着启动的托盘会以为自己被抢了。
    """
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_NAME)
    if not handle:
        return True
    already = ctypes.get_last_error() == 183   # ERROR_ALREADY_EXISTS
    kernel32.CloseHandle(handle)
    return not already


def acquire_single_instance() -> bool:
    """抢一个命名互斥体：多开时只有第一个实例能继续，其余直接退出。

    必须在托盘与服务逻辑之前判定：工具默认可在启动时拉起 ReMe，
    两个实例同时启动会把「谁在管服务、谁在管隧道」搅乱。
    诊断类参数（--smoke / --ui-check / --release / --lang-audit / --make-icon）
    不走这里——它们本来就要能在工具运行时执行。
    """
    global SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    # 名字不带版本号：旧版本与新版也必须互斥，否则升级期间会出现两个托盘在抢同一份配置
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_NAME)
    if not handle:
        log("single-instance: CreateMutexW failed; continuing without the guard")
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    SINGLE_INSTANCE_HANDLE = handle
    return True


def warn_duplicate_instance() -> None:
    """重复启动时的提示：托盘里已经有一个在跑，这里只提示、不执行任何动作。

    提示框 6 秒后自动关掉——开机自启撞上手动启动时没人会去点「确定」。
    """
    message = t("ReMe 助手已在运行：请使用托盘里的那个实例（本次启动已忽略）。")
    log(message)
    try:
        window = tk.Tk()
        window.withdraw()
        window.after(6000, window.destroy)
        try:
            _raw_messagebox.showinfo(t(APP_NAME), message)
        except Exception:  # noqa: BLE001 - 自动关闭时 showinfo 会抛，属预期
            pass
        window.destroy()
    except Exception:  # noqa: BLE001 - 提示失败不该影响退出
        pass


def utf8_diag_streams() -> None:
    """把诊断参数的 stdout/stderr 固定成 UTF-8。

    这些参数的意义就是让脚本与 CI **读到结论**，而结论是中文的。stdout 被重定向时
    Python 用 locale 默认编码（这台机器是 cp936）写出去，读的人只会看到乱码——
    测试套件在 CI 上踩的是同一个坑（见 tests/conftest.py）。冻结的 noconsole 态下
    stream 是 None，reconfigure 会抛，所以整段包住。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - noconsole 冻结态没有 stream，不是错误
            pass


def install_tray_trace() -> None:
    """把托盘的每一次通知写进日志。

    为什么需要：托盘「点了没反应」有两种**从外面看一模一样**的原因 ——

      ① 外壳根本没把点击投递给本进程。最典型的是点在了**残留的幽灵图标**上：那个进程
         早就没了，图标却还留在通知区里（Windows 10 的图标缓存 `IconStreams` 会留住
         它），直到鼠标划过才可能被清掉。
      ② 点击到了，但菜单没弹出来。pystray 弹菜单前必须先 `SetForegroundWindow`
         （win32 后端 `_on_notify`），而 Windows 的前台锁定会让它失败；失败时
         `TrackPopupMenuEx` 立刻返回 0，表现为「右键毫无反应」。

    区分这两者只能靠**到达即记录**。日志量可忽略：一次用户交互一行。
    只包 win32 后端，且可重入（装两次不会套两层）。
    """
    try:
        import pystray._win32 as backend
    except Exception as exc:  # noqa: BLE001 - 非 win32 后端就不装
        log(f"tray trace: unavailable ({type(exc).__name__}: {exc})")
        return
    original = backend.Icon._on_notify
    if getattr(original, "_reme_traced", False):
        return
    kinds = {0x0202: "left-click", 0x0205: "right-click",
             0x0400: "NIN_SELECT", 0x0401: "NIN_KEYSELECT"}

    def traced(self, wparam, lparam):
        try:
            menu = "ok" if self._menu_handle else "MISSING"
        except Exception:  # noqa: BLE001
            menu = "?"
        log(f"tray notify: lparam=0x{lparam:X} ({kinds.get(lparam, 'other')}) menu={menu}")
        result = original(self, wparam, lparam)
        try:
            import ctypes
            fg = int(ctypes.windll.user32.GetForegroundWindow() or 0)
            ours = int(getattr(self, "_hwnd", 0) or 0)
            log(f"tray notify: handled; foreground=0x{fg:X} tray=0x{ours:X} "
                f"{'ok' if fg == ours else 'NOT-FOREGROUND (menu would fail)'}")
        except Exception:  # noqa: BLE001
            pass
        return result

    traced._reme_traced = True
    backend.Icon._on_notify = traced

    # 另一半：**`Shell_NotifyIcon` 的返回值被 pystray 丢掉了**（它的 `_message` 只调用、
    # 不看结果）。于是 NIM_ADD 失败时没有任何异常：窗口照建、注入消息照样能弹出菜单，
    # 但外壳里根本没有这个图标 —— 真实点击无处可去，日志也一片安静。
    # 包住那个 Win32 函数，把每次调用的结果写下来。
    try:
        win32 = backend.win32
        original_notify = win32.Shell_NotifyIcon
        codes = {0: "NIM_ADD", 1: "NIM_MODIFY", 2: "NIM_DELETE",
                 3: "NIM_SETFOCUS", 4: "NIM_SETVERSION"}

        state = {"added": False}

        def traced_notify(code, data):
            result = original_notify(code, data)
            if code == 0:                                   # NIM_ADD
                state["added"] = bool(result)
                log(f"tray: Shell_NotifyIcon(NIM_ADD) -> {result}"
                    + ("" if result else
                       "   <-- FAILED, no icon in the tray (real clicks cannot reach us)"))
            elif code == 2:                                 # NIM_DELETE
                state["added"] = False
                log(f"tray: Shell_NotifyIcon(NIM_DELETE) -> {result}")
            elif not result and state["added"]:
                # 注册成功之后的失败才是真问题。首次显示前的那一次 NIM_MODIFY 失败是
                # **pystray 自己的前奏**（`_base.visible` setter：`_icon_valid` 为假时先
                # `_update_icon()` 再 `_show()`），此时外壳里还没有这条记录，失败是必然的，
                # 不该记成故障 —— 否则每次启动都有一行吓人的假警报。
                import traceback
                frames = traceback.extract_stack()[:-1][-3:]
                where = " <- ".join(f"{f.name}:{f.lineno}" for f in reversed(frames))
                log(f"tray: Shell_NotifyIcon({codes.get(code, code)}) -> 0 FAILED from {where}")
            return result

        traced_notify._reme_traced = True
        win32.Shell_NotifyIcon = traced_notify
        log("tray trace: Shell_NotifyIcon instrumented")
    except Exception as exc:  # noqa: BLE001
        log(f"tray trace: Shell_NotifyIcon not instrumented ({type(exc).__name__}: {exc})")

    log("tray trace installed")


def main() -> int:
    global TRAY_ICON
    started = time.monotonic()
    enable_dpi_awareness()
    apply_theme()
    utf8_diag_streams()
    if "--make-icon" in sys.argv:
        try:
            path = write_app_icon()
            print(f"icon written: {path} ({', '.join(str(s) for s in ICON_SIZES)})")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"icon failed: {type(exc).__name__}: {exc}")
            return 1
    if "--smoke" in sys.argv:
        # 冻结环境里排障用：这些路径决定了诊断文件写到哪里，出问题时先看它们。
        print(f"app_dir={APP_DIR} package_dir={PACKAGE_DIR} run_dir={RUN_DIR}")
        print(f"diag_log_dir={DIAG_LOG_DIR} app_log_dir={APP_LOG_DIR} frozen={getattr(sys, 'frozen', False)}")
        return smoke()
    if "--ui-check" in sys.argv:
        return ui_check()
    if "--release" in sys.argv:
        return release_check()
    if "--lang-audit" in sys.argv:
        return lang_audit()
    # --quit 必须在 acquire_single_instance() 之前处理：它的整个意义就是「有实例在跑时
    # 请那个实例退出」，走到下面只会变成 warn_duplicate_instance() 然后自己退出。
    if "--quit" in sys.argv:
        return request_quit()
    # 更新流程的无头孪生入口：与托盘那两个菜单项走**完全同一段代码**，只是不需要点菜单。
    # 没有它，自更新只能在源码态验证——而这台机器上合成输入完全不落地（同 --quit 的理由），
    # 菜单点不了；更要紧的是**发出去的那个 exe 才是要验的对象**，源码态验不到它。
    if "--check-helper-update" in sys.argv:
        ok, detail = check_helper_update()
        print(detail)
        return 0 if ok else 1
    if "--helper-update" in sys.argv:
        ok, detail = download_and_apply_helper_update()
        print(detail)
        if not ok:
            return 1
        # 更新器要等这个镜像名消失才能替换文件，所以这里必须真的退出。
        # 直接 os._exit：正常收尾会去动 Tk 解释器，而这里只是要立刻放手。
        sys.stdout.flush()
        time.sleep(1.5)
        os._exit(0)
    if not acquire_single_instance():
        warn_duplicate_instance()
        return 0
    sync_autostart_path()
    # 这两个是**快**的：本地健康探测与读配置。它们决定图标首帧和 setup() 里的
    # 「ReMe 启动后启动隧道」判断，所以留在同步路径上。
    refresh_service_state()
    seed_tunnels_wanted()
    # 托盘图标必须先立起来。refresh_tunnels() 已移进 monitor_loop 的第一轮（立即执行）：
    # 它要给每台 VM 起 ssh 并等探测结果，VM 不在线时实测 ≥20 秒。挡在这里的后果是
    # 启动后 20 多秒内**没有任何托盘图标**（详见 monitor_loop 的说明）。
    TRAY_ICON = pystray.Icon(APP_ID, make_icon(STATE["healthy"], any(TUNNEL_STATE.values())),
                             t(APP_NAME), build_menu())
    log(f"tray: icon created (elapsed {time.monotonic() - started:.2f}s)")
    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=menu_refresh_loop, daemon=True).start()
    threading.Thread(target=quit_watch_loop, daemon=True).start()

    def setup(icon):
        icon.visible = True
        # 这一行是「托盘图标真的注册进外壳了」的证据。启动路径上任何一处变慢，
        # 都能从它与上一行的时间差看出来（详见 monitor_loop 的说明）。
        log(f"tray: icon shown (elapsed {time.monotonic() - started:.2f}s)")
        if CFG.get("start_on_launch") and not service_is_healthy():
            run_action(start_service)

    install_tray_trace()
    TRAY_ICON.run(setup=setup)
    # 正常情况走不到这里（run() 一直循环到退出）。真出现了，说明消息循环已经结束、
    # 进程却还活着 —— 那就是「图标还在、点什么都没反应」的另一种成因。
    log("tray: message loop ended")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        logging.exception("fatal application error")
        exit_code = 1
    # Flush by hand, and do it before os._exit for a reason that is easy to miss:
    # os._exit skips the interpreter's normal finalization, so it does not flush
    # stdio. When stdout is a console that hardly matters - the buffer is line
    # buffered and already empty. When stdout is a *pipe* - which is what CI and
    # every build script give it - Python block-buffers and the whole thing dies
    # with the process. That silently swallowed the diagnostics of --smoke,
    # --release and --make-icon exactly where they were needed most.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - flushing must never change the exit code
        pass
    # The settings and guide windows own Tk interpreters created on their own threads.
    # CPython's normal finalization would delete them from the main thread and abort with
    # "Tcl_AsyncDelete: async handler deleted by the wrong thread", so exit directly:
    # everything that must be persisted is already written before this point.
    os._exit(exit_code)