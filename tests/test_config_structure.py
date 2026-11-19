# -*- coding: utf-8 -*-
"""生成配置 × 上游 default.yaml：结构等价 + 凭据防护 + 白名单规则。

上游来源：``tests/fixtures/reme-0.4.2.3-default.yaml``（上游 v0.4.2.3 raw 逐字快照，
sha256 9735026EB5AA126B482BEF21E91BCB24C01A0E17C85583814620231F3997600D）。
本机 venv 可能是 0.4.2.1（无 ``codex_app_server``、无 5 个新 job），故用 monkeypatch 把
官方表替换成夹具，使本测试在任意本机版本下都验证 0.4.2.3 的适配逻辑。

注意：本测试证明的是「生成逻辑跟随上游结构」；真机 0.4.2.3 下的端到端行为仍须 CI
（action.yml 装 0.4.2.3）或 Wave 3 之后复核。
"""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
from pathlib import Path

from conftest import TOOL  # noqa: F401  (puts src/ on sys.path)
import main  # noqa: E402
import yaml  # noqa: E402

FAILS = []
FIXTURE = TOOL / "tests" / "fixtures" / "reme-0.4.2.3-default.yaml"
FIXTURE_SHA256 = "9735026EB5AA126B482BEF21E91BCB24C01A0E17C85583814620231F3997600D"


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def official_config() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def install_official(config: dict) -> None:
    main.official_default_config = lambda: copy.deepcopy(config)
    main.official_jobs = lambda: copy.deepcopy(config.get("jobs") or {})


def generate(mode: str, selected: dict, env: dict, tmp: Path) -> dict:
    """在隔离的 CFG / env / expose 下生成一份配置并读回。"""
    main.CFG = {"mode": mode, "custom": selected, "llm": {}, "pipeline": {}, "embedding": {}}
    main.read_env_values = lambda: dict(env)
    main.expose_values = lambda: {"custom": False, "jobs": []}
    main.pipeline_values = lambda: dict(main.PRESET_PIPELINE)
    main.llm_values = lambda: {"base_url": "", "model": "", "max_tokens": 65536,
                               "thinking_enable": False, "reasoning_effort": ""}
    main.llm_backend_name = lambda: "openai"
    main.effort_options = lambda *a, **k: (["low", "high", "xhigh"], "", [])
    main.effort_is_allowed = lambda value, options: value in options
    target = tmp / (mode + "_" + str(len(list(tmp.iterdir()))) + ".yaml")
    main.generate_mode_config(mode, target)
    return yaml.safe_load(target.read_text(encoding="utf-8"))


def run() -> int:
    raw = FIXTURE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest().upper()
    check("fixture: sha256 matches the pinned upstream snapshot",
          digest == FIXTURE_SHA256, digest)

    config = official_config()
    upstream_jobs = set(config.get("jobs") or {})
    upstream_components = set(config.get("components") or {})
    check("fixture: 0.4.2.3 markers present",
          {"session_read", "session_status", "session_append", "job_status",
           "dashscope_search"} <= upstream_jobs, sorted(upstream_jobs))
    check("fixture: codex_app_server present",
          "codex_app_server" in upstream_components, sorted(upstream_components))

    saved_default = main.official_default_config
    saved_jobs = main.official_jobs
    try:
        install_official(config)
        minimal_features = main.preset_features("minimal")
        custom_features = dict(minimal_features)
        custom_features["auto_memory"] = True

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            gen_min = generate("minimal", minimal_features, {}, tmp)
            removals_min = main.custom_job_removals("minimal", minimal_features)
            check("minimal: jobs == upstream - removals",
                  set(gen_min.get("jobs") or {}) == upstream_jobs - removals_min,
                  sorted((upstream_jobs - removals_min) ^ set(gen_min.get("jobs") or {})))
            check("minimal: no session_* left (agent_wrapper popped)",
                  not ({"session_read", "session_status", "session_append"}
                       & set(gen_min.get("jobs") or {})),
                  sorted(gen_min.get("jobs") or {}))
            comp_min = set(gen_min.get("components") or {})
            check("minimal: as_llm / agent_wrapper / embedding removed",
                  not ({"as_llm", "agent_wrapper", "as_embedding", "embedding_store"} & comp_min),
                  sorted(comp_min))

            gen_c0 = generate("custom", minimal_features, {}, tmp)
            removals_c0 = main.custom_job_removals("custom", minimal_features)
            check("custom(no llm): jobs == upstream - removals",
                  set(gen_c0.get("jobs") or {}) == upstream_jobs - removals_c0,
                  sorted((upstream_jobs - removals_c0) ^ set(gen_c0.get("jobs") or {})))

            gen_c1 = generate("custom", custom_features, {}, tmp)
            comp_c1 = set(gen_c1.get("components") or {})
            check("custom(llm): keeps as_llm / agent_wrapper / codex_app_server",
                  {"as_llm", "agent_wrapper", "codex_app_server"} <= comp_c1, sorted(comp_c1))
            check("custom(llm): keeps session_* (agent_wrapper present)",
                  {"session_read", "session_status", "session_append"} <= set(gen_c1.get("jobs") or {}),
                  sorted(gen_c1.get("jobs") or {}))

            gen_full = generate("full", main.preset_features("full"), {}, tmp)
            check("full: extends default", gen_full.get("extends") == "default", gen_full.get("extends"))
            comp_full = gen_full.get("components") or {}
            check("full: carries as_llm / agent_wrapper / codex_app_server",
                  {"as_llm", "agent_wrapper", "codex_app_server"} <= set(comp_full), sorted(comp_full))
            jobs_full = gen_full.get("jobs") or {}
            check("full: override jobs include dream_cron / auto_dream",
                  {"dream_cron", "auto_dream"} <= set(jobs_full), sorted(jobs_full))
            check("full: dream_cron cron from pipeline settings",
                  (jobs_full.get("dream_cron") or {}).get("cron") == main.PRESET_PIPELINE["dream_cron"],
                  (jobs_full.get("dream_cron") or {}).get("cron"))
            auto_dream_steps = ((jobs_full.get("auto_dream") or {}).get("steps") or [])
            extract = [s for s in auto_dream_steps
                       if isinstance(s, dict) and s.get("backend") == "dream_extract_step"]
            check("full: auto_dream scan_days/max_units from pipeline settings",
                  bool(extract) and extract[0].get("scan_days") == main.PRESET_PIPELINE["scan_days"]
                  and extract[0].get("max_units") == main.PRESET_PIPELINE["max_units"],
                  extract[:1])

            numeric_env = {"CODEX_API_KEY": "123456", "CODEX_BASE_URL": "123456",
                           "DASHSCOPE_API_KEY": "123456", "CODEX_HOME": "123456"}
            gen_cred = generate("custom", custom_features, numeric_env, tmp)
            app_default = ((gen_cred.get("components") or {}).get("codex_app_server") or {}).get("default") or {}
            app_oauth = ((gen_cred.get("components") or {}).get("codex_app_server") or {}).get("oauth") or {}
            dash_key = (((gen_cred.get("jobs") or {}).get("dashscope_search") or {}).get("steps") or [{}])[0].get("api_key")
            check("credentials: codex_app_server.default api_key inlined (numeric)",
                  app_default.get("api_key") == "123456", app_default.get("api_key"))
            check("credentials: codex_app_server.default base_url inlined (numeric)",
                  app_default.get("base_url") == "123456", app_default.get("base_url"))
            check("credentials: codex_app_server.oauth codex_home inlined (numeric)",
                  app_oauth.get("codex_home") == "123456", app_oauth.get("codex_home"))
            check("credentials: dashscope_search api_key inlined (numeric)",
                  dash_key == "123456", dash_key)

            gen_empty = generate("custom", custom_features, {}, tmp)
            app_default_e = ((gen_empty.get("components") or {}).get("codex_app_server") or {}).get("default") or {}
            app_oauth_e = ((gen_empty.get("components") or {}).get("codex_app_server") or {}).get("oauth") or {}
            dash_key_e = (((gen_empty.get("jobs") or {}).get("dashscope_search") or {}).get("steps") or [{}])[0].get("api_key")
            check("credentials: empty env keeps ${...} placeholders",
                  app_default_e.get("api_key") == "${CODEX_API_KEY:-}"
                  and app_oauth_e.get("codex_home") == "${CODEX_HOME:-~/.codex}"
                  and dash_key_e == "${DASHSCOPE_API_KEY:-}",
                  (app_default_e.get("api_key"), app_oauth_e.get("codex_home"), dash_key_e))

            gen_full_cred = generate("full", main.preset_features("full"), numeric_env, tmp)
            full_default = ((gen_full_cred.get("components") or {}).get("codex_app_server") or {}).get("default") or {}
            full_oauth = ((gen_full_cred.get("components") or {}).get("codex_app_server") or {}).get("oauth") or {}
            full_dash_key = (((gen_full_cred.get("jobs") or {}).get("dashscope_search") or {}).get("steps") or [{}])[0].get("api_key")
            check("credentials: full also inlines codex_app_server.default api_key",
                  full_default.get("api_key") == "123456", full_default.get("api_key"))
            check("credentials: full also inlines codex_app_server.default base_url",
                  full_default.get("base_url") == "123456", full_default.get("base_url"))
            check("credentials: full also inlines codex_app_server.oauth codex_home",
                  full_oauth.get("codex_home") == "123456", full_oauth.get("codex_home"))
            check("credentials: full covers dashscope_search api_key (numeric)",
                  full_dash_key == "123456", full_dash_key)

            gen_full_empty = generate("full", main.preset_features("full"), {}, tmp)
            full_oauth_e = ((gen_full_empty.get("components") or {}).get("codex_app_server") or {}).get("oauth") or {}
            check("credentials: full keeps ${CODEX_HOME:-~/.codex} when unset",
                  full_oauth_e.get("codex_home") == "${CODEX_HOME:-~/.codex}", full_oauth_e.get("codex_home"))

        check("servable: enable_serve:false excluded",
              main.is_servable({"backend": "base", "enable_serve": False}) is False)
        check("servable: enabled:false excluded",
              main.is_servable({"backend": "base", "enabled": False}) is False)
        check("servable: enabled:[] excluded (empty list == 0)",
              main.is_servable({"backend": "base", "enabled": []}) is False)
        check("servable: background excluded", main.is_servable({"backend": "background"}) is False)
        check("servable: cron excluded", main.is_servable({"backend": "cron"}) is False)
        names = main.servable_job_names()
        check("servable: proactive_refresh (enable_serve:false) not exposed",
              "proactive_refresh" not in names, names)
        check("servable: proactive_refresh_cron not exposed",
              "proactive_refresh_cron" not in names, names)
        # 裁决（2026-11-18，Lead 采纳产品经理核实）：chat（backend=stream）不入 MCP 由**服务层**
        # 实现（http_service.py::add_job(): isinstance(job, StreamJob) → 只注册 HTTP SSE，不注册
        # MCP tool），与 0.4.2.1 一致，非新增；helper 不改 is_servable。helper 侧只断言
        # 「不自行排除 stream」；chat 不在 MCP 工具清单 + POST /chat 返回 SSE 需运行中的 0.4.2.3
        # 服务，本机 venv 0.4.2.1 无法验，留 CI / Wave 3 / 4 复核。
        check("helper: does not exclude stream by itself (service layer decides)",
              main.is_servable({"backend": "stream"}) is True)
        print("  note  chat 不入 MCP 工具清单 + POST /chat 返回 SSE：服务层 http_service.py 行为，"
              "需 0.4.2.3 运行环境，留 CI / Wave 3 / 4 复核", flush=True)
    finally:
        main.official_default_config = saved_default
        main.official_jobs = saved_jobs

    print("CONFIG STRUCTURE TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(run())
