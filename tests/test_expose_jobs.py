# -*- coding: utf-8 -*-
"""ReMe 0.4.1.13 适配的纯逻辑判据（无窗口、无网络、不碰真 ReMe 安装）。

覆盖三件事：
  ① `is_servable()` 必须排除**显式 `enable_serve: false` 的 base job**
     （0.4.1.13 的 `proactive_refresh`：backend=base 但不对外服务；
     旧逻辑把它当可服务 ⇒ 可能写进 MCP 白名单 ⇒ ReMe add_jobs() raise）。
  ② job 改名：`proactive` → `proactive_read`（EXPOSE 分组/标签/信息/removals 只认新名）。
  ③ 新 job `list_tags`（backend=base、可服务、只读）进入候选名单与「检索与浏览」组，
     且等级/标签/说明齐备。

用**合成 default.yaml 表**（monkeypatch `official_jobs`）跑，不受本机装的 ReMe 版本影响；
真安装表读不到时（CI）同样可跑。
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


# ---------- ① is_servable：enable_serve:false 的 base job 不可服务 ----------
check("is_servable: base + enable_serve:false -> False",
      main.is_servable({"backend": "base", "enable_serve": False}) is False)
check("is_servable: base + enable_serve:true -> True",
      main.is_servable({"backend": "base", "enable_serve": True}) is True)
check("is_servable: base without enable_serve -> True",
      main.is_servable({"backend": "base"}) is True)
check("is_servable: background -> False", main.is_servable({"backend": "background"}) is False)
check("is_servable: cron -> False", main.is_servable({"backend": "cron"}) is False)
check("is_servable: non-dict spec stays permitted (defensive, old behavior)",
      main.is_servable(None) is True)

# ---------- ②③ 候选名单 / 分组 / 标签 / removals（合成 0.4.1.13 表） ----------
_FAKE_DECLARED = {
    "search": {"backend": "base"},
    "read": {"backend": "base"},
    "proactive_read": {"backend": "base"},
    "proactive_refresh": {"backend": "base", "enable_serve": False},
    "proactive_refresh_cron": {"backend": "cron"},
    "list_tags": {"backend": "base"},
    "auto_memory": {"backend": "base"},
    "chat": {"backend": "base"},
}
_saved_official = main.official_jobs
main.official_jobs = lambda: dict(_FAKE_DECLARED)
try:
    names = main.servable_job_names()
    check("candidates: renamed job proactive_read is servable", "proactive_read" in names, names)
    check("candidates: new list_tags is servable", "list_tags" in names, names)
    check("candidates: proactive_refresh excluded (enable_serve:false)",
          "proactive_refresh" not in names, names)
    check("candidates: proactive_refresh_cron excluded (cron)",
          "proactive_refresh_cron" not in names, names)
    check("candidates: legacy job name 'proactive' is gone", "proactive" not in names, names)

    flat_groups = {job for _group, jobs in main.EXPOSE_JOB_GROUPS for job in jobs}
    check("groups: legacy 'proactive' not referenced in any group", "proactive" not in flat_groups)
    check("groups: proactive_read under 自动记忆",
          any(g == "自动记忆" and "proactive_read" in jobs for g, jobs in main.EXPOSE_JOB_GROUPS))
    check("groups: list_tags under 检索与浏览",
          any(g == "检索与浏览" and "list_tags" in jobs for g, jobs in main.EXPOSE_JOB_GROUPS))

    rows = dict(main.expose_job_rows())
    check("ui rows: list_tags actually shown in 检索与浏览", "list_tags" in rows.get("检索与浏览", ()), rows)
    check("ui rows: proactive_read actually shown in 自动记忆", "proactive_read" in rows.get("自动记忆", ()), rows)

    check("labels: list_tags has a label", "list_tags" in main.EXPOSE_JOB_LABELS,
          sorted(main.EXPOSE_JOB_LABELS))
    check("labels: proactive_read label exists (renamed key)", "proactive_read" in main.EXPOSE_JOB_LABELS)

    info = main.EXPOSE_JOB_INFO.get("list_tags")
    check("info: list_tags has tier + description",
          bool(info) and len(info) == 2 and info[0] in main.EXPOSE_TIER_ORDER, info)
    check("info: proactive_read keeps tier + description",
          bool(main.EXPOSE_JOB_INFO.get("proactive_read")))
    check("info: no orphan 'proactive' entry", "proactive" not in main.EXPOSE_JOB_INFO)

    removals_off = main.custom_job_removals({"proactive_read": False})
    check("removals: disabling proactive_read removes the RENAMED job",
          "proactive_read" in removals_off and "proactive" not in removals_off, removals_off)
    removals_on = main.custom_job_removals({"proactive_read": True})
    check("removals: enabling proactive_read removes nothing of it",
          "proactive_read" not in removals_on and "proactive" not in removals_on, removals_on)
finally:
    main.official_jobs = _saved_official

# ---------- 真安装表（如果本机装了 ReMe）：只能做弱断言 ----------
_real = main.official_jobs()
if _real:
    real_servable = main.servable_job_names()
    for name in ("proactive_refresh", "proactive_refresh_cron"):
        if name in _real:
            check("real default.yaml: %s excluded from candidates" % name,
                  name not in real_servable, sorted(real_servable))
    if "list_tags" in _real:
        check("real default.yaml: list_tags is a candidate",
              "list_tags" in real_servable, sorted(real_servable))
else:
    print("  ok   real default.yaml unavailable (no local ReMe install) - synthetic checks above", flush=True)

print("EXPOSE JOBS TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
