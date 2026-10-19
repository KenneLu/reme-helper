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

# ---------------- ② 加粗项：恰好两个 default，控制台在前、Studio 在后 ----------------
zh_defaults = default_items()
check("zh: exactly two default items", len(zh_defaults) == 2, [item.text for item in zh_defaults])
check("zh: first default is the console item",
      bool(zh_defaults) and zh_defaults[0].text == "ReMe 控制台…",
      zh_defaults[0].text if zh_defaults else None)
check("zh: second default is Open ReMe Studio",
      len(zh_defaults) > 1 and zh_defaults[1].text == "打开 ReMe Studio",
      zh_defaults[1].text if len(zh_defaults) > 1 else None)

items = menu_items()
console_index = next((i for i, item in enumerate(items) if item.text == "ReMe 控制台…"), None)
studio_index = next((i for i, item in enumerate(items) if item.text == "打开 ReMe Studio"), None)
check("console comes before studio, so double-click still opens the console",
      console_index is not None and studio_index is not None and console_index < studio_index,
      (console_index, studio_index))

# ---------------- ③ English mode keeps the same default order ----------------
saved_lang = main.CFG.get("ui_lang")
main.CFG["ui_lang"] = "en"
main.i18n_bridge.sync_lang("en")
try:
    en_defaults = default_items()
    check("en: exactly two default items", len(en_defaults) == 2, [item.text for item in en_defaults])
    check("en: first default is the console item",
          bool(en_defaults) and en_defaults[0].text == "ReMe console…",
          en_defaults[0].text if en_defaults else None)
    check("en: second default is Open ReMe Studio",
          len(en_defaults) > 1 and en_defaults[1].text == "Open ReMe Studio",
          en_defaults[1].text if len(en_defaults) > 1 else None)
finally:
    main.CFG["ui_lang"] = saved_lang if saved_lang is not None else "zh"
    main.i18n_bridge.sync_lang("zh")

print("TRAY MENU TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
