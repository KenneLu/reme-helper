# -*- coding: utf-8 -*-
"""C-2 接线：`hold_exe_delete_guard` 必须在**单实例守卫之后、托盘构造之前**被调用。

**为什么用"跑真正的 `main()` 并记录顺序"而不是读源码/读注释**：顺序是**行为**，
注释保证不了它 —— 它随时可以被一次"顺手整理"挪走，而挪走之后**没有任何门禁会红**。
l-s2t 的同类用例用 `ORDER == ['guard','overlay','tray']` 钉住；reme 的托盘入口是
`pystray.Icon(...)`，这里同形，只是把 `overlay` 换成 `tray`。

窗口的三面约束（挪到任意一边都错，docstring 里写死，因为下一个人一定会问）：
  * **不能在无头 CLI 分支之前** —— `--helper-update` 走 `os._exit(0)`，之后要靠更新器
    **整目录替换 exe**；提前持句柄 = 让那次更新自己把自己钉住；
  * **不能在单实例守卫之前** —— 第二个实例会去持第一个实例的 exe 句柄，语义错位；
  * **不能在托盘构造之后** —— 晚了就等于"窗口尚未建立"那段时间没有保护。

本用例**不验证** `hold_exe_delete_guard` 自身的行为（dev 跳过 / 失败放行由模板件与
它的文档保证），只验证**调用点存在且顺序正确**。
"""
import os
import sys
import tempfile
from pathlib import Path

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)

# F11/D12 实例隔离：必须在 import main 之前钉住数据根与配置，否则导入期的
# seed_config() 会写用户真实的 %LOCALAPPDATA%\reme-helper\。
_TMP = tempfile.mkdtemp(prefix="reme-guard-order-")
os.environ["REME_HELPER_DATA_DIR"] = _TMP
os.environ["REME_HELPER_CONFIG"] = str(Path(_TMP) / "config.json")

import main as M  # noqa: E402

FAILS = []
ORDER = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def _mark(tag, value=True):
    ORDER.append(tag)
    return value


class _StopBeforeTray(Exception):
    """托盘构造时抛出：把 main() 从阻塞的 run() 之前带出来。"""


# ---- 替身：只替换"顺序断言"关心的那几个调用点，其余保持真实 ----
M.acquire_single_instance = lambda *a, **k: _mark("instance-guard")
M.warn_duplicate_instance = lambda: None
M.hold_exe_delete_guard = lambda **k: _mark("exe-guard")
M.sync_autostart_path = lambda: None
M.sweep_stale_update_dirs = lambda: None
M.refresh_service_state = lambda: None
M.seed_tunnels_wanted = lambda: None
M.install_tray_identity = lambda: None
M.install_tray_trace = lambda: None


class _FakePystray:
    # build_menu() 会在 Icon(...) 的**实参求值阶段**被调用，所以菜单构造的替身也要在，
    # 否则 `main()` 在到达托盘之前就 AttributeError 退出，顺序断言根本跑不到。
    class Menu:                                  # noqa: N801 - 模拟 pystray.Menu
        SEPARATOR = object()                     # build_menu() 会引用它

        def __init__(self, *a, **k):
            pass

    class MenuItem:                              # noqa: N801
        def __init__(self, *a, **k):
            pass

    class Icon:                                  # noqa: N801 - 模拟 pystray.Icon
        def __init__(self, *a, **k):
            _mark("tray")
            raise _StopBeforeTray()


M.pystray = _FakePystray

_CRASH = None
try:
    M.main()
except _StopBeforeTray:
    pass
except SystemExit:                               # 正常收尾（重复实例等分支 return/exit 表达）不算"崩"。
    pass                                         # SystemExit 是 BaseException 子类 ⇒ 必须排在下面那条之前
except BaseException as exc:                     # noqa: BLE001 - ORDER 三条不依赖退出方式；_CRASH 那条依赖
    _CRASH = exc
    print("  (main() raised %s before reaching the tray - 继续按已记录的顺序判定)"
          % type(exc).__name__, flush=True)

# ⚠️ 与"顺序"**分开**的一条断言（verifier 2026-09-19 复核提出，我采纳）：
# 上面那条 `except BaseException` 只打印、不进 FAILS，于是「`tray` 标记之后抛出的
# 意外异常」会走完打印、FAILS 仍为空、`sys.exit(0)`——**全绿**。窗口很窄（托盘构造
# 那一刻附近），顺序断言本身判别力没坏（删调用 / 挪到 run() 之后都会红）。
# 但"main() 能干净地走到托盘"这件事，本仓**没有别的门禁接住**（全 tests 只有本文件
# 会跑 main()），所以必须在这里单独列一条。
# 为什么**不**并进 ORDER 那条：合并会重犯"一个红代表多种病因"的老账——顺序错
# 与"崩了"是两回事，读报的人需要一眼分清。
# **第三种失败模式（`os._exit`）**：它**不抛异常** ⇒ 本处的 try/except 接不住——进程
# 直接消失、`ORDER` 与 `FAILS` 都停在半路，报出来是**输出截断**而不是红。与
# `except BaseException` 互补：一条管"抛出来的"，一条管"不抛就走的"。今天为潜伏态
# （托盘构造在 `os._exit` 分支之前，打桩能走到），登记以免将来误判为"测试通过"。
check("main() reached the tray without an unexpected exception", _CRASH is None,
      repr(_CRASH) if _CRASH else "")

check("instance guard ran", "instance-guard" in ORDER, str(ORDER))
check("exe delete-guard ran", "exe-guard" in ORDER, str(ORDER))
check("tray was constructed", "tray" in ORDER, str(ORDER))

if all(t in ORDER for t in ("instance-guard", "exe-guard", "tray")):
    i_i, i_e, i_t = (ORDER.index("instance-guard"), ORDER.index("exe-guard"),
                     ORDER.index("tray"))
    check("ORDER == instance-guard -> exe-guard -> tray", i_i < i_e < i_t, str(ORDER))
else:
    check("ORDER == instance-guard -> exe-guard -> tray", False,
          "无法判定（有调用点没跑到）：%s" % ORDER)


def _cleanup(path):
    """删数据根并**回读确认**。

    先 `logging.shutdown()` 再删：`log()` 用的文件 handler 在进程内一直持有日志文件，
    不先关掉，Windows 会拒绝删除**包含该文件的目录**——那时用例会报"泄漏"，
    而真正的泄漏只是本进程自己没放手（不是工具写坏东西）。
    """
    import logging
    import shutil
    import time
    logging.shutdown()
    for attempt in range(10):
        try:
            shutil.rmtree(path)
        except OSError:
            pass
        if not os.path.exists(path):
            return True
        time.sleep(0.2)
    return not os.path.exists(path)


check("temp dir cleaned up (no %TEMP% leak)", _cleanup(_TMP), _TMP)
print("DELETE GUARD WIRED TEST "
      + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
