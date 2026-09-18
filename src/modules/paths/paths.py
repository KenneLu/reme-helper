# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/modules/paths/paths.py | TEMPLATE-VER: 1.1.1
# TEMPLATE-LOCAL-OVERRIDE: dev 态 RUN_DIR = 仓库根（诊断输出/图标/文档跟"这次跑的那个包"走，
#   构建脚本按 RELEASE_DIR 下的 log 读取清理——与模板"dev 态 APP_DIR"语义不同，reme 特有）；
#   DIAG_LOG_DIR/RUN_LOG_DIR/图标帧表为 reme 增补。
"""T2｜路径与数据区（reme-helper 形态：四区注释随实现走）。"""
import os
import sys
from pathlib import Path

from modules.appconfig import APP_ID

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
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
    PACKAGE_DIR = APP_DIR
else:
    # dev 态以 main.py 所在的 src/ 为锚（本文件住在 src/modules/paths/，深两级）：
    # parents[2] = src/，再上一级 = 仓库根（诊断输出/图标/文档跟"这次跑的那个包"走）
    APP_DIR = Path(__file__).resolve().parents[2]
    PACKAGE_DIR = APP_DIR.parent
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
# The tray image is stateful and rendered by pystray. Windows taskbar/titlebar icons have a
# different job and much less room, so use a second asset whose small frames fill more pixels.
TASKBAR_ICON_PATH = RUN_DIR / f"{APP_ID}-taskbar.ico"
# 帧尺寸按「外壳真实索要的像素」铺开：100%/125%/150%/175%/200% 缩放下的标题栏 16/20/24/
# 28/32、任务栏 24/30/36/42/48、Alt-Tab 32/40/48/56/64。少一档，LoadImage 就会拿邻近
# 尺寸缩放，缩过的边缘在深色任务栏上看着就是「糊」。
TASKBAR_ICON_SIZES = (16, 20, 24, 28, 30, 32, 36, 40, 42, 48, 56, 64, 96, 128, 256)
# pystray 把 PIL 图写成单帧 .ico 后交给 LoadImage(LR_DEFAULTSIZE)，外壳固定取 32×32；
# 所以托盘图按 32×DPI 渲染，避免 64→32→16 的两次重采样。
TRAY_HICON_PIXELS = 32
