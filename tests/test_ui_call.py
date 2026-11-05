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

实现改用 **universal rule**（只钉行为、不钉代码结构）：AST 解析源码，按**调用内容**
识别下载弹窗（含 ``run_download_dialog``），其余调用一律要求**有界**超时。这样
重命名嵌套函数、改用 ``work=`` 关键字写法都不会假红，``**{}`` 解包、显式
``timeout=None``、``functools.partial``/别名也都会被挡（红队复审 B1/B2/B3/N4）。
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


def has_bounded_timeout(call: ast.Call) -> bool:
    """是否传了「有界」的 timeout（值不是显式 ``None``）。

    只看关键字在不在会被 ``timeout=None`` 绕过（红队 N4）——而 ``ui_call`` 里
    ``None`` 就是**无界等待**（``done.wait(None)``），与不写 ``timeout=`` 等价。
    非用户节拍的调用（构建门禁 / quit fail-open）必须传**有界**超时，否则
    UI 线程真死时会重新变成永久挂死（P2 那类事故）。
    """
    for kw in call.keywords:
        if kw.arg != "timeout":
            continue
        value = kw.value
        if isinstance(value, ast.Constant) and value.value is None:
            return False      # 显式 None = 无界，不算有界超时
        return True           # 数字 / 名字 / 表达式 = 有界
    return False


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
    check(f"ui_call at line {call.lineno} passes a bounded explicit timeout",
          has_bounded_timeout(call), call_args_segment(call)[:60])

# ---------- ④ 已知站点集合未变（单独断言，保留 N3 的原始意图）----------
# 注意：``== 5`` 同时拒绝「新增」与「删除」——两者都应触发评审，不是单向保护。
check("ui_call call site count is exactly 5 (no addition/removal without review)",
      len(ui_calls) == 5, len(ui_calls))

print("UI CALL TIMEOUT TEST " + ("FAILED: " + ", ".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
