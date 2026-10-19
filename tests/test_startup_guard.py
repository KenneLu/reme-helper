# -*- coding: utf-8 -*-
"""启动守卫回归：托盘创建失败可重试、可读错误兜底、traceback 模块级可用。

背景：受限终端/沙箱/远程会话里 pystray 创建托盘窗口会抛 PermissionError；
旧版顶层 except 还引用了未导入的 traceback → NameError 把真实错误吞掉。
本测试离线运行：不建真实托盘窗口、不启 GUI/服务、不依赖 AppData。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


# ---------------- ① traceback 模块级可用（上一版顶层 except 的 NameError 回归） ----------------
check("module-level traceback is available", getattr(main, "traceback", None) is not None)
try:
    _text = main.traceback.format_exc()
    check("traceback.format_exc works at module level", isinstance(_text, str))
except Exception as exc:  # noqa: BLE001
    check("traceback.format_exc works at module level", False, repr(exc))


# ---------------- ② 托盘 run 抛 PermissionError → 重试 + 可读错误 ----------------
class _FailingIcon:
    def run(self, setup=None):
        raise PermissionError(5, "拒绝访问", "CreateWindowExW")


stats = {"created": 0, "slept": []}


def _make_failing_icon():
    stats["created"] += 1
    return _FailingIcon()


saved_sleep, saved_log = main.time.sleep, main.log
main.time.sleep = lambda seconds: stats["slept"].append(seconds)
main.log = lambda *parts: None
try:
    raised = None
    try:
        main._run_tray_with_retry(_make_failing_icon, setup=None)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    check("retries three times with a fresh icon each attempt", stats["created"] == 3, stats["created"])
    check("backoff is 1s then 2s", stats["slept"] == [1.0, 2.0], stats["slept"])
    check("final failure is a readable TrayStartupError", isinstance(raised, main.TrayStartupError), repr(raised))
finally:
    main.time.sleep, main.log = saved_sleep, saved_log

failure_detail = "Traceback (most recent call last):\n  ...\nPermissionError: [WinError 5] 拒绝访问"
text = main._startup_failure_text(main.TrayStartupError(PermissionError(5, "denied")), failure_detail)
check("tray failure text names the restricted-launch causes",
      "受限终端" in text and "文件资源管理器" in text, text)
check("tray failure text keeps the traceback tail for diagnosis", "PermissionError" in text, text)

saved_log_init = main.LOG_INIT_ERROR
main.LOG_INIT_ERROR = PermissionError("log dir denied")
try:
    logged_fallback_text = main._startup_failure_text(main.TrayStartupError(PermissionError(5)), failure_detail)
    check("text adds the log-directory note when logging also failed",
          "日志目录也不可写" in logged_fallback_text, logged_fallback_text)
finally:
    main.LOG_INIT_ERROR = saved_log_init

# 正常启动（没有 LOG_INIT_ERROR）时不应出现日志目录那句
plain_text = main._startup_failure_text(main.TrayStartupError(PermissionError(5)), failure_detail)
check("normal case has no log-directory note", "日志目录也不可写" not in plain_text, plain_text)


# ---------------- ③ MessageBoxW 兜底：失败也不能抛 ----------------
class _FakeUser32:
    def __init__(self, sink):
        self.sink = sink

    def MessageBoxW(self, hwnd, text, title, flags):
        self.sink.append((text, title, flags))
        return 1


class _FakeWindll:
    def __init__(self, sink):
        self.user32 = _FakeUser32(sink)


class _FakeCtypes:
    def __init__(self, sink):
        self.windll = _FakeWindll(sink)


shown_boxes = []
saved_ctypes = main.ctypes
main.ctypes = _FakeCtypes(shown_boxes)
try:
    ok = main._message_box("hello box", "title")
    check("MessageBoxW is invoked through the guard", ok is True and shown_boxes and shown_boxes[0][0] == "hello box",
          shown_boxes)
finally:
    main.ctypes = saved_ctypes


class _BrokenCtypes:
    @property
    def windll(self):
        raise RuntimeError("no user32 here")


main.ctypes = _BrokenCtypes()
try:
    check("MessageBoxW failure returns False without raising", main._message_box("x") is False)
finally:
    main.ctypes = saved_ctypes


# ---------------- ④ 崩溃日志 best-effort 多落点 ----------------
with tempfile.TemporaryDirectory(prefix="reme-helper-startup-") as temp:
    root = Path(temp)
    saved_dirs = (main.LOG_DIR, main.DIAG_LOG_DIR)
    try:
        main.LOG_DIR = root / "appdata" / "log"
        main.DIAG_LOG_DIR = root / "diag"
        first = main._write_startup_failure_log("boom-1")
        check("crash log written to the first available path",
              first is not None and "boom-1" in Path(first).read_text(encoding="utf-8"), first)

        blocker = root / "blocker"
        blocker.write_text("x", encoding="utf-8")
        main.LOG_DIR = blocker / "log"   # 父路径是文件 → 第一个落点必失败
        fallback = main._write_startup_failure_log("boom-2")
        check("crash log falls back when the first path is unusable",
              fallback is not None and "boom-2" in Path(fallback).read_text(encoding="utf-8"), fallback)

        main.DIAG_LOG_DIR = blocker / "diag"
        saved_tempdir = main.tempfile.gettempdir
        main.tempfile.gettempdir = lambda: str(blocker)
        try:
            none_path = main._write_startup_failure_log("boom-3")
        finally:
            main.tempfile.gettempdir = saved_tempdir
        check("all log paths blocked -> None, no raise", none_path is None, none_path)
    finally:
        main.LOG_DIR, main.DIAG_LOG_DIR = saved_dirs


# ---------------- ⑤ 启动失败展示：不抛 + 可读入口不弹窗 ----------------
saved_message_box = main._message_box
saved_write_log = main._write_startup_failure_log
saved_argv = list(sys.argv)
boxes = []
main._message_box = lambda text, title="ReMe 助手 启动失败": boxes.append(text) or True
main._write_startup_failure_log = lambda text: None
try:
    sys.argv = ["reme-helper"]
    main._show_startup_failure(main.TrayStartupError(PermissionError(5)), failure_detail)
    check("show-startup-failure never raises and routes to the messagebox",
          bool(boxes) and "无法创建系统托盘图标" in boxes[0], boxes[:1])

    boxes.clear()
    sys.argv = ["reme-helper", "--smoke"]
    main._show_startup_failure(RuntimeError("boom"), "Traceback ...")
    check("headless diagnostics mode does not pop a dialog", not boxes, boxes)
finally:
    sys.argv = saved_argv
    main._message_box = saved_message_box
    main._write_startup_failure_log = saved_write_log

print("STARTUP GUARD TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
