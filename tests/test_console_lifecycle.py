"""控制台生命周期回归：反复切换语言/主题、关掉再打开，窗口都必须还能开出来。

旧实现每次开窗都新建一个 Tk 解释器，跨线程的隐式默认根窗口会让新解释器抛
“main thread is not in main loop”，窗口建到一半就死掉——表现就是「点控制台没反应」。
这个测试专门盯这条路径。
"""
import os
import sys
import threading
import time
from pathlib import Path

from conftest import TOOL  # noqa: E402  (puts src/ on sys.path)
import main  # noqa: E402

LOG = TOOL / "log" / "tests" / "console-lifecycle-test.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, bool, str]] = []
ORIGINAL = {"lang": str(main.CFG.get("ui_lang") or "zh"), "theme": str(main.CFG.get("theme") or "light")}

for _name in ("showwarning", "showerror", "showinfo"):
    setattr(main.messagebox, _name, lambda *a, **k: True)
main.messagebox.askyesno = lambda *a, **k: False
main.save_config = lambda *a, **k: None
main.read_env_values = lambda: {}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), str(detail)))


def wait_window(timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline and main.UI_HOST.get("win") is None:
        time.sleep(0.05)
    return main.UI_HOST.get("win")


def main_run() -> int:
    main.enable_dpi_awareness()
    main.show_settings()
    check("首次打开窗口", wait_window() is not None)
    time.sleep(0.8)

    for index in range(4):
        # 窗口内按钮路径（UI 线程直接重建）
        main.ui_post(lambda index=index: main.set_language("en" if index % 2 == 0 else "zh"))
        time.sleep(1.6)
        # 托盘路径（其它线程 → PENDING_LANG → 窗口自己重建）
        threading.Thread(target=lambda index=index: main.set_language(
            "zh" if index % 2 == 0 else "en"), daemon=True).start()
        time.sleep(1.2)
        threading.Thread(target=main.toggle_theme, daemon=True).start()
        time.sleep(1.2)
        check(f"第{index + 1}轮切换后窗口仍在", main.UI_HOST.get("win") is not None)
        check(f"第{index + 1}轮切换后语言生效", main.ui_lang() in ("zh", "en"), main.ui_lang())

    main.close_settings_window()
    time.sleep(1.0)
    check("关闭后清空窗口引用", main.UI_HOST.get("win") is None)

    for attempt in range(3):
        main.show_settings()
        check(f"重开 {attempt + 1}", wait_window() is not None)
        time.sleep(0.4)
        main.close_settings_window()
        time.sleep(0.8)

    # 已经开着时再点一次：应当前置窗口，而不是报错或再建一个
    main.show_settings()
    wait_window()
    first = main.UI_HOST.get("win")
    main.show_settings()
    time.sleep(0.5)
    check("重复点击复用同一个窗口", main.UI_HOST.get("win") is first)
    check("UI 线程只有一个", len(main.UI_THREADS) == 1, str(len(main.UI_THREADS)))
    check("全程没有 UI 异常", not main.UI_ERRORS, "; ".join(main.UI_ERRORS[:2]))

    main.CFG["ui_lang"] = ORIGINAL["lang"]
    main.CFG["theme"] = ORIGINAL["theme"]
    failed = [(name, detail) for name, ok, detail in results if not ok]
    LOG.write_text("console lifecycle test: " + ("PASS" if not failed else f"FAIL ({len(failed)})") + "\n"
                   + "\n".join(f"{'ok  ' if ok else 'FAIL'} {name} {detail}"
                               for name, ok, detail in results) + "\n", encoding="utf-8")
    print(f"console lifecycle test: {len(results) - len(failed)}/{len(results)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    code = main_run()
    main.close_settings_window()
    time.sleep(0.2)
    os._exit(code)
