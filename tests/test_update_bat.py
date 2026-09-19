# -*- coding: utf-8 -*-
"""更新器 bat 的真实执行测试（成功 + 失败注入）。

背景（2026-09-19 自查发现的最高风险缺陷）：bat 里 `robocopy` 之后只
`echo rc=` 而**不判 errorlevel**，随后**无条件** `start` 新 exe —— 一旦铺设失败
（磁盘满/文件被占/源缺失），会留下**半铺的安装目录**却报 done；而 `_backup` 不是
回滚源，且下一次更新开头还会把它删掉（唯一手工回退材料也没了）。

本测试**真跑** `main.HELPER_UPDATE_BAT` 渲染出的脚本（不 mock），用假 exe（probe.bat）
观察"到底启动了哪个版本"，断言：
  成功：新版本被启动、安装目录已更新、快照轮转成 BACKUP；
  失败注入（STAGE 不存在 ⇒ robocopy rc=16）：**不启动新版本**、回退后启动旧版本、
          留下 update.failed marker、快照保留可人工恢复。

实例隔离：全部在临时目录里跑；probe.bat 写绝对路径的 marker，避免 cwd 影响。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def _probe_bat(marker_name: str) -> str:
    """一个"假 exe"：被 start 时写一个 marker 文件（绝对路径）。"""
    return '@echo off\r\necho started > "%~dp0' + marker_name + '"\r\n'


def _wait_for(path: Path, seconds: float = 10.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False


def _stage_root(root: Path, stage_missing: bool = False) -> dict:
    """布置 install/stage/work 三区；返回给 bat 模板的路径参数。"""
    install = root / "install"
    stage = root / "stage"
    work = root / "work"
    for d in (install, stage, work):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    (install / "probe.bat").write_text(_probe_bat("started-old.txt"), encoding="ascii")
    (install / "data-old.txt").write_text("old", encoding="utf-8")
    if not stage_missing:
        (stage / "probe.bat").write_text(_probe_bat("started-new.txt"), encoding="ascii")
        (stage / "data-new.txt").write_text("new", encoding="utf-8")
    return {
        "install": install,
        "stage": stage if not stage_missing else (root / "no-such-stage"),
        "work": work,
        "backup": root / "_backup",
        "snapshot": root / "_backup.pre",
        "failed": root / "update.failed",
        "log": root / "update.log",
    }


def _run_bat(root: Path, paths: dict) -> None:
    text = main.HELPER_UPDATE_BAT.format(
        install=paths["install"], stage=paths["stage"], work=paths["work"],
        backup=paths["backup"], snapshot=paths["snapshot"], failed=paths["failed"],
        log=paths["log"], exe="probe.bat", limit=2, stamp="test",
    )
    bat = root / "updater.bat"
    bat.write_text(text, encoding="ascii", newline="")
    subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(root), timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main_test() -> int:
    root = Path(tempfile.mkdtemp(prefix="reme-update-bat-"))
    try:
        # ---------- 成功路径 ----------
        paths = _stage_root(root)
        _run_bat(root, paths)
        check("success: new version started",
              _wait_for(paths["install"] / "started-new.txt"))
        check("success: install updated",
              (paths["install"] / "data-new.txt").exists())
        check("success: old snapshot rotated into BACKUP",
              (paths["backup"] / "data-old.txt").exists()
              and not paths["snapshot"].exists())
        check("success: no failure marker", not paths["failed"].exists())
        check("success: work cleaned", not paths["work"].exists())

        # ---------- 失败注入：STAGE 不存在 ⇒ robocopy rc=16 ----------
        paths = _stage_root(root, stage_missing=True)
        _run_bat(root, paths)
        check("failure: new version NOT started",
              not _wait_for(paths["install"] / "started-new.txt", 3.0))
        check("failure: previous version was started after restore",
              _wait_for(paths["install"] / "started-old.txt"))
        check("failure: install still has the old payload",
              (paths["install"] / "data-old.txt").exists()
              and not (paths["install"] / "data-new.txt").exists())
        check("failure: marker written", paths["failed"].exists())
        check("failure: snapshot kept for manual recovery", paths["snapshot"].exists())
        log_text = paths["log"].read_text(encoding="utf-8", errors="replace")
        check("failure: log records the failed rc", "INSTALL FAILED rc=" in log_text,
              log_text[-120:].replace("\n", " | "))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("UPDATE BAT TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main_test())
