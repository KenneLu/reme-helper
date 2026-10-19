# -*- coding: utf-8 -*-
"""日志初始化失败不得让模块导入崩溃（启动期回归）。

场景：日志目录路径被另一个实例/升级窗口占住（或 `log` 恰好是普通文件）时，
`make_logger()` 内部 mkdir / FileHandler 会抛；模块级调用若直接把异常抛出去，
PyInstaller 启动即崩——而 log_kit 自己承诺「任何日志失败都静默」。

断言方式：子进程 import main，`REME_HELPER_DATA_DIR` 指向临时目录，并把该数据区
真实的 `log` 路径预创建成**普通文件**（使 mkdir/打开必失败）→
  ① import 退出码 0、无 Traceback；
  ② 打印了可见的失败信号（stderr）；
  ③ 兜底 `log` 仍是 print 形态（可变参数可调用）、`open_log_dir` 可调用且不抛。
不依赖真实 AppData、不启 GUI / 服务。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


def run_python(code, env):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="reme-helper-logfail-") as temp:
        data = Path(temp) / "data"
        data.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "REME_HELPER_DATA_DIR": str(data), "PYTHONUTF8": "1"}
        env.pop("REME_HELPER_CONFIG", None)

        # 1) 先问出这次数据区下真实的日志路径（不导入 main，避免受被测代码影响）
        probe = run_python(
            "import sys; sys.path.insert(0, %r); "
            "from template.paths.paths import LOG_DIR; print(str(LOG_DIR))" % str(SRC),
            env,
        )
        check("probe: log path resolved", probe.returncode == 0 and probe.stdout.strip(),
              (probe.returncode, probe.stdout, probe.stderr[-300:]))
        if probe.returncode != 0 or not probe.stdout.strip():
            print("LOG FAIL-OPEN TEST FAILED: " + ",".join(FAILS), flush=True)
            return 1
        log_path = Path(probe.stdout.strip().splitlines()[-1])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("blocked by the fail-open regression test", encoding="utf-8")
        check("setup: log path is a regular file (blocks mkdir/handler)", log_path.is_file())

        # 2) 真正的回归：导入 main 必须成功，且兜底闭包保持 print 形态契约
        code = (
            "import sys; sys.path.insert(0, %r); "
            "import main; "
            "print('IMPORT OK'); "
            "main.log('fallback', 'accepts', 3, 'parts'); "
            "main.open_log_dir(); "
            "print('FALLBACK CALL OK')" % str(SRC)
        )
        result = run_python(code, env)
        combined = (result.stdout or "") + (result.stderr or "")
        check("import exits 0 with the log path blocked", result.returncode == 0,
              (result.returncode, combined[-500:]))
        check("module import completed", "IMPORT OK" in (result.stdout or ""), result.stdout[-300:])
        check("no uncaught traceback", "Traceback" not in combined, combined[-500:])
        check("failure was signalled (not silent)", "log init failed" in (result.stderr or ""),
              (result.stderr or "")[-300:])
        check("fallback log/open_log_dir callable without raising",
              "FALLBACK CALL OK" in (result.stdout or ""), result.stdout[-300:])

    print("LOG FAIL-OPEN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
