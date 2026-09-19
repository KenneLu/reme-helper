# -*- coding: utf-8 -*-
"""更新器 bat 的真实执行测试（成功 + 失败注入）。

背景（2026-09-19 自查发现的最高风险缺陷）：bat 里 `robocopy` 之后只
`echo rc=` 而**不判 errorlevel**，随后**无条件** `start` 新 exe —— 一旦铺设失败
（磁盘满/文件被占/源缺失），会留下**半铺的安装目录**却报 done；而 `_backup` 不是
回滚源，且下一次更新开头还会把它删掉（唯一手工回退材料也没了）。

本测试**真跑** `main.HELPER_UPDATE_BAT` 渲染出的脚本（不 mock），用假 exe（probe.vbs）
观察"到底启动了哪个版本"，断言：
  成功：新版本被启动、安装目录已更新、快照轮转成 BACKUP；
  空 STAGE（**存在但无 exe** ⇒ robocopy /purge 会把 install 清空而 rc=2 落在"成功"区间）：
          安装目录**分毫不动**、写 marker、不启动、脚本立刻返回——这是 2026-09-19 修掉的
          缺陷：原脚本把 exe 检查放在 `move SNAPSHOT→BACKUP` **之后**，回滚源已被搬走，
          `:start_missing` 从空路径回铺必然失败 ⇒ install 留空、工具起不来（实测 rc=2 时
          install 被清空；见 `:gone` 的注释）；
  STAGE 不存在：同样在**动手之前**中止（新加的源前置校验），install 不动；
  铺设失败（INSTALL 位置不可用 ⇒ robocopy rc=16）：**不启动新版本**、写 marker、
          回滚也失败时走 `:install_dead`，且日志里的"保留位置"必须**真实存在**。

**桌面无扰**：假 exe 用 `.vbs`（`wscript`，无控制台）而不是 `.bat`——更新器用
`start "" <exe>` 启动目标，启动 .bat 会弹出一个可见控制台窗口，构建期就会在用户桌面上
闪一下。产品本身启动的是 `--noconsole` 的 GUI exe，所以这里保持"什么都看不见"才是忠实的；
本测试自身跑 cmd 也带 `CREATE_NO_WINDOW`。

实例隔离：全部在临时目录里跑；probe.vbs 写绝对路径的 marker，避免 cwd 影响。
"""
from __future__ import annotations

import os
import re
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


def _probe_script(marker: Path, note: str = "") -> str:
    """The fake "exe": when started, it writes the marker file (absolute path).

    Deliberately a **.vbs**, not a .bat: the updater starts it with `start "" <exe>`, and
    starting a .bat pops a visible console window - during a build gate that is a window
    flashing on the user's desktop. `wscript` runs .vbs with no console at all. The real
    product starts a `--noconsole` GUI exe, so this keeps the probe faithful in the one
    way that matters (nothing visible) without touching the production line.

    `note` is not decoration: robocopy treats a destination file as "the same file" and
    SKIPS it when the size and the timestamp match, without comparing content. The install
    probe and the stage probe used to be byte-identical in length (their only difference
    was `started-old.txt` vs `started-new.txt`, same character count) and were written
    microseconds apart, i.e. inside the same system-clock tick - so the copy was skipped
    roughly one run in three and the "install carries the NEW version" check flaked. Giving
    the two scripts different lengths makes the skip impossible.
    """
    body = ('CreateObject("Scripting.FileSystemObject").CreateTextFile("%s", True).Write "x"\r\n'
            % str(marker))
    return ("' %s\r\n%s" % (note, body)) if note else body


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


def _observe_started(marker: Path, what: str) -> None:
    """观察（但**不作为判据**）被 `start` 拉起的进程是否写下 marker。

    `start ""` 是异步的，且门禁连续跑时 Windows 可能拒绝新建进程/控制台（桌面堆压力；
    用户此前用 .bat 假 exe 时正是 1/3 概率撞上）。**启动决策**用确定性证据断言（安装目录
    里的文件内容 + 日志分支），**守卫本身**用静态检查断言；marker 缺失只记录不判失败。
    """
    if _wait_for(marker, 5.0):
        print("  ok   observed: %s process wrote its marker" % what, flush=True)
    else:
        print("  ..   observation skipped: %s marker absent (start may be refused under "
              "repeated runs; the replacement/decision checks above are deterministic)"
              % what, flush=True)


def _stage_root(root: Path, stage_missing: bool = False, stage_empty: bool = False,
                install_exe: bool = True, install_as_file: bool = False) -> dict:
    """布置 install/stage/work 三区；返回给 bat 模板的路径参数。

    stage_missing：STAGE 路径**不存在**（robocopy rc=16）。
    stage_empty  ：STAGE **存在但是空的**（有目录、没有 exe）。这是最危险的一态，
                   也正是 2026-09-19 修复的注入形态（见文件头）。
    install_as_file：INSTALL 被一个**同名文件**占住（"安装目录不可用"），用来把
                   robocopy 确定性地打成 rc≥8，走到 :install_failed / :install_dead。
    """
    install = root / "install"
    stage = root / "stage"
    work = root / "work"
    for d in (install, stage, work):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    if not install_as_file:
        install.mkdir(parents=True)
    stage.mkdir(parents=True)
    work.mkdir(parents=True)
    # 每个用例从干净的 log/marker 开始：bat 是**追加**日志的，否则上一个用例的
    # "done"/失败内容会串进下一个用例的断言（实测踩到：成功用例的 done 让
    # "failure: never reported done" 假红）。
    for leftover in (root / "update.log", root / "update.failed"):
        leftovers = [leftover, *(root.glob(leftover.name + ".*"))]
        for f in leftovers:
            try:
                f.unlink()
            except OSError:
                pass
    if install_as_file:
        install.write_text("not a directory", encoding="utf-8")
    else:
        if install_exe:
            (install / "probe.vbs").write_text(
                _probe_script(install / "started-old.txt", note="old"),
                encoding="ascii")
        (install / "data-old.txt").write_text("old", encoding="utf-8")
    if not stage_missing and not stage_empty:
        # 新版一旦被铺进 install，就从 install 运行 → 它的 marker 也写在 install 下。
        # note 故意比 old 那份长：让两份 probe 脚本**大小不同**，否则 robocopy 会因
        # "大小 + 时间戳相同"把新脚本当成同一个文件跳过（见 _probe_script）。
        (stage / "probe.vbs").write_text(
            _probe_script(install / "started-new.txt",
                          note="new version, longer than the old note on purpose"),
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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _old_version_in_place(install: Path) -> bool:
    """install 里的 probe.vbs 仍是**旧版本那一份**（marker 指向 started-old.txt）。"""
    probe = install / "probe.vbs"
    return probe.exists() and "started-old.txt" in _read(probe)


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


def _static_checks() -> None:
    """渲染出的 bat 的机械卫生（不依赖运行）：

    ① 每个 `goto X` 都要有 `:X`——2026-09-19 真实回归：重写尾部时把 `:giveup`
       删了而循环仍在 `goto giveup`，超时路径会跳到不存在的标签（脚本直接中止）。
    ② 每个 `start ""` 前必须紧邻 `if not exist` 守卫——`start` 一个不存在的 exe 会
       弹**无法关闭**的模态错误框，而更新器是 detached 的，会永久挂住（模板 1.4.0 的
       同款教训）。
    """
    rendered = main.HELPER_UPDATE_BAT.format(
        install=r"C:\i", stage=r"C:\s", work=r"C:\w", backup=r"C:\b",
        snapshot=r"C:\b.pre", failed=r"C:\f", log=r"C:\l", exe="probe.vbs",
        limit=2, stamp="static")
    lines = rendered.splitlines()
    labels = {l.strip()[1:] for l in lines if l.startswith(":")}
    gotos = set(re.findall(r"goto (\w+)", rendered))
    check("bat: every goto target has a matching label", not (gotos - labels),
          "unresolved: %s" % ", ".join(sorted(gotos - labels)))
    # 守卫不必与 start 紧邻，但必须落在**同一个标签块内**（中间可能夹一段日志 echo）。
    unguarded = []
    for i, line in enumerate(lines):
        if not line.startswith('start ""'):
            continue
        guarded = False
        for j in range(i - 1, max(-1, i - 7), -1):
            if lines[j].startswith(":"):
                break
            if lines[j].lstrip().startswith("if not exist") and "probe.vbs" in lines[j]:
                guarded = True
                break
        if not guarded:
            unguarded.append(i + 1)
    check("bat: every start is guarded by an existence check", not unguarded,
          "unguarded at lines %s" % unguarded)


def main_test() -> int:
    root = Path(tempfile.mkdtemp(prefix="reme-update-bat-"))
    try:
        _static_checks()

        # ---------- 成功路径 ----------
        paths = _stage_root(root)
        _run_bat(root, paths)
        install_probe = _read(paths["install"] / "probe.vbs")
        observed_marker = re.search(r"started-(\w+)\.txt", install_probe)
        check("success: install carries the NEW version",
              "started-new.txt" in install_probe,
              "marker=%s install listing=%s"
              % (observed_marker.group(1) if observed_marker else "?",
                 sorted(p.name for p in paths["install"].iterdir())))
        check("success: install updated",
              (paths["install"] / "data-new.txt").exists())
        check("success: old snapshot rotated into BACKUP",
              (paths["backup"] / "data-old.txt").exists()
              and not paths["snapshot"].exists())
        check("success: no failure marker", not paths["failed"].exists())
        check("success: work cleaned", not paths["work"].exists())
        _observe_started(paths["install"] / "started-new.txt", "new version")

        # ---------- 空 STAGE（存在但无 exe）⇒ install 必须分毫不动 ----------
        # 修复前：rc=2 被当成成功 → install 被 /purge 清空 → move SNAPSHOT→BACKUP 把
        # 回滚源搬走 → :start_missing 从已不存在的 SNAPSHOT 回铺 → install 留空。
        paths = _stage_root(root, stage_empty=True)
        elapsed = time.time()
        _run_bat(root, paths)
        elapsed = time.time() - elapsed
        empty_log = _read(paths["log"])
        check("empty stage: old exe untouched", _old_version_in_place(paths["install"]))
        check("empty stage: old payload untouched", (paths["install"] / "data-old.txt").exists()
              and not (paths["install"] / "data-new.txt").exists())
        check("empty stage: install was not purged", (paths["install"] / "data-old.txt").read_text(
            encoding="utf-8") == "old")
        check("empty stage: log says install untouched", "install untouched" in empty_log,
              empty_log[-160:].replace("\n", " | "))
        check("empty stage: marker written", paths["failed"].exists())
        check("empty stage: never reported done", "[test] done" not in empty_log)
        check("empty stage: never entered the failed-copy path", "INSTALL FAILED" not in empty_log)
        check("empty stage: no restore was attempted", "RESTORE FAILED" not in empty_log)
        check("empty stage: script returned promptly (did not block)", elapsed < 30,
              "%.1fs" % elapsed)
        _observe_started(paths["install"] / "started-old.txt", "previous version (untouched install)")

        # ---------- STAGE 不存在：同样在动手之前中止 ----------
        paths = _stage_root(root, stage_missing=True)
        _run_bat(root, paths)
        missing_log = _read(paths["log"])
        check("missing stage: old exe untouched", _old_version_in_place(paths["install"]))
        check("missing stage: old payload untouched", (paths["install"] / "data-old.txt").exists())
        check("missing stage: log says install untouched", "install untouched" in missing_log,
              missing_log[-160:].replace("\n", " | "))
        check("missing stage: marker written", paths["failed"].exists())
        check("missing stage: never reported done", "[test] done" not in missing_log)
        _observe_started(paths["install"] / "started-old.txt", "previous version (untouched install)")

        # ---------- 空 STAGE 且 install 本来就没有 exe：仍然什么都不启动 ----------
        # `start` 一个不存在的 exe 会弹**无法关闭**的模态错误框，而更新器是 detached 的，
        # 会永久挂住——所以"没得启动"时唯一正确的动作是写 marker 然后退场。
        paths = _stage_root(root, stage_empty=True, install_exe=False)
        _run_bat(root, paths)
        check("no exe anywhere: install still has no exe",
              not (paths["install"] / "probe.vbs").exists())
        check("no exe anywhere: marker written", paths["failed"].exists())
        check("no exe anywhere: nothing was started",
              not _wait_for(paths["install"] / "started-old.txt", 3.0))

        # ---------- 铺设失败注入：INSTALL 位置不可用 ⇒ robocopy rc=16 ----------
        paths = _stage_root(root, install_as_file=True)
        _run_bat(root, paths)
        dead_log = _read(paths["log"])
        check("copy failure: marker written", paths["failed"].exists())
        check("copy failure: log records the failed rc", "INSTALL FAILED rc=16" in dead_log,
              dead_log[-160:].replace("\n", " | "))
        # 决策级证据（确定性）：失败分支**从未**走到 "done"（那是替换成功才有的行）
        check("copy failure: never reported done", "[test] done" not in dead_log)
        check("copy failure: restore could not produce an exe, last resort logged",
              "RESTORE FAILED" in dead_log, dead_log[-160:].replace("\n", " | "))
        check("copy failure: did not start anything", not (paths["install"] / "probe.vbs").exists())
        # 修复③：install_dead 的"保留位置"必须**真实存在**（旧文案恒定打印 %SNAPSHOT%，
        # 而在 move 之后 SNAPSHOT 早已不存在，等于把用户指向一个空路径）。
        kept = re.search(r"rollback copies kept at (.+)$", dead_log, re.M)
        named = [p for p in (kept.group(1).split() if kept else []) if os.path.isabs(p)]
        check("copy failure: kept-path report names only paths that exist",
              bool(kept) and all(Path(p).exists() for p in named),
              "named=%s" % named)
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
