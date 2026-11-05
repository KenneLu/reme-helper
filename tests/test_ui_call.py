# -*- coding: utf-8 -*-
"""ui_call 默认超时的机械判据（2026-11-05 OTA 误报修复的回归保护）。

背景：``update_ui.run_download_dialog`` 是**模态**对话框，返回时机由用户决定
（下载大包 + 用户可能离开）。给它加固定业务超时会把「用户还在操作」误判成
「UI 线程没响应」，让调用方提前退出、对话框成孤儿——用户随后点【立即更新】
无人接收（reme-helper 1.2.22 OTA 实测：17.5MB 下载超过 20s 触发误报）。

本测试钉住三件事：
  ① ``ui_call`` 的默认 ``timeout`` 必须是 ``None``（无限等）——下载弹窗走默认；
  ② 下载对话框的 ``ui_call(...)`` **不含** ``timeout=``（用户节拍，不该被限）；
  ③ 非用户节拍的调用（``console_widgets`` / ``console_texts`` / 退出确认）
     **显式**传了超时，以防 UI 线程真死时门禁/退出 fail-open 永久挂死。

实现用 AST 按函数体切片，避免「同名调用点」互相满足（红队复审 R2），
并用括号配平提取 ``ui_call(...)`` 实参区间，避免非贪婪正则的捕获逃逸（R1）。
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main  # noqa: E402

FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else "  FAIL") + " " + name + (("  " + str(detail)) if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


SRC = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def call_args_segment(call: ast.Call) -> str:
    """调用的完整实参源码（含嵌套括号），用 AST 的 end 位置截取。"""
    return ast.get_source_segment(SRC, call) or ""


def has_timeout_kw(call: ast.Call) -> bool:
    return any(kw.arg == "timeout" for kw in call.keywords)


# ---------- ① 默认超时为 None ----------
sig = inspect.signature(main.ui_call)
param = sig.parameters.get("timeout")
check("ui_call has a timeout parameter", param is not None, sorted(sig.parameters))
if param is not None:
    check("ui_call default timeout is None (no fixed business timeout)",
          param.default is None, repr(param.default))

# ---------- 找到每个调用所属的最近函数定义 ----------
def enclosing_function(node: ast.AST) -> str:
    # ast.walk 不给出父指针，这里用位置区间匹配
    best = ""
    best_span = None
    for fn in ast.walk(TREE):
        if isinstance(fn, ast.FunctionDef):
            span = (fn.lineno, fn.end_lineno or fn.lineno)
            if span[0] <= node.lineno <= span[1]:
                if best_span is None or (span[1] - span[0]) < (best_span[1] - best_span[0]):
                    best = fn.name
                    best_span = span
    return best


# ---------- 收集全部 ui_call 调用，按所在线程/函数分类 ----------
ui_calls = [n for n in ast.walk(TREE)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ui_call"]
# 精确计数 + 白名单：防止新增调用点逃逸（红队 N3），也防止已知站点被删。
# run_helper_update 的 ui_call 位于其内部 ``work()`` 中，故白名单含 "work"。
ALLOWED_ENCLOSING = {"console_widgets", "console_texts", "quit_app", "work"}
check("ui_call call site count is exactly 5", len(ui_calls) == 5, len(ui_calls))
_actual_enclosing = {enclosing_function(c) for c in ui_calls}
check("ui_call call sites are within the known whitelist",
      _actual_enclosing <= ALLOWED_ENCLOSING, sorted(_actual_enclosing))


download_calls = [c for c in ui_calls if "run_download_dialog" in call_args_segment(c)]
check("download dialog call site found", len(download_calls) == 1, len(download_calls))
for call in download_calls:
    # 只接受 ``ui_call(lambda: ...)``：一个位置参数、无 timeout 关键字（红队 N2：
    # 位置超时 ``ui_call(lambda: ..., 60.0)`` 也必须被抓）。
    check("download dialog ui_call carries NO timeout (keyword or positional, user-paced)",
          not has_timeout_kw(call) and len(call.args) == 1, call_args_segment(call)[:80])

# ---------- ③ 非用户节拍的调用显式传超时（按函数体切片，R2） ----------
for fname in ("console_widgets", "console_texts"):
    fn_calls = [c for c in ui_calls if enclosing_function(c) == fname]
    check(f"{fname} has exactly one ui_call", len(fn_calls) == 1, len(fn_calls))
    for call in fn_calls:
        check(f"{fname} ui_call passes explicit timeout=",
              has_timeout_kw(call), call_args_segment(call)[:80])

quit_calls = [c for c in ui_calls if enclosing_function(c) == "quit_app"]
check("quit_app has two ui_call sites (rich + native)", len(quit_calls) == 2, len(quit_calls))
for call in quit_calls:
    check("quit_app ui_call passes explicit timeout=",
          has_timeout_kw(call), call_args_segment(call)[:80])

print("UI CALL TIMEOUT TEST " + ("FAILED: " + ", ".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
