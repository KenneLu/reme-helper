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
"""
from __future__ import annotations

import inspect
import re
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

# ---------- ① 默认超时为 None ----------
sig = inspect.signature(main.ui_call)
param = sig.parameters.get("timeout")
check("ui_call has a timeout parameter", param is not None, sorted(sig.parameters))
if param is not None:
    check("ui_call default timeout is None (no fixed business timeout)",
          param.default is None, repr(param.default))

# ---------- ② 下载对话框走默认（不含 timeout=） ----------
match = re.search(r"ui_call\(lambda:\s*update_ui\.run_download_dialog\((.*?)\)\)",
                  SRC, re.S)
check("download dialog is invoked through ui_call",
      match is not None, "" if match else "ui_call(...run_download_dialog...) not found")
if match is not None:
    check("download dialog ui_call carries NO timeout= (user-paced)",
          "timeout=" not in match.group(1), match.group()[:80])

# ---------- ③ 非用户节拍的调用显式传超时 ----------
check("console_widgets passes an explicit timeout",
      "ui_call(collect, timeout=" in SRC)
check("quit confirm passes an explicit timeout",
      "ui_call(QUIT_CONFIRM, timeout=" in SRC)
native_match = re.search(r"ui_call\(lambda: messagebox\.askyesno\(.*?\), timeout=", SRC, re.S)
check("native confirm fallback passes an explicit timeout",
      native_match is not None, "" if native_match else "pattern not found")

print("UI CALL TIMEOUT TEST " + ("FAILED: " + ", ".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
