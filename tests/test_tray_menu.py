# -*- coding: utf-8 -*-
"""托盘菜单文案与默认项（1.2.11 微调）。

1) 中文与英文/字母之间留一个空格（「启动ReMe」这类粘连不再出现）；
2) 「打开 ReMe Studio」与「ReMe 控制台…」一样加粗：两者都带 default=True（Windows 的
   MFS_DEFAULT → 粗体），且**控制台排在前面**，所以 pystray 双击默认项行为不变。
"""
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
    "启动工具时启动 ReMe",
)
for new in SPACED:
    check("spaced text present: %s" % new, new in joined)

check("status row spaced", "ReMe 状态：" in joined)
check("ReMe version row spaced", "ReMe 版本：" in joined)
check("helper version row spaced", "ReMe 助手版本：" in joined)

# ---------------- ② 默认项：恰好一个（「ReMe 控制台…」） ----------------
# 曾给「打开 ReMe Studio」也加 default=True 想做双粗体，但 Windows InsertMenuItem 只接受
# 一个 MFS_DEFAULT 项，第二个会让菜单创建报 WinError 87（参数错误）——已回退。
zh_defaults = default_items()
check("zh: exactly one default item", len(zh_defaults) == 1, [item.text for item in zh_defaults])
check("zh: the only default item is the console item",
      bool(zh_defaults) and zh_defaults[0].text == "ReMe 控制台…",
      zh_defaults[0].text if zh_defaults else None)

items = menu_items()
studio = next((item for item in items if item.text == "打开 ReMe Studio"), None)
check("zh: Open ReMe Studio exists but is not a default item",
      studio is not None and not studio.default,
      None if studio is None else studio.default)
check("zh: text assertions did not lose the Studio entry", studio is not None)

# ---------------- ③ English mode keeps the same single default ----------------
saved_lang = main.CFG.get("ui_lang")
main.CFG["ui_lang"] = "en"
main.i18n_bridge.sync_lang("en")
try:
    en_defaults = default_items()
    check("en: exactly one default item", len(en_defaults) == 1, [item.text for item in en_defaults])
    check("en: the only default item is the console item",
          bool(en_defaults) and en_defaults[0].text == "ReMe console…",
          en_defaults[0].text if en_defaults else None)
    en_studio = next((item for item in menu_items() if item.text == "Open ReMe Studio"), None)
    check("en: Open ReMe Studio is not a default item",
          en_studio is not None and not en_studio.default,
          None if en_studio is None else en_studio.default)
finally:
    main.CFG["ui_lang"] = saved_lang if saved_lang is not None else "zh"
    main.i18n_bridge.sync_lang("zh")

print("TRAY MENU TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
