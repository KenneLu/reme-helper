# -*- coding: utf-8 -*-
"""autostart 模板件（1.2.1）单测：monkeypatch winreg，零真实注册表读写。

四用例（W4 补，i18n-unify 复核 F-2）：
  ① 无键不新建且出声（migrate：FileNotFoundError → log 一行、零写）
  ② 值 == 当前命令行且目标活着 → 不动（零写）
  ③ 死链重写（值指向不存在的路径 → set_autostart(True) 重写）
  ④ 非 frozen 态 migrate 只读只记（1.2.1 守卫：注册表零接触——
     W4 实测事故的前置红灯，事故语义此前只靠 C-40 事后抓获）
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import SRC_DIR  # noqa: E402  (puts src/ on sys.path)
from template.autostart import autostart  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


class FakeWinreg:
    """winreg 替身：内存表 + 可注入的读行为。所有方法与真实 winreg 同签名（本测试用到的那部分）。"""

    HKEY_CURRENT_USER = 1
    KEY_READ = 2
    REG_SZ = 1

    def __init__(self, table=None, read_error=None):
        self.table = dict(table or {})
        self.read_error = read_error   # None | "filenotfound" | "oserror"
        self.writes = []               # [(sub_key, name, value)] —— 断言"零写"的证据

    class _Key:
        def __init__(self, fake): self._fake = fake
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    # 真实 winreg 的 QueryValueEx/SetValueEx/DeleteValue 是顶层函数（第一参为 key 句柄）
    def QueryValueEx(self, _k, name):
        if self.read_error == "filenotfound":
            raise FileNotFoundError(name)
        if self.read_error == "oserror":
            raise OSError("simulated")
        if name not in self.table:
            raise FileNotFoundError(name)
        return self.table[name], 1

    def SetValueEx(self, _k, name, _reserved, _type, value):
        self.writes.append(("set", name, value))
        self.table[name] = value

    def DeleteValue(self, _k, name):
        self.writes.append(("del", name, None))
        self.table.pop(name, None)

    def OpenKey(self, *_a, **_k): return self._Key(self)
    def CreateKey(self, *_a, **_k): return self._Key(self)


def with_fake(monkeypatch_target, fake, frozen=False, exists=True):
    """把 autostart 模块的 winreg 与环境谓词换成替身。"""
    import types
    mod = autostart
    mod.winreg = fake
    mod.sys = types.SimpleNamespace(executable=sys.executable,
                                    argv=list(sys.argv), frozen=frozen)
    import os as _real_os
    mod.os = types.SimpleNamespace(path=types.SimpleNamespace(
        exists=lambda p: exists, abspath=_real_os.path.abspath))
    return mod


def run() -> int:
    logs = []
    log = logs.append
    key = "reme-helper"  # AUTOSTART_KEY 经 appconfig == APP_ID

    # ① 无键：不新建、要出声
    fake = FakeWinreg(read_error="filenotfound")
    with_fake(None, fake, frozen=True)
    autostart.migrate_autostart(log=log)
    check("no entry: not created", fake.writes == [], str(fake.writes))
    check("no entry: logged once", len(logs) == 1 and "no Run entry" in logs[0], str(logs))

    # ② 值 == 当前命令行且目标活着 → 零写
    logs.clear()
    wanted = autostart.get_autostart_cmd()  # frozen 替身下走 stable/runtime 分支
    fake = FakeWinreg(table={key: wanted})
    with_fake(None, fake, frozen=True, exists=True)
    autostart.migrate_autostart(log=log)
    check("current+alive: no rewrite", fake.writes == [], str(fake.writes))

    # ③ 死链 → 重写
    logs.clear()
    fake = FakeWinreg(table={key: r'"C:\gone\old.exe"'})
    with_fake(None, fake, frozen=True, exists=True)
    autostart.migrate_autostart(log=log)
    check("dead link: rewritten", any(w[0] == "set" and w[1] == key for w in fake.writes), str(fake.writes))
    check("dead link: migration logged", any("migrated" in l or "missing too" in l for l in logs), str(logs))

    # ④ 非 frozen（dev/测试态）→ 注册表零接触（1.2.1 守卫）
    logs.clear()
    fake = FakeWinreg(table={key: r'"C:\gone\old.exe"'})
    with_fake(None, fake, frozen=False, exists=True)
    autostart.migrate_autostart(log=log)
    check("dev run: registry untouched", fake.writes == [], str(fake.writes))
    check("dev run: guard logged", any("dev run" in l for l in logs), str(logs))

    print("AUTOSTART TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(run())
