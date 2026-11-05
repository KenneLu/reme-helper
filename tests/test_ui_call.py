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

# ---------- 收集全部 ui_call 调用 ----------
ui_calls = [n for n in ast.walk(TREE)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ui_call"]

# ---------- ② 下载弹窗：无超时（任何形式都算超时）----------
# universal rule：只钉行为，不钉代码结构（函数名/参数写法）。红队 B1/B2/B3：
# 不看函数名 → 重命名嵌套 work() 不假红；len(args) <= 1 → work= 关键字写法不假红；
# 挡 ``**{}`` 解包 → ``ui_call(lambda: ..., **{"timeout": 60.0})`` 不逃逸。
download_calls = [c for c in ui_calls if "run_download_dialog" in call_args_segment(c)]
check("download dialog call site found", len(download_calls) == 1, len(download_calls))
if download_calls:
    dl = download_calls[0]
    check("download dialog has no timeout in any form (user-paced)",
          not has_timeout_kw(dl)
          and not any(kw.arg is None for kw in dl.keywords)
          and len(dl.args) <= 1,
          call_args_segment(dl)[:80])

# ---------- ③ 其他所有 ui_call 必须显式传超时（用户节拍只有下载弹窗）----------
for call in ui_calls:
    if download_calls and call is download_calls[0]:
        continue
    check(f"ui_call at line {call.lineno} passes an explicit timeout=",
          has_timeout_kw(call), call_args_segment(call)[:60])

# ---------- ④ 已知站点未被删除（单独断言，保留 N3 的原始意图）----------
check("ui_call call site count is exactly 5 (no known site removed)",
      len(ui_calls) == 5, len(ui_calls))

print("UI CALL TIMEOUT TEST " + ("FAILED: " + ", ".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
