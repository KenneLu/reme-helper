# -*- coding: utf-8 -*-
"""ReMe 版本固定（`SUPPORTED_REME_VERSION`）——用户 2026-09-19 直接需求。

背景：助手要生成三份配置、内省思考强度档位、核对 MCP 工具白名单，这些都依赖目标版本
`default.yaml` 的 job 表与依赖 pin。旧实现的升级目标是「PyPI 上查到的最新版」——上游
一发新版，托盘就提示"有新版本"并把用户往未验证的组合上引。

本测试把新语义钉死成机械判据：
  ① **单点定义**：版本号只写在 appconfig（T1 参数区），main.py 里没有第二份字面量；
  ② **四象限文案**：本机 < pin（提示升级，且目标就是 pin）/ == pin（已最新）/
     > pin（越界警告，**不**给升级引导）/ 上游 > pin（只提示"尚未适配"，绝不引导升级）；
  ③ **提示词锁版本**：安装 / 升级两份提示词都含 `==<pin>`，**不含**「最新稳定版」，
     且上游有更新版本时渲染出的 pip 目标**仍然是 pin**（这是本需求的核心）；
  ④ 负数面：源码与词表里都不再出现「最新稳定版」这个引导性说法。

全部离线：`fetch_latest_reme_version` 被打桩，绝不碰网络（门禁要能断网跑）。
"""
from __future__ import annotations

import sys

from conftest import SRC_DIR, TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


PIN = main.SUPPORTED_REME_VERSION

# ---------- ① 单点定义 ----------
check("pin is non-empty", bool(PIN), repr(PIN))
check("pin comes from the appconfig parameter file",
      main.appconfig.SUPPORTED_REME_VERSION == PIN, repr(main.appconfig.SUPPORTED_REME_VERSION))

source = (SRC_DIR / "main.py").read_text(encoding="utf-8", errors="replace")
assignments = [line.strip() for line in source.splitlines()
               if line.strip().startswith("SUPPORTED_REME_VERSION")]
check("main.py holds no second literal definition (single source in appconfig)",
      assignments == [], "found: %s" % assignments)

# ---------- ② 四象限 ----------
# 本机装了什么不影响判定——`reme_versions()` 被打桩，门禁在哪台机器上跑结论都一样。
main.fetch_latest_reme_version = lambda *_a, **_k: (True, "9.9.9")   # 上游永远比 pin 新
old_pin = "0.4.1.10" if PIN != "0.4.1.10" else "0.4.1.9"
check("outdated: state", main.reme_pin_state(old_pin) == main.REME_PIN_OUTDATED,
      main.reme_pin_state(old_pin))

main.reme_versions = lambda: {"reme-ai": old_pin, "reme_studio": "0.1.1"}
main.REME_UPDATE_STATE.update(checked_for="", latest="", at=0.0, error="")
outdated, outdated_text = main.check_reme_update()
check("outdated: reported with an upgrade hint", bool(outdated) and ("升级" in outdated_text),
      outdated_text)
check("outdated: upgrade target is the pin, not upstream", ("==" + PIN) in outdated_text
      and ("9.9.9" not in outdated_text), outdated_text)

# == pin
main.reme_versions = lambda: {"reme-ai": PIN, "reme_studio": "0.1.1"}
main.REME_UPDATE_STATE.update(checked_for="", latest="", at=0.0, error="")
ok_flag, ok_text = main.check_reme_update()
check("ok: state", main.reme_pin_state(PIN) == main.REME_PIN_OK)
check("ok: message says latest supported version", "最新适配版本" in ok_text, ok_text)
check("ok: upstream newer only adds a do-not-upgrade note",
      "9.9.9" in ok_text and "尚未适配" in ok_text and "升级" not in ok_text.replace("不要升级", ""),
      ok_text)

# > pin（越界）
ahead_pin = PIN + ".1"
main.reme_versions = lambda: {"reme-ai": ahead_pin, "reme_studio": "0.1.1"}
main.REME_UPDATE_STATE.update(checked_for="", latest="", at=0.0, error="")
ahead_flag, ahead_text = main.check_reme_update()
check("ahead: state", main.reme_pin_state(ahead_pin) == main.REME_PIN_AHEAD)
check("ahead: message warns it is beyond the supported version",
      "高于" in ahead_text and "未适配" in ahead_text, ahead_text)
check("ahead: never tells the user to upgrade", "建议升级" not in ahead_text, ahead_text)

# 上游 > pin 的附注本身
note = main.reme_upstream_note("9.9.9")
check("upstream note: says not supported yet, do not upgrade",
      "尚未适配" in note and "不要升级" in note, note)
check("upstream note: silent when upstream is not newer", main.reme_upstream_note(PIN) == "")

# 托盘版本行（四象限的界面形态）
main.reme_versions = lambda: {"reme-ai": old_pin, "reme_studio": "0.1.1"}
main.REME_UPDATE_STATE.update(checked_for="", latest="", at=0.0, error="")
check("tray line: outdated points at the pin",
      ("可升级到 " + PIN) in main.reme_version_text(), main.reme_version_text())
main.reme_versions = lambda: {"reme-ai": ahead_pin, "reme_studio": "0.1.1"}
check("tray line: ahead says unsupported",
      ("未适配" in main.reme_version_text()), main.reme_version_text())

# ---------- ③ 提示词锁版本 ----------
pinned = "reme-ai[core]==%s" % PIN
install = main.reme_install_prompt()
check("install prompt pins the version", pinned in install,
      " | ".join(line for line in install.splitlines() if "pip install" in line))
check("install prompt forbids latest", "不要装更高版本" in install and "latest" in install)

# 变异负控：把**共享状态**染成"上游有 9.9.9"。提示词的目标版本不吃这个状态——
# `reme_upgrade_prompt` 用参数，`reme_upgrade_target()` 直接返回常量。以后谁要是
# 把升级目标接回 REME_UPDATE_STATE["latest"]（旧实现就是那个形态），这条会立刻红。
main.REME_UPDATE_STATE.update(checked_for=old_pin, latest="9.9.9", at=0.0, error="")
check("poisoned state cannot move the upgrade target", main.reme_upgrade_target() == PIN,
      main.reme_upgrade_target())

# 关键：上游有更新版本时，升级提示词的 pip 目标**仍然是 pin**
upgrade = main.reme_upgrade_prompt(current=old_pin, latest="9.9.9")
check("upgrade prompt pins the version even when upstream is newer", pinned in upgrade,
      " | ".join(line for line in upgrade.splitlines() if "pip install" in line))
# 同一条走"不带 latest 参数"的路径：目标也必须还是 pin（这里读的是被染过的状态）
upgrade_from_state = main.reme_upgrade_prompt(current=old_pin)
check("upgrade prompt without an explicit latest still pins the pin",
      pinned in upgrade_from_state and ("9.9.9" in upgrade_from_state),
      " | ".join(line for line in upgrade_from_state.splitlines() if "pip install" in line))
check("upgrade prompt names the pin as the target",
      ("reme-ai==" + PIN) in upgrade,
      " | ".join(line for line in upgrade.splitlines() if "目标版本" in line))
check("upgrade prompt tells the AI not to substitute another version",
      "不要自己换一个" in upgrade and "不要装更新的版本" in upgrade)
check("upgrade prompt keeps the upstream note advisory only",
      "9.9.9" in upgrade and "尚未适配" in upgrade)
check("pip spec helper is the single formatter",
      main.reme_pip_spec() == pinned and main.reme_upgrade_target() == PIN)

# ---------- ④ 负数面：源码与词表里不再有「最新稳定版」 ----------
for path in (SRC_DIR / "main.py", SRC_DIR / "modules" / "i18n" / "pairs.json"):
    text = path.read_text(encoding="utf-8", errors="replace")
    check("no 'latest stable' wording in %s" % path.name, "最新稳定版" not in text)

check("no 'latest stable' wording in either prompt",
      "最新稳定版" not in install and "最新稳定版" not in upgrade)

print("REME VERSION PIN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
