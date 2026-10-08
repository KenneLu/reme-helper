# -*- coding: utf-8 -*-
"""退出路径的失败方向（D3.2；A 项）。

触发条件不是"正常用户点取消"，而是**包被损坏**：Tcl/Tk 运行时不见了，`tkinter.Toplevel`
直接抛异常。此时如果确认链把"弹窗挂了"当成"用户没确认"，用户就被锁死在工具里——只能靠
任务管理器杀进程（这正是用户可见后果）。所以本仓的口径是：

  链路不可用（富对话框 + 原生框**都**失败）→ 记一行日志，**照常退出**（清理按已存配置）；
  用户明确取消（富对话框返回 go=False，或原生框返回"No"）→ **不退出**，一切照旧。

两条都必须钉住：只钉"能退出"会退化成把确认框拆了；只钉"能取消"就是现在的锁死状态。
"""
import sys
import threading as _real_threading
from types import SimpleNamespace

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


class _Boom(RuntimeError):
    pass


def _raise(*_a, **_k):
    raise _Boom("no Tcl interpreter (damaged package)")


class _FakeThread:
    """`quit_app` 把真正的清理丢给后台线程；这里只记录"它被启动了"。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        CALLS["shutdown"] += 1


CALLS = {"shutdown": 0, "notify": [], "log": []}

# ---- 替身：不碰 Tk / 不落盘 / 不起线程 ----
main.save_config = lambda *a, **k: None
main.notify = lambda *a, **k: CALLS["notify"].append(a)
main.log = lambda *a, **k: CALLS["log"].append(" ".join(str(x) for x in a))
main.threading = SimpleNamespace(Thread=_FakeThread)


def _run(rich, native):
    """跑一次 quit_app，返回是否走到了清理（= 退出被放行）。"""
    CALLS["shutdown"] = 0
    CALLS["notify"].clear()
    CALLS["log"].clear()
    main.SHUTDOWN_STARTED.clear()
    main.ui_call = lambda work, timeout=20.0: work()
    main.QUIT_CONFIRM = rich
    main.messagebox.askyesno = native
    main.quit_app(object(), None)
    return CALLS["shutdown"] > 0


# ---------- ① 用户明确取消：一律不退出 ----------
def _rich_cancel():
    return (False, False, False)


def _native_no(*_a, **_k):
    return False


check("rich dialog 'cancel' -> no exit", not _run(_rich_cancel, _native_no))
check("rich dialog raises + native 'No' -> no exit",
      not _run(_raise, _native_no),
      "the native fallback did run and the user said no; must be respected")

# ---------- ② 链路不可用：必须放行退出（否则用户被锁死） ----------
check("rich dialog raises + native raises -> exit anyway (fail open)",
      _run(_raise, _raise), "both dialogs unusable")
check("...and it says so in the log",
      any("proceeding without confirmation" in line for line in CALLS["log"]),
      " | ".join(CALLS["log"]))

# ---------- ③ 正向对照：确认了当然要退出（防止把断言写成恒真/恒假） ----------
def _rich_confirm():
    return (True, False, False)


check("rich dialog 'confirm' -> exit", _run(_rich_confirm, _native_no))

# ---------- ④ 清理选项：**用户没被问过时一律不动服务** ----------
# 旧行为（lead 2026-09-19 **撤回**了原先的批准）：链路不可用时按**已存配置**走。
# 危险面：用户在"有确认框"的语境下勾过"退出时停服务"，而一次坏掉的弹窗会在**没有任何确认**
# 的情况下把服务/隧道停掉——「辅助机制坏掉 ⇒ 触发破坏性动作」，正是本轮一直在打的形态。
# 新行为：**没人问过用户 ⇒ 必须选保住服务的那一侧**（与 dsh/ocx 的 `return True, False` 同形）。
main.CFG["quit_stop_tunnels"] = True
main.CFG["quit_stop_reme"] = True
_run(_raise, _raise)                     # 富框抛 + 原生框也抛 ⇒ 用户从未被问过
check("fail-open forces cleanup OFF (user was never asked)",
      main.CFG.get("quit_stop_tunnels") is False and main.CFG.get("quit_stop_reme") is False,
      "CFG[reme]=%r CFG[tunnels]=%r"
      % (main.CFG.get("quit_stop_reme"), main.CFG.get("quit_stop_tunnels")))

# 正向对照：**原生框问到了**用户（只是没有勾选框）——这一支仍按已存配置走，与 dsh 同形。
# 没有这条对照，上面那条"强制 False"就可能被写成"任何异常都 False"，把**问到过的**用户也一起无视。
main.CFG["quit_stop_tunnels"] = True
main.CFG["quit_stop_reme"] = True
_run(_raise, lambda *_a, **_k: True)     # 富框抛 → 原生框答「是」
check("native confirm (user WAS asked) still honours the persisted choice",
      main.CFG.get("quit_stop_tunnels") is True,
      "CFG[quit_stop_tunnels]=%r" % main.CFG.get("quit_stop_tunnels"))
main.CFG["quit_stop_tunnels"] = False
main.CFG["quit_stop_reme"] = False

# ---------- ⑤ 二次退出：claim_shutdown 只放行一次 ----------
# 前一个用例刚启动过一次清理，所以这里比的是**增量**而不是绝对值。
_run(_rich_confirm, _native_no)
before = CALLS["shutdown"]
main.SHUTDOWN_STARTED.set()
try:
    CALLS["notify"].clear()
    main.quit_app(object(), None)
    check("a second quit request does not start shutdown twice",
          CALLS["shutdown"] == before and not CALLS["notify"],
          "shutdown %s -> %s" % (before, CALLS["shutdown"]))
finally:
    main.SHUTDOWN_STARTED.clear()

print("QUIT FAIL-OPEN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
