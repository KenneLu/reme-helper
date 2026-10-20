# -*- coding: utf-8 -*-
"""重复启动优雅化（1.2.14）：第二实例只写 show.request，常驻实例打开/前置设置页。

- 第二实例不弹任何模态框：写请求文件后静默 return 0；
- 常驻实例 consume_show_request() 消费请求 → show_settings()；窗口不可用时退化为托盘气泡
  「ReMe 助手已在运行」。
全部用 mock：不启 GUI、不依赖真实 AppData。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402

# CI runner 的 Windows UI 语言是英文：本测试断言中文气泡文案，先把界面语言钉成 zh。
# 产品自身的 en/zh 本地化正确性由 test_i18n / test_en_mode 覆盖。
main.i18n.init("zh")

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


saved_show_path = main.SHOW_REQUEST_PATH
saved_show_settings = main.show_settings
saved_tray_icon = main.TRAY_ICON
saved_warn = main.warn_duplicate_instance
saved_ui_host = dict(main.UI_HOST)

try:
    # ---------------- ① 第二实例：写 show.request + 静默退出 + 不弹模态框 ----------------
    modal_calls = []
    main.warn_duplicate_instance = lambda: modal_calls.append("modal")
    with tempfile.TemporaryDirectory(prefix="reme-helper-show-") as temp:
        main.SHOW_REQUEST_PATH = Path(temp) / "data" / "show.request"
        rc = main.request_show_existing()
        check("second instance exits with 0", rc == 0, rc)
        check("second instance writes show.request", main.SHOW_REQUEST_PATH.is_file(),
              main.SHOW_REQUEST_PATH)
        check("second instance never shows a modal dialog", not modal_calls, modal_calls)

        # ---------------- ② 常驻侧消费：删文件 + 打开设置页 ----------------
        shown = []
        main.show_settings = lambda *args, **kwargs: shown.append(True)
        main.UI_HOST.clear()
        main.UI_HOST["root"] = type("FakeRoot", (), {"winfo_exists": lambda self: True})()
        consumed = main.consume_show_request()
        check("resident consumes show.request", consumed is True)
        check("show.request is deleted after consumption", not main.SHOW_REQUEST_PATH.exists())
        check("resident opens the settings window", shown == [True], shown)
        check("consume returns False when there is no request", main.consume_show_request() is False)

        # ---------------- ③ 设置窗口不可用 → 托盘气泡兜底 ----------------
        class _FakeTray:
            def __init__(self):
                self.notes = []

            def notify(self, message, title=None):
                self.notes.append((message, title))

        fake_tray = _FakeTray()
        main.TRAY_ICON = fake_tray
        main.UI_HOST.clear()   # 没有可用的 Tk 根窗口

        def _boom(*_args, **_kwargs):
            raise RuntimeError("no tk interpreter")

        main.show_settings = _boom
        main.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
        consumed = main.consume_show_request()
        check("fallback still consumes the request", consumed is True)
        check("fallback shows the 'already running' balloon",
              bool(fake_tray.notes) and "已在运行" in fake_tray.notes[0][0], fake_tray.notes)

        # ---------------- ④ 请求文件读失败不抛 ----------------
        main.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
        main.UI_HOST.clear()
        main.TRAY_ICON = None
        try:
            main.consume_show_request()
            check("consuming without any UI/tray does not raise", True)
        except Exception as exc:  # noqa: BLE001
            check("consuming without any UI/tray does not raise", False, repr(exc))
finally:
    main.SHOW_REQUEST_PATH = saved_show_path
    main.show_settings = saved_show_settings
    main.TRAY_ICON = saved_tray_icon
    main.warn_duplicate_instance = saved_warn
    main.UI_HOST.clear()
    main.UI_HOST.update(saved_ui_host)

print("SINGLE INSTANCE TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
