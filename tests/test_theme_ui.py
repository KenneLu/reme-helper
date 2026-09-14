"""主题一致性测试：切主题不能位移、不能有看不清的文字、勾选框含义要一致。

三条都对应真实故障：
  * 浅色用 vista、深色用 clam → 控件高度不同（27px vs 33px），切一次主题整页位移；
  * restyle_widgets 只改背景不改前景 → 深色切浅色后 Label 变成近白字浅底，看不清；
  * clam 把「选中」画成 ✗、未选画成实心块，勾选框含义正好反了。
"""
import os
import sys
import time
import traceback
from pathlib import Path

from conftest import TOOL  # noqa: E402  (puts src/ on sys.path)
import main  # noqa: E402

LOG = TOOL / "log" / "tests" / "theme-test.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, bool, str]] = []
finished = {"done": False}
ORIGINAL = {"lang": str(main.CFG.get("ui_lang") or "zh"), "theme": str(main.CFG.get("theme") or "light")}

for _name in ("showwarning", "showerror", "showinfo"):
    setattr(main.messagebox, _name, lambda *a, **k: True)
main.messagebox.askyesno = lambda *a, **k: False
main.save_config = lambda *a, **k: None
main.read_env_values = lambda: {}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), str(detail)))


def luminance(color: str) -> float | None:
    value = str(color).strip()
    if not value.startswith("#") or len(value) != 7:
        return None
    try:
        parts = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    except ValueError:
        return None
    channels = [(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4) for c in parts]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(fg: str, bg: str) -> float | None:
    a, b = luminance(fg), luminance(bg)
    if a is None or b is None:
        return None
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


def invisible(widgets: list[dict]) -> list[str]:
    """前景与背景几乎一样 → 内容看不清（对比度 < 2:1）。"""
    bad = []
    for item in widgets:
        if not item["text"] or not item["fg"] or not item["bg"]:
            continue
        ratio = contrast(item["fg"], item["bg"])
        if ratio is not None and ratio < 2.0:
            bad.append(f"{item['class']} {item['text'][:24]} fg={item['fg']} bg={item['bg']} ({ratio:.2f})")
    return bad


def geometry(widgets: list[dict]) -> dict:
    """按 (类, 文字) 归并的几何，用来比较两套主题是否位移。

    用「窗口内相对坐标」：窗口每次重建时在屏幕上的位置会变（重开时 Windows 会层叠
    偏移二十几像素），用绝对坐标会整片假失败。原点必须取 Toplevel 自己的位置——
    以前取所有控件的 min()，会被某个未映射控件的 (0,0) 吃掉，等于根本没归一化。
    """
    # 只比较控制台本身。Tooltip、下拉弹层与隐藏 Tk 宿主也都是顶层窗口；它们由 UI
    # 线程异步创建/销毁，曾让同一份布局在 3 次运行中出现 1 次额外 Toplevel。它们不属于
    # 控制台布局，纳入数量或几何只会把调度时机测成产品回归。
    widgets = [item for item in widgets
               if item.get("console_root") or item["class"] not in ("Toplevel", "Tk")]
    if not widgets:
        return {}
    # 隐藏控件（例如「自定义允许列表」收起时的整块内容）没有布局可言，Tk 给它们的位置
    # 在两次构建之间并不一致，会把「有没有位移」变成噪声。颜色检查照旧看全部控件。
    widgets = [item for item in widgets if item.get("mapped", True)]
    if not widgets:
        return {}
    tops = [item for item in widgets if item["class"] == "Toplevel"]
    if tops:
        origin_x = min(item["x"] for item in tops)
        origin_y = min(item["y"] for item in tops)
    else:
        origin_x = min(item["x"] for item in widgets)
        origin_y = min(item["y"] for item in widgets)
    out = {}
    for item in widgets:
        key = (item["class"], item["text"])
        out.setdefault(key, []).append((item["x"] - origin_x, item["y"] - origin_y,
                                        item["w"], item["h"]))
    return {key: sorted(value) for key, value in out.items()}


def settled_count(timeout: float = 10.0, stable_rounds: int = 3) -> int:
    """控件数量的稳定值：连续几轮采样一致才采纳。

    和几何一样，数量也会在中途抖动：服务探测、依赖提示、滚动条映射状态都会在开窗后的
    头几秒里让控件短暂出现/消失。整轮构建（跑完 7 个测试脚本后紧接着跑这个）时更容易
    撞上，实测出现过同一次运行里 446 -> 444 的假失败。比较「稳定后的数量」才是这个断言
    想验证的东西：切主题不应该重建或丢掉控件。
    """
    deadline = time.time() + timeout
    previous = None
    same = 0
    while time.time() < deadline:
        current = len([item for item in main.console_widgets(include_aux=False)
                       if item.get("console_root") or item["class"] not in ("Toplevel", "Tk")])
        if current == previous:
            same += 1
            if same >= stable_rounds:
                return current
        else:
            same = 0
        previous = current
        time.sleep(0.1)
    return previous or 0


def settled_geometry(timeout: float = 10.0, stable_rounds: int = 2):
    """等布局不再变化之后才取几何快照。

    开窗后画布与滚动条还要自我调整几轮（内容越多轮数越多），1 秒时的快照仍处在
    中间态：实测不切主题、只等 2 秒，就有 177 项「位移」，宽度从 839 变到 896。
    拿中间态当基线，「切主题是否位移」比的就成了「中间态 vs 稳定态」，必然假失败。
    """
    deadline = time.time() + timeout
    previous = None
    same = 0
    while time.time() < deadline:
        current = geometry(main.console_widgets(include_aux=False))
        if current == previous:
            same += 1
            if same >= stable_rounds:
                return current
        else:
            same = 0
        previous = current
        time.sleep(0.4)
    return previous or {}


def main_run() -> int:
    main.enable_dpi_awareness()
    main.CFG["ui_lang"] = "zh"
    main.CFG["theme"] = "light"
    main.show_settings()
    deadline = time.time() + 25
    while time.time() < deadline and main.UI_HOST.get("win") is None:
        time.sleep(0.05)
    if main.UI_HOST.get("win") is None:
        check("控制台能打开", False)
        finished["done"] = True
    time.sleep(1.0)

    try:
        # 禁用态文字太暗会「发虚」（浅底/深底都糊）：两套调色板都要求 4:1 以上
        for palette_name, palette in main.PALETTES.items():
            ratio = contrast(palette["disabled"], palette["bg"])
            check(f"{palette_name}：禁用态文字对比度 ≥ 6:1（太低就发虚）",
                  ratio is not None and ratio >= 6.0,
                  f"{palette['disabled']} on {palette['bg']} = {ratio:.2f}")
            ratio_muted = contrast(palette["muted"], palette["bg"])
            check(f"{palette_name}：次要文字对比度 ≥ 4:1",
                  ratio_muted is not None and ratio_muted >= 4.0,
                  f"{palette['muted']} on {palette['bg']} = {ratio_muted:.2f}")

        light = main.console_widgets(include_aux=False)
        light_geom = settled_geometry()
        light_count = settled_count()
        engine_light = main.ui_call(lambda: main.ttk.Style().theme_use())
        fonts_light = main.ui_call(lambda: {
            name: str(main.ttk.Style().lookup(name, "font"))
            for name in ("TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox", "Treeview")
        })
        bad_light = invisible(light)
        check("浅色：没有看不清的文字", not bad_light, "; ".join(bad_light[:4]))
        check("浅色：用的是统一引擎", engine_light == main.TTK_ENGINE, engine_light)
        # 注意措辞：这不是「防中文回退」——这台机器上 Tk 默认字体本来就是 Microsoft YaHei UI，
        # 显式指定的意义是让交互控件跟界面里的 FONT_UI 标签同字号（10pt），不做 9pt 混排。
        check("浅色：交互控件字体显式对齐 FONT_UI（微软雅黑 UI 10pt）",
              all("Microsoft YaHei UI" in value for value in fonts_light.values()), str(fonts_light))

        # 真实路径切到深色（托盘线程 → PENDING_THEME → 窗口自己落地）
        import threading
        threading.Thread(target=main.toggle_theme, daemon=True).start()
        time.sleep(2.5)

        dark = main.console_widgets(include_aux=False)
        dark_geom = settled_geometry()
        dark_count = settled_count()
        engine_dark = main.ui_call(lambda: main.ttk.Style().theme_use())
        fonts_dark = main.ui_call(lambda: {
            name: str(main.ttk.Style().lookup(name, "font"))
            for name in ("TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox", "Treeview")
        })
        bad_dark = invisible(dark)
        check("深色：没有看不清的文字", not bad_dark, "; ".join(bad_dark[:4]))
        check("深色：用的是同一个引擎（不会整页位移）", engine_dark == engine_light,
              f"{engine_light} -> {engine_dark}")
        check("深色：交互控件字体与浅色完全一致（不是 Tk 默认的 9pt）",
              fonts_dark == fonts_light and all("Microsoft YaHei UI" in value for value in fonts_dark.values()),
              f"light={fonts_light} dark={fonts_dark}")
        check("切主题后控件数量不变", dark_count == light_count,
              f"{light_count} -> {dark_count}")

        moved = []
        for key, boxes in light_geom.items():
            if key not in dark_geom:
                continue      # 文字本身变了（例如主题按钮「深色/浅色」）→ 不参与比较
            if dark_geom[key] != boxes:
                moved.append(f"{key[0]} {key[1][:22]}: {boxes} -> {dark_geom[key]}")
        check("切主题后布局不位移", not moved, "; ".join(moved[:4]))

        colored = {item["class"]: (item["fg"], item["bg"]) for item in dark if item["fg"] and item["bg"]}
        check("深色：控件颜色确实变了",
              any(main.PALETTES["light"].get("text") != item["fg"] for item in dark if item["fg"]),
              str(colored)[:120])

        # 控制台说明：代码块/引用的颜色必须跟着主题（以前写死浅色，深色下看不清）
        if True:      # 说明文档现在是内置的，任何环境都有
            main.show_doc_viewer()
            time.sleep(1.5)

            def doc_tags():
                for win in main.AUX_WINDOWS:
                    stack = [win]
                    while stack:
                        widget = stack.pop()
                        try:
                            if widget.winfo_class() == "Text" and "code" in widget.tag_names():
                                return (str(widget.tag_cget("code", "background")),
                                        str(widget.tag_cget("quote", "foreground")))
                            stack.extend(widget.winfo_children())
                        except Exception:  # noqa: BLE001
                            pass
                return None

            tags = main.ui_call(doc_tags)
            check("说明文档的代码块用主题色",
                  tags is not None and tags[0].lower() == main.THEME["code_bg"].lower(), str(tags))
            check("说明文档的引用用次要文字色",
                  tags is not None and tags[1].lower() == main.THEME["muted"].lower(), str(tags))
            for win in list(main.AUX_WINDOWS):
                try:
                    if win.winfo_exists():
                        main.ui_call(win.destroy)
                except Exception:  # noqa: BLE001
                    pass

        # 控制台关掉后从托盘切主题：没有窗口消费 PENDING_THEME，新窗口也必须用新样式
        main.close_settings_window()
        time.sleep(1.0)
        import threading as _threading
        main.CFG["theme"] = "light"
        main.ui_call(main.apply_theme)          # 固定起点：浅色 + 样式已铺好
        check("起点固定为浅色", main.THEME["bg"].lower() == "#f4f5f7", main.THEME["bg"])
        _threading.Thread(target=main.toggle_theme, daemon=True).start()   # 托盘路径 → 深色
        time.sleep(1.5)
        check("托盘切深色后 THEME 已更新（没有窗口也一样）",
              main.THEME["bg"].lower() == "#1b1f27", main.THEME["bg"])
        main.show_path_guide()
        time.sleep(1.5)
        style_bg, theme_bg = main.ui_call(
            lambda: (main.ttk.Style().lookup("TFrame", "background"), main.THEME["bg"]))
        check("没开控制台时切主题，指引窗口也用新主题",
              str(style_bg).lower() == str(theme_bg).lower() == "#1b1f27",
              f"style={style_bg} theme={theme_bg}")
        guide_bgs = {item["bg"].lower() for item in main.console_widgets() if item["bg"]}
        check("指引窗口里的控件背景跟着主题",
              "#1b1f27" in guide_bgs and "#f4f5f7" not in guide_bgs, str(guide_bgs))
        _threading.Thread(target=main.toggle_theme, daemon=True).start()
        time.sleep(1.2)
        main.show_settings()
        deadline2 = time.time() + 20
        while time.time() < deadline2 and main.UI_HOST.get("win") is None:
            time.sleep(0.05)
        time.sleep(1.0)

        # 切回浅色，确认回来以后仍然可读（旧实现在这里把 Label 刷成白字）
        threading.Thread(target=main.toggle_theme, daemon=True).start()
        time.sleep(2.5)
        back = main.console_widgets(include_aux=False)
        bad_back = invisible(back)
        check("切回浅色：依然看得清", not bad_back, "; ".join(bad_back[:4]))
        back_geom = settled_geometry()
        back_count = settled_count()
        moved_back = [f"{key[0]} {key[1][:22]}" for key, boxes in light_geom.items()
                      if key in back_geom and back_geom[key] != boxes]
        check("切回浅色：布局与最初一致", not moved_back and back_count == light_count,
              "; ".join(moved_back[:4]) or f"{light_count} -> {back_count}")
    except Exception:  # noqa: BLE001 - 记录而不是挂住
        check("主题测试未崩溃", False, traceback.format_exc(limit=4))
    finally:
        main.CFG["ui_lang"] = ORIGINAL["lang"]
        main.CFG["theme"] = ORIGINAL["theme"]
        finished["done"] = True

    failed = [(name, detail) for name, ok, detail in results if not ok]
    LOG.write_text("theme test: " + ("PASS" if not failed else f"FAIL ({len(failed)})") + "\n"
                   + "\n".join(f"{'ok  ' if ok else 'FAIL'} {name} {detail}"
                               for name, ok, detail in results) + "\n", encoding="utf-8")
    total, bad = len(results), len(failed)
    print(f"theme test: {total - bad}/{total} checks passed")
    return 0 if (total and not bad) else 1


if __name__ == "__main__":
    code = main_run()
    main.close_settings_window()
    time.sleep(0.2)
    os._exit(code)
