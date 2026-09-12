"""英文模式全树扫描：把控制台切到英文，逐屏检查还有没有中文残留。

test_i18n.py 只能看见源码里的静态字面量；刷新时才写进控件的动态文案（状态条、
页脚、功能表、VM 表格、整理状态…）只有把窗口真的建出来才能抓到。这个测试因此
在英文模式下打开控制台，点一遍主要状态，扫描整棵控件树的文字。
"""
import sys
import time
import traceback
from pathlib import Path

from conftest import TOOL  # noqa: E402  (puts src/ on sys.path)
import main  # noqa: E402

LOG = TOOL / "log" / "tests" / "en-mode-test.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, bool, str]] = []
finished = {"done": False}
ORIGINAL_LANG = str(main.CFG.get("ui_lang") or "zh")


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), str(detail)))


def install_patches() -> None:
    for name in ("showwarning", "showerror", "showinfo"):
        setattr(main.messagebox, name, lambda *a, **k: True)
    main.messagebox.askyesno = lambda *a, **k: False
    main.save_config = lambda *a, **k: None
    main.read_env_values = lambda: {}


def offenders() -> list[str]:
    """当前控制台里所有含中文的控件文字。"""
    bad = []
    for cls, text in main.console_texts():
        if not text or text in main.i18n.ALLOW_CJK_IN_EN:
            continue      # 语言按钮在英文模式下就该显示「中文」
        if main.i18n.HAN.search(text) or main.i18n.FULLWIDTH.search(text):
            bad.append(f"{cls}: {text[:60]}")
    return bad


def build_steps(api):
    steps = []

    def step(name):
        def decorate(fn):
            steps.append((name, fn))
            return fn
        return decorate

    @step("初始画面（英文）")
    def _initial():
        pass

    @step("切到全功能模式")
    def _full():
        api["set_mode"]("full")

    @step("切到自定义模式并改一项")
    def _custom():
        api["set_mode"]("custom")
        api["edit"]("llm", "max_tokens", 8192)

    @step("整理期间与整理结束")
    def _dream():
        api["begin_dream"]()
        api["finish_dream"](True, "done in 12s (test)")

    @step("刷新整理记录")
    def _dream_log():
        api["refresh_dream_history"]()
        api["dream_history"]()          # 读一次文本，触发刷新

    @step("回到基线")
    def _baseline():
        api["reset_section"]("llm")
        api["apply_saved_state"]()

    @step("深色模式")
    def _dark():
        api["toggle_theme"]()

    @step("切回浅色")
    def _light():
        if api["theme"]() == "dark":
            api["toggle_theme"]()

    @step("VM 目标：空表提示")
    def _vm():
        api["set_root"](str(main.CFG.get("reme_root") or ""))

    @step("路径与入口指引窗口")
    def _guide():
        main.show_path_guide()
        time.sleep(0.8)

    @step("内置的控制台说明")
    def _doc():
        main.show_doc_viewer()
        time.sleep(1.2)

    return steps


def main_run() -> int:
    install_patches()
    main.enable_dpi_awareness()
    main.CFG["ui_lang"] = "en"          # 窗口会用当前语言构建

    def harness(api):
        steps = build_steps(api)

        def runner(index=0):
            if index >= len(steps):
                check("英文模式下控制台无中文残留", not state["bad"], "; ".join(state["bad"][:6]))
                check("英文模式下状态条为英文",
                      "Full" in str(api["ui_state"]()["chips"]["模式"])
                      or "Custom" in str(api["ui_state"]()["chips"]["模式"]),
                      str(api["ui_state"]()["chips"]))
                check("全程没有 UI 异常", not main.UI_ERRORS, str(main.UI_ERRORS[:2]))
                check("英文模式下窗口仍存活", bool(api["window_alive"]()))
                finished["done"] = True
                api["root"].after(150, api["close"])
                return
            name, fn = steps[index]
            try:
                fn()
                api["root"].update_idletasks()
                time.sleep(0.05)
                found = offenders()
                if found:
                    state["bad"].extend(f"{name} → {item}" for item in found)
                check(f"步骤「{name}」无中文", not found, "; ".join(found[:4]))
            except Exception:  # noqa: BLE001 - 记录而不是挂住窗口
                check(f"步骤「{name}」未崩溃", False, traceback.format_exc(limit=3))
            api["root"].after(160, lambda: runner(index + 1))

        api["root"].after(400, runner)

    state = {"bad": []}
    main.show_settings(autoclose_ms=45000, harness=harness)
    deadline = time.time() + 45
    while not finished["done"] and time.time() < deadline:
        time.sleep(0.3)

    # 托盘菜单文案也要是英文（菜单项文案是 callable，展开菜单时才求值）
    try:
        menu = main.build_menu()
        texts = [str(item.text) for item in menu.items]
        chinese = [text for text in texts
                   if text and text not in main.i18n.ALLOW_CJK_IN_EN and main.i18n.HAN.search(text)]
        check("托盘右键菜单为英文", not chinese, "; ".join(chinese[:5]))
    except Exception:  # noqa: BLE001
        check("托盘右键菜单为英文", False, traceback.format_exc(limit=2))
    finally:
        main.CFG["ui_lang"] = ORIGINAL_LANG

    failed = [(name, detail) for name, ok, detail in results if not ok]
    LOG.write_text("en mode test: " + ("PASS" if not failed else f"FAIL ({len(failed)})") + "\n"
                   + "\n".join(f"{'ok  ' if ok else 'FAIL'} {name} {detail}"
                               for name, ok, detail in results) + "\n", encoding="utf-8")
    total, bad = len(results), len(failed)
    print(f"en mode test: {total - bad}/{total} checks passed")
    return 0 if (total and not bad) else 1


if __name__ == "__main__":
    code = main_run()
    main.close_settings_window()
    time.sleep(0.2)
    import os

    os._exit(code)
