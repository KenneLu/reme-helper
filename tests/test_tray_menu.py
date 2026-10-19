# -*- coding: utf-8 -*-
"""托盘菜单（1.2.13）：文案空格 + 双粗体（Studio 主默认、设置页同粗）+ 双击落到 Studio。

1) 中文与英文/字母之间留一个空格；
2) 「打开 ReMe Studio」与「ReMe 设置…」都带 default=True（Windows MFS_DEFAULT → 粗体）；
   Windows 的 InsertMenuItem 只接受一个默认项，靠工具侧 patch（先去掉状态位插入，再
   SetMenuItemInfo 补状态位并用 GetMenuItemInfo 复核）立住第二个；patch 失败也只退化为
   单默认项，菜单本身仍可用；
3) 双击托盘图标固定打开 Studio（TrayMenu.__call__ 显式优先 primary 项）。
"""
import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


def menu_items():
    return list(main.build_menu().items)


def menu_texts():
    return [item.text for item in menu_items()]


def default_items():
    return [item for item in menu_items() if item.default]


# ---------------- ① 中英文之间补空格 ----------------
main.i18n_bridge.sync_lang("zh")
joined = "\n".join(menu_texts())

GLUED = (
    "启动ReMe", "停止ReMe", "重启ReMe", "打开ReMe Studio",
    "启动全部ssh 隧道", "停止全部ssh 隧道", "ReMe启动后启动隧道",
    "启动工具时启动ReMe", "ReMe状态：", "ReMe版本：", "ReMe助手版本：",
)
for old in GLUED:
    check("no glued Chinese/Latin text: %s" % old, old not in joined)

SPACED = (
    "启动 ReMe", "停止 ReMe", "重启 ReMe", "打开 ReMe Studio",
    "启动全部 ssh 隧道", "停止全部 ssh 隧道", "ReMe 启动后启动隧道",
    "启动工具时启动 ReMe", "ReMe 设置…",
)
for new in SPACED:
    check("spaced text present: %s" % new, new in joined)

check("status row spaced", "ReMe 状态：" in joined)
check("ReMe version row spaced", "ReMe 版本：" in joined)
check("helper version row spaced", "ReMe 助手版本：" in joined)


# ---------------- ② 两个粗体默认项：设置页 + Studio（Studio 为主默认） ----------------
def check_defaults(lang):
    items = menu_items()
    defaults = [item for item in items if item.default]
    texts = [item.text for item in defaults]
    expected_settings = "ReMe 设置…" if lang == "zh" else "ReMe Settings…"
    expected_studio = "打开 ReMe Studio" if lang == "zh" else "Open ReMe Studio"
    check("%s: exactly two default items" % lang, len(defaults) == 2, texts)
    check("%s: settings item is a default item" % lang, expected_settings in texts, texts)
    check("%s: Studio item is a default item" % lang, expected_studio in texts, texts)
    return items, defaults


items_zh, defaults_zh = check_defaults("zh")

menu = main.build_menu()
check("build_menu returns the tool-side TrayMenu", isinstance(menu, main.TrayMenu), type(menu))
check("double-click primary is the Studio default item",
      menu._primary_item is not None and menu._primary_item.default
      and menu._primary_item.text == "打开 ReMe Studio",
      None if menu._primary_item is None else (menu._primary_item.text, menu._primary_item.default))

# 双击行为：TrayMenu.__call__ 必须选中 primary，而不是 items 顺序里更靠前的设置项
calls = []


def _record(label):
    return lambda _icon, _item: calls.append(label)


fake_other = main.pystray.MenuItem("other", _record("other"), default=True)
fake_primary = main.pystray.MenuItem("primary", _record("primary"), default=True)
probe_menu = main.TrayMenu(fake_other, fake_primary, primary=fake_primary)
probe_menu.__call__(None)
check("double-click resolves to the primary (Studio) item, not the earlier default",
      calls == ["primary"], calls)

# ---------------- ③ 双默认 patch 的机械验证：两个 Win32 菜单项都含 MFS_DEFAULT ----------------
check("double-default workaround installs", main.install_double_default_workaround())
try:
    from pystray._util import win32 as pystray_win32

    hmenu = pystray_win32.CreatePopupMenu()
    try:
        for index in range(2):
            info = pystray_win32.MENUITEMINFO(
                cbSize=ctypes.sizeof(pystray_win32.MENUITEMINFO),
                fMask=pystray_win32.MIIM_STATE | pystray_win32.MIIM_STRING,
                fState=pystray_win32.MFS_DEFAULT,
                dwTypeData="bold-%d" % index,
            )
            pystray_win32.InsertMenuItem(hmenu, index, True, ctypes.byref(info))
        states = [main._menu_item_state(hmenu, index) for index in range(2)]
        check("ctypes: both inserted items carry MFS_DEFAULT",
              all(state is not None and (state & pystray_win32.MFS_DEFAULT) for state in states),
              states)
        check("ctypes: no third item exists",
              main._menu_item_state(hmenu, 2) is None, main._menu_item_state(hmenu, 2))
    finally:
        pystray_win32.DestroyMenu(hmenu)
except Exception as exc:  # noqa: BLE001
    check("ctypes dual-default probe", False, repr(exc))

# ---------------- ④ English mode keeps the same two defaults ----------------
saved_lang = main.CFG.get("ui_lang")
main.CFG["ui_lang"] = "en"
main.i18n_bridge.sync_lang("en")
try:
    check_defaults("en")
    check("en: double-click primary is the Studio item",
          main.build_menu()._primary_item.text == "Open ReMe Studio",
          main.build_menu()._primary_item.text)
finally:
    main.CFG["ui_lang"] = saved_lang if saved_lang is not None else "zh"
    main.i18n_bridge.sync_lang("zh")

print("TRAY MENU TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
