# -*- coding: utf-8 -*-
"""Wave 3.3：从当前 ReMe venv 的 ``default.yaml`` 重生成三份配置（走脚本，不走 GUI）。

在 helper 仓根目录执行：

    H:\\Tools\\Python\\Python313\\python.exe scripts\regen_configs.py

等价于设置页的「验证并保存」：``minimal``/``full`` 用预设，``custom`` 用 live 配置
（``%LOCALAPPDATA%\\reme-helper\\config.json``）里的功能开关。**生成物禁止手改。**

环境要求：
  * Python 用 ``H:\\Tools\\Python\\Python313\\python.exe``（源码态需要 pystray / Pillow /
    PyYAML；ReMe venv 缺 pystray，不要用它跑本脚本）。
  * **不需要 GUI 初始化**：GUI 只在 ``src/main.py`` 的 ``main()``（``__main__``）里启动，
    本脚本只 ``import main``，因此会加载 ``CFG``（读 live 配置）但不启动托盘。
  * 上游来源：``official_default_config()`` 读
    ``<reme_root>/venv/Lib/site-packages/reme/config/default.yaml``（应为 0.4.2.3，45 个 job）。
    脚本会在生成前校验 0.4.2.3 标志，缺标志直接报错退出。

形态一（已采纳）：不改 ``codex_app_server.default.codex_home``（保持 ``.codex``）；脚本只
打印它供复核。``.env`` 登记 ``CODEX_OAUTH_MODEL_NAME`` 属另一步，本脚本不写 ``.env``。

选项：
  * ``--out DIR``：把三份配置写到 DIR（默认 ``<reme_root>/config``）。干跑验证用，不碰 live。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main  # noqa: E402  （导入即加载 live 配置 CFG，不启动 GUI）
import yaml  # noqa: E402

TARGETS = (("minimal", "app.yaml"), ("full", "app-full.yaml"), ("custom", "app-custom.yaml"))
# 0.4.2.3 的标志 job（0.4.2.1 没有），用来证明读到的上游表是 0.4.2.3。
MARKERS = {"session_read", "session_status", "session_append", "job_status", "dashscope_search"}


def run() -> int:
    parser = argparse.ArgumentParser(description="Regenerate the three ReMe mode configs from the installed default.yaml.")
    parser.add_argument("--out", default=None, help="output directory (default: <reme_root>/config)")
    args = parser.parse_args()

    root = main.reme_root()
    official = main.official_default_config()
    official_jobs = set(official.get("jobs") or {})
    official_components = set(official.get("components") or {})

    print(f"reme_root              = {root}")
    print(f"official default.yaml  = {main.official_default_path()}")
    print(f"official jobs          = {len(official_jobs)}")
    print(f"official components    = {len(official_components)}")

    missing = MARKERS - official_jobs
    if missing:
        print(f"ERROR: 上游 default.yaml 不是 0.4.2.3（缺标志 job：{sorted(missing)}）", file=sys.stderr)
        return 1

    out_dir = Path(args.out).expanduser() if args.out else root / "config"
    out_dir.mkdir(parents=True, exist_ok=True)

    rc = 0
    for mode, name in TARGETS:
        target = out_dir / name
        main.generate_mode_config(mode, target)
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        jobs = set(data.get("jobs") or {})
        components = set(data.get("components") or {})
        app_default = ((data.get("components") or {}).get("codex_app_server") or {}).get("default") or {}
        extra = jobs - official_jobs
        status = "OK" if not extra else f"ERROR 非法 job：{sorted(extra)}"
        if extra:
            rc = 1
        print(f"[{mode}] {target}")
        print(f"    jobs={len(jobs)} components={len(components)} "
              f"dashscope_search={'dashscope_search' in jobs} "
              f"codex_home={app_default.get('codex_home')!r}  {status}")
    return rc


if __name__ == "__main__":
    raise SystemExit(run())
