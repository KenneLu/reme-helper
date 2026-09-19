# -*- coding: utf-8 -*-
"""更新器 bat 的真实执行测试（成功 + 失败注入）。

背景（2026-09-19 自查发现的最高风险缺陷）：bat 里 `robocopy` 之后只
`echo rc=` 而**不判 errorlevel**，随后**无条件** `start` 新 exe —— 一旦铺设失败
（磁盘满/文件被占/源缺失），会留下**半铺的安装目录**却报 done；而 `_backup` 不是
回滚源，且下一次更新开头还会把它删掉（唯一手工回退材料也没了）。

本测试**真跑** `main.HELPER_UPDATE_BAT` 渲染出的脚本（不 mock），用假 exe（probe.vbs）
观察"到底启动了哪个版本"，断言：
  成功：新版本被启动、安装目录已更新、快照轮转成 BACKUP；
  失败注入（STAGE 不存在 ⇒ robocopy rc=16）：**不启动新版本**、回退后启动旧版本、
          留下 update.failed marker、快照保留可人工恢复。

**桌面无扰**：假 exe 用 `.vbs`（`wscript`，无控制台）而不是 `.bat`——更新器用
`start "" <exe>` 启动目标，启动 .bat 会弹出一个可见控制台窗口，构建期就会在用户桌面上
闪一下。产品本身启动的是 `--noconsole` 的 GUI exe，所以这里保持"什么都看不见"才是忠实的；
本测试自身跑 cmd 也带 `CREATE_NO_WINDOW`。

实例隔离：全部在临时目录里跑；probe.vbs 写绝对路径的 marker，避免 cwd 影响。
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


def _probe_script(marker: Path) -> str:
    """The fake "exe": when started, it writes the marker file (absolute path).

    Deliberately a **.vbs**, not a .bat: the updater starts it with `start "" <exe>`, and
    starting a .bat pops a visible console window - during a build gate that is a window
    flashing on the user's desktop. `wscript` runs .vbs with no console at all. The real
    product starts a `--noconsole` GUI exe, so this keeps the probe faithful in the one
    way that matters (nothing visible) without touching the production line.
    """
    return ('CreateObject("Scripting.FileSystemObject").CreateTextFile("%s", True).Write "x"\r\n'
            % str(marker))


def _rmtree_retry(path: Path, attempts: int = 10, delay: float = 0.3) -> bool:
    """删除临时目录，失败重试：刚 start 的进程可能还占着 cwd（Windows 会拒绝删除）。

    一次性 `rmtree(ignore_errors=True)` 会把失败吞掉并**静默留下空壳**——本轮实测
    在 %TEMP% 里留了三个 `reme-update-bat-*`，所以这里重试并返回是否真的删掉。
    """
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(delay)
    return False


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
    (install / "probe.vbs").write_text(_probe_script(install / "started-old.txt"),
                                       encoding="ascii")
    (install / "data-old.txt").write_text("old", encoding="utf-8")
    if not stage_missing:
        # 新版一旦被铺进 install，就从 install 运行 → 它的 marker 也写在 install 下
        (stage / "probe.vbs").write_text(_probe_script(install / "started-new.txt"),
                                         encoding="ascii")
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
        log=paths["log"], exe="probe.vbs", limit=2, stamp="test",
    )
    bat = root / "updater.bat"
    bat.write_text(text, encoding="ascii", newline="")
    subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(root), timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
        _rmtree_retry(root)

    # 「不留垃圾」要变成机械判据：本轮实测到过空壳目录（窗口/进程的 cwd 还占着，
    # 一次性 rmtree 会静默失败并留在 %TEMP%），所以这里断言而不是"希望它删掉了"。
    leftovers = sorted(p.name for p in Path(tempfile.gettempdir()).glob("reme-update-bat-*"))
    check("no temp leftovers from this test", not leftovers, ", ".join(leftovers))

    print("UPDATE BAT TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main_test())
