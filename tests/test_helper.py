"""Focused checks for mode generation and tunnel command construction."""
from pathlib import Path
import tempfile

import yaml

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402
import test_baseline


# 整套测试必须自包含，理由见 test_baseline 模块。快照放在钉死之后：下面 finally
# 会把 CFG 还原到这个确定性基线，末尾那句 `main.CFG["mode"] == original["mode"]`
# （验证测试没漏改模式）才有意义。
test_baseline.pin_clean_baseline()
original = main.deep_copy(main.CFG)
try:
    with tempfile.TemporaryDirectory(prefix="reme-helper-test-") as temp:
        # 显式固定能力集再断言。下面几条断言描述的是「auto_memory 开 / CC 关 / 资料关 /
        # dream 开 / chat 关 / embedding 关」这一种组合的生成结果；不能依赖本机那份
        # config.json 恰好是那个形状——它住在用户数据目录里（见 seed_config），
        # 用户正常改一次设置就会把构建打挂。
        main.CFG["custom"].update(
            auto_memory=True, auto_memory_cc=False, auto_resource=False, auto_dream=True,
            proactive_read=True, chat=False, embedding=False, faiss=False, studio=True, mcp=True,
        )
        first = Path(temp) / "custom-default.yaml"
        main.generate_custom_config(first)
        config = yaml.safe_load(first.read_text(encoding="utf-8"))
        assert "auto_memory" in config["jobs"]
        assert "auto_memory_cc" not in config["jobs"]
        assert "resource_watch_loop" not in config["jobs"]
        assert "dream_cron" in config["jobs"]
        assert "chat" not in config["jobs"]
        assert config["service"]["mcp_enabled"] is True
        assert config["components"]["file_store"]["default"]["embedding_store"] == ""

        main.CFG["custom"].update(
            auto_memory=False,
            auto_memory_cc=False,
            auto_resource=False,
            auto_dream=False,
            proactive_read=False,
            chat=False,
            embedding=True,
            faiss=True,
            studio=False,
            mcp=True,
        )
        second = Path(temp) / "custom-vector.yaml"
        main.generate_custom_config(second)
        config = yaml.safe_load(second.read_text(encoding="utf-8"))
        assert "as_llm" not in config["components"]
        assert "agent_wrapper" not in config["components"]
        assert config["components"]["file_store"]["default"]["backend"] == "faiss"
        assert config["components"]["file_store"]["default"]["embedding_store"] == "default"
        assert config["service"]["web_enabled"] is False

        # v1.0.1: LLM 参数 / dream 闸门 / service.jobs 允许列表注入
        main.CFG["custom"].update(
            auto_memory=True, auto_memory_cc=False, auto_resource=False, auto_dream=True,
            proactive_read=False, chat=False, embedding=False, faiss=False, studio=True, mcp=True,
        )
        main.CFG["llm"].update(
            base_url="http://127.0.0.1:10100/v1", model="deepseek/deepseek-flash",
            max_tokens=32768, thinking_enable=False, reasoning_effort="low",
        )
        main.CFG["pipeline"].update(scan_days=3, max_units=4, dream_cron="30 2 * * *")
        main.CFG["expose"].update(custom=True, jobs=["search", "read", "write", "edit"])
        third = Path(temp) / "custom-tuned.yaml"
        main.generate_custom_config(third)
        config = yaml.safe_load(third.read_text(encoding="utf-8"))
        parameters = config["components"]["as_llm"]["default"]["parameters"]
        assert parameters["max_tokens"] == 32768
        assert parameters["thinking_enable"] is False
        assert parameters["reasoning_effort"] == "low"
        assert config["jobs"]["dream_cron"]["cron"] == "30 2 * * *"
        assert config["jobs"]["dream_cron"]["steps"][0]["scan_days"] == 3
        assert config["jobs"]["dream_cron"]["steps"][0]["max_units"] == 4
        assert config["jobs"]["auto_dream"]["steps"][0]["scan_days"] == 3
        assert config["service"]["jobs"] == ["search", "read", "write", "edit"]

        main.CFG["expose"]["custom"] = False
        main.CFG["pipeline"]["dream_cron"] = "not a cron"
        fourth = Path(temp) / "custom-cron-fallback.yaml"
        main.generate_custom_config(fourth)
        config = yaml.safe_load(fourth.read_text(encoding="utf-8"))
        assert config["jobs"]["dream_cron"]["cron"] == "0 23 * * *"
        assert "jobs" not in config["service"]

        # v1.0.1: .env 原地更新不产生重复键，且可回滚
        env_root = Path(temp) / "envtest"
        env_root.mkdir(parents=True, exist_ok=True)
        saved_root = main.CFG["reme_root"]
        try:
            main.CFG["reme_root"] = str(env_root)
            main.write_env_values({"LLM_BASE_URL": "http://127.0.0.1:10100/v1", "LLM_MODEL_NAME": "model-a"})
            main.write_env_values({"LLM_MODEL_NAME": "model-b"})
            text = main.env_file_text()
            assert "LLM_BASE_URL=http://127.0.0.1:10100/v1" in text
            assert "LLM_MODEL_NAME=model-b" in text
            assert text.count("LLM_MODEL_NAME") == 1
            main.write_env_text("")
            assert main.env_file_text() == ""
        finally:
            main.CFG["reme_root"] = saved_root

        # 状态轮询只接受菜单提供的六档；新装默认 5 分钟，非法旧值也回到 5 分钟。
        saved_config_path = main.CONFIG_PATH
        try:
            probe_config = Path(temp) / "probe-config.json"
            main.CONFIG_PATH = probe_config
            probe_config.write_text("{}", encoding="utf-8")
            assert main.load_config()["probe_interval_sec"] == 300
            probe_config.write_text('{"probe_interval_sec": 7}', encoding="utf-8")
            assert main.load_config()["probe_interval_sec"] == 300
            probe_config.write_text('{"probe_interval_sec": 20}', encoding="utf-8")
            assert main.load_config()["probe_interval_sec"] == 300, "旧版硬编码20秒应迁移到新默认5分钟"
            probe_config.write_text(
                '{"probe_interval_sec": 20, "probe_interval_user_set": true}', encoding="utf-8")
            assert main.load_config()["probe_interval_sec"] == 20, "用户主动选择的20秒必须保留"
        finally:
            main.CONFIG_PATH = saved_config_path

    target = main.CFG["targets"][0]
    command = main.ssh_command(target)
    mapping = f"127.0.0.1:{target['remote_port']}:127.0.0.1:2333"
    assert "-R" in command and mapping in command
    assert main.reme_python().name == "python.exe"

    second_target = {
        "name": "Ubuntu备用", "user": "tester", "host": "vm-alias", "port": 2222,
        "key": "", "remote_port": 22334, "enabled": False,
    }
    main.validate_targets([target, second_target])
    try:
        duplicate = main.deep_copy(second_target)
        main.validate_targets([second_target, duplicate])
        raise AssertionError("duplicate target was accepted")
    except ValueError:
        pass
    main.CFG["targets"] = [target, second_target]
    targets_menu = main.build_targets_menu()
    assert len(targets_menu.items) >= 6
    assert "Ubuntu备用" in str(targets_menu.items[1].text)

    ok, detail = main.validate_install("minimal")
    assert ok, detail
    assert "ReMe " in detail
    assert main.CFG["mode"] == original["mode"]

    main.set_state(healthy=False)
    old_probe = main.probe_health
    main.probe_health = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("tray menu blocked on HTTP"))
    try:
        menu = main.build_menu()
        for item in menu.items:
            if isinstance(item, main.pystray.MenuItem):
                str(item.text)
                bool(item.enabled)
                item.checked
        assert main.service_is_healthy() is False
    finally:
        main.probe_health = old_probe
finally:
    main.CFG.clear()
    main.CFG.update(original)

print("reme-helper focused tests: PASS")


# ---------------- 设置窗口状态逻辑：模式 × 能力 × 基线 的组合矩阵 ----------------
def _draft(mode):
    cfg = main.deep_copy(main.CFG)
    cfg["mode"] = mode
    draft = main.settings_new_draft(cfg, str(main.reme_root()))
    main.settings_load_mode(draft, mode, cfg, str(main.reme_root()), mode)
    # 与真实窗口一致：固定预设下窗口显示的是预设的能力集与预设参数（collect_widgets 会写回草稿）
    main.settings_materialize_display(draft)
    return cfg, draft


def _edit(cfg, draft, section, key, value):
    # 模拟界面：每次改动前先把“窗口当前显示的值”收进草稿
    main.settings_materialize_display(draft)
    return main.settings_apply_edit(draft, section, key, value, cfg)


# 1) 预设模式：显示值来自预设，且“回到基线”必须全部不可用
for mode in ("minimal", "full"):
    cfg, draft = _draft(mode)
    feats = main.settings_display_features(draft)
    if mode == "minimal":
        assert feats["auto_memory"] is False and feats["auto_dream"] is False
        assert feats["embedding"] is False and feats["faiss"] is False
        assert feats["studio"] is True and feats["mcp"] is True
    else:
        assert feats == main.FULL_FEATURES
    assert draft["baseline"] == mode, f"{mode} 的基线应是自身"
    assert main.settings_resettable(draft, cfg) == set(), f"{mode} 预设下不应有可回到基线的项"
    assert main.settings_changed_items(draft, cfg, str(main.reme_root()), mode, cfg["targets"]) == []

# 2) 门控矩阵：预设与自定义下的能力开关
cfg, minimal = _draft("minimal")
gate = main.settings_gating(minimal, service_up=True, llm_ready=True)
assert gate["model_features"] is False
assert gate["embedding_fields"] is False and gate["dream_fields"] is False
assert gate["dream_button"] is False, "基础模式没有 auto_dream，按钮必须禁用"
assert gate["reindex_button"] is True, "重建索引只需要服务运行中"
assert gate["reindex_scopes"] == ["all", "bm25"]
assert all(gate["job_enabled"][job] for job in main.MINIMAL_JOBS)
assert not gate["job_enabled"]["auto_dream"] and not gate["job_enabled"]["auto_memory"]

cfg, full = _draft("full")
gate = main.settings_gating(full, service_up=True, llm_ready=True)
assert gate["model_features"] is True and gate["dream_fields"] is True
assert gate["dream_button"] is True and gate["embedding_fields"] is False
assert all(gate["job_enabled"].values()), "全功能预设下所有 job 都应可用"
assert main.settings_gating(full, service_up=False, llm_ready=True)["dream_button"] is False
assert main.settings_gating(full, service_up=True, llm_ready=False)["dream_button"] is False

# 3a) 能力项矩阵：预设下改「能力项」→ 转自定义、只改这一项、基线仍是该预设
for mode in ("minimal", "full"):
    baseline = main.preset_features(mode)
    # 每项都取“与预设不同”的值，否则草稿会正好等于预设而被自动折叠
    capability_edits = (
        ("feature", "auto_memory", not baseline["auto_memory"]),
        ("feature", "auto_dream", not baseline["auto_dream"]),
    )
    for section, key, value in capability_edits:
        cfg, draft = _draft(mode)
        degraded, collapsed = _edit(cfg, draft, section, key, value)
        assert degraded is True and draft["mode"] == "custom", f"{mode}+{section}.{key} 应降级为自定义"
        assert collapsed is None, f"{mode}+{section}.{key} 不应被折叠"
        assert draft["baseline"] == mode, f"{mode}+{section}.{key} 的基线应保持 {mode}"
        assert draft["features"][key] is value
        for feat_key, expected in baseline.items():
            if feat_key == key:
                continue
            assert draft["features"][feat_key] is expected, f"{mode}+{section}.{key} 不应改动 {feat_key}"
        assert main.settings_resettable(draft, cfg), "产生差异后应有可回到基线的项"

# 3b) 公共设置矩阵：预设下改「参数/凭据/整理参数/MCP 允许列表」→ **模式不变**
#     （地址、模型、Key、token 预算、思考强度、Embedding 维度、整理参数都是公共设置，
#       在哪个模式下都成立；曾经它们会把用户从预设里踢出去，那是个 bug）
for mode in ("minimal", "full"):
    # (section, key, value, 是否应出现"回到基线")
    # 凭据类（base_url / model / key）按设计永不重置：它们属于账号，不属于模式。
    shared_edits = (
        ("llm", "reasoning_effort", "high", True),
        ("llm", "max_tokens", 8192, True),
        ("llm", "thinking_enable", True, True),
        ("llm", "base_url", "http://127.0.0.1:20200/v1", False),
        ("llm", "model", "example/model-x", False),
        ("embedding", "dimensions", 1536, True),
        ("pipeline", "scan_days", 7, True),
        ("pipeline", "max_units", 10, True),
        ("expose", "custom", True, True),
    )
    for section, key, value, resettable in shared_edits:
        cfg, draft = _draft(mode)
        degraded, collapsed = _edit(cfg, draft, section, key, value)
        assert degraded is False, f"{mode}+{section}.{key} 不应改变模式"
        assert collapsed is None, f"{mode}+{section}.{key} 不应折叠"
        assert draft["mode"] == mode, f"{mode}+{section}.{key} 后模式应仍是 {mode}"
        assert draft["baseline"] == mode, f"{mode}+{section}.{key} 后基线应仍是 {mode}"
        if section == "expose":
            assert draft["expose"]["custom"] is True
        else:
            assert draft[section][key] == value, f"{mode}+{section}.{key} 的值应写进草稿"
        assert draft["features"] == main.preset_features(mode), "公共设置不该动能力集合"
        names = main.settings_resettable(draft, cfg)
        if resettable:
            assert names, f"{mode}+{section}.{key} 有差异时应能回到基线"
        else:
            assert not names, f"{mode}+{section}.{key} 是凭据，不该提供回到基线：{names}"
        changed = main.settings_changed_items(draft, cfg, str(main.reme_root()), mode, cfg["targets"])
        assert changed, f"{mode}+{section}.{key} 应出现在待保存改动里"
        assert "模式" not in changed, f"{mode}+{section}.{key} 不该把模式算成改动：{changed}"

# 4) 基线语义：从基础模式降级后，“回到基线”回到基础模式的值（而不是官方默认全开）
cfg, draft = _draft("minimal")
_edit(cfg, draft, "feature", "auto_memory", True)      # 打开一项
_edit(cfg, draft, "pipeline", "max_units", 10)         # 改管道
assert draft["baseline"] == "minimal"
names = main.settings_resettable(draft, cfg)
assert {"feature:auto_memory", "pipeline"} <= names, names
main.settings_reset_feature(draft, "auto_memory", cfg)
assert draft["features"]["auto_memory"] is False, "应回到基础模式的值（关闭），而不是官方默认（开启）"
main.settings_reset_section(draft, "pipeline", cfg)
assert draft["pipeline"] == main.PRESET_PIPELINE

# 5) 折叠：草稿与某个预设完全一致 → 模式自动切换为该预设（模式是推导出来的）
cfg, draft = _draft("minimal")
_edit(cfg, draft, "feature", "auto_memory", True)
assert draft["mode"] == "custom"
degraded, collapsed = _edit(cfg, draft, "feature", "auto_memory", False)
assert degraded is False and collapsed == "minimal", (degraded, collapsed)
assert draft["mode"] == "minimal" and draft["baseline"] == "minimal"

cfg, draft = _draft("minimal")
_edit(cfg, draft, "feature", "auto_memory", True)
main.settings_reset_all(draft, cfg)
assert main.settings_collapse_mode(draft) == "minimal", "全部回到基础模式的值后应折叠为基础模式"
assert draft["mode"] == "minimal"

cfg, draft = _draft("minimal")
_edit(cfg, draft, "feature", "embedding", True)          # 打开 Embedding → 与全功能预设不同
assert draft["mode"] == "custom"
_edit(cfg, draft, "feature", "embedding", False)         # 再关回去 → 精确等于基础模式
assert draft["mode"] == "minimal", draft["mode"]

cfg, draft = _draft("custom")
draft["features"] = dict(main.FULL_FEATURES)             # 自定义草稿与全功能一致
assert main.settings_collapse_mode(draft) == "full"
assert draft["mode"] == "full"

# 6) 公共设置与预设不同，也不能阻止折叠：模式只看能力集合
cfg, draft = _draft("minimal")
_edit(cfg, draft, "llm", "max_tokens", 8192)             # 参数改了，但还是基础模式的能力集合
_edit(cfg, draft, "llm", "reasoning_effort", "high")
assert draft["mode"] == "minimal", draft["mode"]
assert main.settings_collapse_mode(draft) is None, "已经是预设，无需折叠"
cfg, draft = _draft("minimal")
_edit(cfg, draft, "feature", "auto_memory", True)        # 离开预设
_edit(cfg, draft, "llm", "max_tokens", 8192)             # 顺手调个参数
_edit(cfg, draft, "feature", "auto_memory", False)       # 能力项改回来
assert draft["mode"] == "minimal", f"参数不同也应折叠回预设，实际={draft['mode']}"

# 6) 差异统计：预设值不等于官方默认时，也不算“未保存改动”
cfg, draft = _draft("minimal")
assert main.settings_changed_items(draft, cfg, str(main.reme_root()), "minimal", cfg["targets"]) == []
_edit(cfg, draft, "feature", "auto_memory", True)
items = main.settings_changed_items(draft, cfg, str(main.reme_root()), "minimal", cfg["targets"])
assert "模式" in items, items

# 7) 模式切换只换能力集：用户填的端点/模型/参数一律保留
cfg, draft = _draft("minimal")
draft["llm"].update(base_url="http://127.0.0.1:10100/v1", model="deepseek/deepseek-flash", max_tokens=8192)
draft["embedding"].update(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                          model="text-embedding-v4", dimensions=1024)
draft["pipeline"]["scan_days"] = 7
assert main.settings_load_mode(draft, "full", cfg, str(main.reme_root()), "minimal") is True
assert draft["features"] == main.FULL_FEATURES, "切到全功能：能力集应变成全功能"
assert draft["llm"]["base_url"] == "http://127.0.0.1:10100/v1" and draft["llm"]["model"] == "deepseek/deepseek-flash"
assert draft["embedding"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
assert draft["pipeline"]["scan_days"] == 7, "填过的参数也应保留"
assert draft["llm"]["max_tokens"] == 8192
assert main.settings_load_mode(draft, "custom", cfg, str(main.reme_root()), "minimal") is True
assert draft["llm"]["base_url"] == "http://127.0.0.1:10100/v1", "切到自定义同样保留"
assert draft["features"] == cfg["custom"], "自定义 = 磁盘上那份能力集"

# 8) 点击“当前已选模式”必须什么都不做
cfg, draft = _draft("full")
before = main.deep_copy(draft)
assert main.settings_load_mode(draft, "full", cfg, str(main.reme_root()), "full") is False
assert draft == before

# 9) 切到“另一个”预设：只报模式 + 能力集差异，不牵动端点/参数
cfg, draft = _draft("minimal")
main.settings_load_mode(draft, "full", cfg, str(main.reme_root()), "minimal")
items = main.settings_changed_items(draft, cfg, str(main.reme_root()), "minimal", cfg["targets"])
# 待保存的能力项 = 「将要写入的（全功能预设）」与「当前生效的（保存下来的基础模式预设）」之差；
# 拿保存下来的 custom 集合比是错的：固定预设下那份集合并不生效。
expected = {"模式"} | {main.FEATURES[key]["name"] for key in main.FEATURES
                       if bool(main.FULL_FEATURES[key]) != bool(main.MINIMAL_FEATURES[key])}
assert set(items) == expected, (items, expected)
assert not any(item in items for item in ("LLM 参数", "Embedding", "记忆管道", "MCP 暴露")), items

# 10) 关掉 Embedding 时必须同时关掉 FAISS（编辑路径，不只是恢复路径）
cfg, draft = _draft("full")
_edit(cfg, draft, "feature", "embedding", True)
_edit(cfg, draft, "feature", "faiss", True)
_edit(cfg, draft, "feature", "embedding", False)
assert draft["features"]["faiss"] is False, "关 Embedding 后 FAISS 必须自动关闭"

# 11) 基线是“已保存配置”时，恢复 = 放弃改动；凭据永不参与恢复
cfg, draft = _draft("custom")
assert draft["baseline"] == main.BASELINE_SAVED
draft["llm"].update(base_url="http://mine/v1", model="my-model", max_tokens=8192)
draft["embedding"].update(base_url="https://mine/v1")
main.settings_reset_all(draft, cfg)
assert draft["features"] == cfg["custom"] and draft["pipeline"] == cfg["pipeline"]
assert draft["llm"]["base_url"] == "http://mine/v1" and draft["llm"]["model"] == "my-model", "端点与模型必须保留"
assert draft["embedding"]["base_url"] == "https://mine/v1", "Embedding 端点必须保留"
assert draft["llm"]["max_tokens"] == main.PRESET_LLM["max_tokens"], "调参应回到默认"
main.settings_reset_section(draft, "llm", cfg)
assert draft["llm"]["base_url"] == "http://mine/v1", "区块恢复也不动端点"

# 12) 缺失变量按精确名字报告（不再用“和/或”含糊表述）
assert main.missing_env_names({}, "llm") == ["LLM_BASE_URL", "LLM_API_KEY"]
assert main.missing_env_names({"LLM_BASE_URL": "http://127.0.0.1:10100/v1"}, "llm") == ["LLM_API_KEY"]
assert main.missing_env_names({"LLM_BASE_URL": "x", "LLM_API_KEY": "y"}, "llm") == []
assert main.missing_env_names({"EMBEDDING_BASE_URL": "  ", "EMBEDDING_API_KEY": "k"}, "embedding") == ["EMBEDDING_BASE_URL"]
assert main.missing_env_text({"LLM_BASE_URL": "x"}, "llm") == "LLM_API_KEY"
assert main.missing_env_text({"LLM_BASE_URL": "x", "LLM_API_KEY": "y"}, "llm") == "（无）"
assert main.missing_env_text({"EMBEDDING_API_KEY": "k"}, "embedding") == "EMBEDDING_BASE_URL"

# 13) ReMe 安装探测与 .env 回填
import tempfile as _tempfile  # noqa: E402

with _tempfile.TemporaryDirectory() as temp:
    fake = main.Path(temp)
    assert main.looks_like_reme_install(fake) is False, "空目录不算安装"
    assert main.looks_like_reme_install(main.Path("Z:/definitely/missing")) is False
    (fake / "venv" / "Scripts").mkdir(parents=True)
    (fake / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    assert main.looks_like_reme_install(fake) is False, "只有 python 还不算（缺 reme）"
    (fake / "venv" / "Scripts" / "reme.exe").write_bytes(b"")
    assert main.looks_like_reme_install(fake) is True, "python + reme 才算安装"
    (fake / "venv" / "Scripts" / "reme.exe").unlink()
    (fake / "venv" / "Lib" / "site-packages" / "reme").mkdir(parents=True)
    assert main.looks_like_reme_install(fake) is True, "python + reme 包也算安装"

# 扫描返回的是**解析后**的路径（scan_reme_installations 里 resolve 过），所以这里也
# 按解析后的路径比较：根目录本身可能是个映射盘或链接（CI 用 subst 造出 H:\Tools\ReMe，
# 解析回来就是它的真实目标），按字符串比会假红。
found = [Path(path).resolve() for path in main.scan_reme_installations()]
assert main.reme_root().resolve() in found, found  # 本机已安装，扫描必须能找到

draft = {"llm": {"base_url": "http://kept/v1", "model": ""},
         "embedding": {"base_url": "", "model": "text-embedding-v4"}}
merged = main.merge_env_defaults(draft, {"LLM_BASE_URL": "http://env/v1", "LLM_MODEL_NAME": "env-model",
                                            "EMBEDDING_BASE_URL": "http://env-emb/v1",
                                            "EMBEDDING_MODEL_NAME": ""})
assert merged["filled"] == ["llm.model", "embedding.base_url"], merged
assert merged["corrected"] == ["llm.base_url"], merged
# ReMe 真正读的是 .env：保存值为空要补，与 .env 不同要按 .env 校正（否则界面与生效值不一致）
assert draft["llm"]["base_url"] == "http://env/v1", draft["llm"]
assert draft["llm"]["model"] == "env-model"
assert draft["embedding"]["base_url"] == "http://env-emb/v1"
assert draft["embedding"]["model"] == "text-embedding-v4", "空值不能覆盖已有值"

prompt = main.reme_install_prompt(r"D:\X\ReMe")
for needle in ('reme-ai[core]', "service.backend=http", "2333", r"D:\X\ReMe", "health_check"):
    assert needle in prompt, needle

# 16) 从日志解析“上次整理结果”
with _tempfile.TemporaryDirectory() as temp:
    log_dir = main.Path(temp)
    (log_dir / "reme-20260101.log").write_text(
        "2026-01-01 23:00:01 | INFO | extract.py:49 | execute | [DreamExtractStep] start date=2026-01-01 "
        "dates=2025-12-31,2026-01-01 scan_days=2 max_units=5 hint=False\n"
        "2026-01-01 23:00:02 | INFO | extract.py:76 | execute | [DreamExtractStep] scan summary existing=6 indexed=6 "
        "changed=2 unchanged=4 deleted=0\n"
        "2026-01-01 23:00:20 | INFO | integrate.py:239 | _finish | [DreamIntegrateStep] "
        "finish success=True integrated=3 failed=0\n"
        "2026-01-01 23:00:21 | INFO | finish.py:55 | execute | [DreamFinishStep] "
        "finish success=True checkpointed=2 failed_units=0 errors=0\n",
        encoding="utf-8",
    )
    original_log_dir = main.reme_log_dir
    main.reme_log_dir = lambda: log_dir
    ok, detail = main.last_dream_summary()
    assert ok, detail
    assert "2026-01-01 23:00:21" in detail, detail
    assert "写入 3 个节点" in detail and "扫描 6 个文件" in detail and "2 个有变化" in detail, detail
    (log_dir / "reme-20260102.log").write_text(
        "2026-01-02 23:00:01 | INFO | extract.py:49 | execute | [DreamExtractStep] start date=2026-01-02 "
        "dates=2026-01-01,2026-01-02 scan_days=2 max_units=5 hint=False\n"
        "2026-01-02 23:00:02 | INFO | extract.py:103 | execute | [DreamExtractStep] "
        "skip no changed input dates=2026-01-01,2026-01-02\n"
        "2026-01-02 23:00:03 | INFO | finish.py:55 | execute | [DreamFinishStep] "
        "finish success=True checkpointed=0 failed_units=0 errors=0\n",
        encoding="utf-8",
    )
    ok, detail = main.last_dream_summary()
    assert ok and "跳过" in detail and "2026-01-02" in detail, detail
    (log_dir / "reme-20260103.log").write_text(
        "2026-01-03 23:00:01 | INFO | extract.py:49 | execute | [DreamExtractStep] start date=2026-01-03 "
        "dates=2026-01-02,2026-01-03 scan_days=2 max_units=5 hint=False\n"
        "2026-01-03 23:00:02 | INFO | extract.py:76 | execute | [DreamExtractStep] scan summary existing=4 indexed=3 "
        "changed=1 unchanged=3 deleted=0\n"
        "2026-01-03 23:00:20 | INFO | integrate.py:239 | _finish | [DreamIntegrateStep] "
        "finish success=False integrated=2 failed=1\n"
        "2026-01-03 23:00:21 | INFO | finish.py:55 | execute | [DreamFinishStep] "
        "finish success=False checkpointed=0 failed_units=1 errors=1\n",
        encoding="utf-8",
    )
    ok, detail = main.last_dream_summary()
    assert ok is False and "整理失败" in detail and "已整合 2" in detail and "失败 1" in detail, detail
    main.reme_log_dir = lambda: log_dir / "missing"
    ok, detail = main.last_dream_summary()
    assert ok is False and "日志" in detail, detail
    main.reme_log_dir = original_log_dir

# 17) 测试探针用到的判定函数（不联网，纯计算）
assert abs(main.cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9
assert main.cosine_similarity([1, 0], [0, 1]) == 0.0
assert main.cosine_similarity([1, 0], [1, 0, 0]) == 0.0, "维度不同应返回 0"
assert main.cosine_similarity([], [1]) == 0.0
assert main.extract_json_object('{"ok": true}')["ok"] is True
assert main.extract_json_object('```json\n{"ok": true}\n```')["ok"] is True
assert main.extract_json_object('前缀 {"ok": true} 后缀')["ok"] is True
assert main.extract_json_object("没有 JSON") is None
assert main.extract_json_object("{不是合法 json") is None

# 15) 托盘文案：窗口叫“控制台”，只读提示指向同一个名字
menu_texts = []


def _walk_items(menu):
    """把菜单摊平成列表，分隔符用 None 表示。"""
    out = []
    for item in getattr(menu, "items", []):
        out.append(None if item is getattr(main.pystray.Menu, "SEPARATOR", None) else item)
        submenu = getattr(item, "submenu", None)
        if submenu is not None:
            out.extend(_walk_items(submenu))
    return out


def _menu_walk(menu):
    for item in getattr(menu, "items", []):
        text = getattr(item, "text", "") or ""
        if text:
            menu_texts.append(text)
        submenu = getattr(item, "submenu", None)
        if submenu is not None:
            _menu_walk(submenu)


_menu_walk(main.build_menu())
assert any("控制台" in text for text in menu_texts), menu_texts
assert any("打开 workspace" in text for text in menu_texts), menu_texts
assert any("打开指引" in text for text in menu_texts), menu_texts
assert any("状态刷新间隔" in text for text in menu_texts), menu_texts
# 「打开…」已经收敛：本地配置文件不再各占一个菜单项
for gone in ("打开ReMe目录", "打开官方default配置", "打开当前配置", "打开日志目录", "打开 .env（凭据）"):
    assert not any(gone in text for text in menu_texts), (gone, menu_texts)
# 分区与排序：至少 6 个分隔段，且安装提示只在缺 ReMe 时出现
separators = sum(1 for item in _walk_items(main.build_menu()) if item is None)
assert separators >= 6, separators
_install_items = [item for item in _walk_items(main.build_menu())
                  if item is not None and "复制安装提示词" in str(item.text)]
assert _install_items, "应当保留安装提示项"
assert bool(_install_items[0].visible) is (not main.reme_installed()), _install_items[0].visible

# 指引窗口把这些入口都收回来了
guide_paths = {str(item["path"]) for item in main.path_guide_items()}
assert len(guide_paths) >= 6, guide_paths
assert any(str(main.reme_root()) == path for path in guide_paths), guide_paths
assert not any("图形配置" in text for text in menu_texts), menu_texts
assert "控制台" in main.mode_text()
assert "图形配置" not in main.mode_text()

# 状态刷新菜单六档与 opencodex-helper 一致；保存后唤醒监控，让新间隔立即生效。
assert main.PROBE_INTERVAL_CHOICES == (
    (20, "20 秒"), (60, "1 分钟"), (300, "5 分钟"),
    (600, "10 分钟"), (1800, "30 分钟"), (3600, "1 小时"),
)
_saved_save_config = main.save_config
_saved_notify_interval = main.notify
_saved_interval = main.CFG.get("probe_interval_sec")
_saved_interval_mark = main.CFG.get("probe_interval_user_set")
_interval_messages = []
try:
    main.save_config = lambda: None
    main.notify = lambda message: _interval_messages.append(message)
    main.MONITOR_WAKE_EVENT.clear()
    main.set_probe_interval(300)
    assert main.CFG["probe_interval_sec"] == 300
    assert main.CFG["probe_interval_user_set"] is True
    assert main.MONITOR_WAKE_EVENT.is_set()
    assert _interval_messages == ["状态刷新间隔已设为 5 分钟"], _interval_messages
finally:
    main.save_config = _saved_save_config
    main.notify = _saved_notify_interval
    main.CFG["probe_interval_sec"] = _saved_interval
    main.CFG["probe_interval_user_set"] = _saved_interval_mark
    main.MONITOR_WAKE_EVENT.clear()

# 任务栏与托盘的16px小图都至少占14x14有效像素；任务栏另带20/40px原生帧。
_tray_16 = main.make_icon(True, False, 16)
_taskbar_16 = main.make_taskbar_icon(16)
_tray_box = _tray_16.getbbox()
_taskbar_box = _taskbar_16.getbbox()
assert _tray_box and _taskbar_box
assert (_tray_box[2] - _tray_box[0]) >= 14, _tray_box
assert (_taskbar_box[2] - _taskbar_box[0]) >= 14, _taskbar_box
assert 20 in main.TASKBAR_ICON_SIZES and 40 in main.TASKBAR_ICON_SIZES

# 交互启动后检查一次更新：发现新版才通知；已是最新与网络失败只写日志。
_saved_latest_release = main.helper_latest_release
_saved_update_notify = main.notify
_saved_update_state = dict(main.HELPER_UPDATE_STATE)
_update_messages = []
try:
    main.STOP_EVENT.clear()
    main.SHUTDOWN_STARTED.clear()
    main.notify = lambda message: _update_messages.append(message)
    main.helper_latest_release = lambda: {"tag": "v99.0.0", "zip": "x", "sha256": ""}
    main.startup_helper_update_check()
    assert len(_update_messages) == 1 and "v99.0.0" in _update_messages[0], _update_messages
    _update_messages.clear()
    main.helper_latest_release = lambda: {"tag": f"v{main.VERSION}", "zip": "x", "sha256": ""}
    main.startup_helper_update_check()
    assert not _update_messages, "已是最新时不应每次启动都弹通知"
finally:
    main.helper_latest_release = _saved_latest_release
    main.notify = _saved_update_notify
    main.HELPER_UPDATE_STATE.clear()
    main.HELPER_UPDATE_STATE.update(_saved_update_state)

# 16) 标题随语言切换（弹窗标题早就翻了，窗口标题/托盘提示以前没有）
_lang = main.CFG.get("ui_lang")
main.CFG["ui_lang"] = "zh"
assert main.app_title().startswith("ReMe 助手"), main.app_title()
main.CFG["ui_lang"] = "en"
assert main.app_title().startswith("ReMe Helper"), main.app_title()
assert "帮助" not in main.app_title(), main.app_title()
main.CFG["ui_lang"] = _lang

# 17) 托盘菜单：菜单正开着时绝不能重画（pystray 会 DestroyMenu，右键菜单就「突然失焦」）
class _FakeIcon:
    def __init__(self):
        self.menu = "old-menu"
        self.title = ""


_icon = _FakeIcon()
_saved_icon = main.TRAY_ICON
main.TRAY_ICON = _icon
_saved_probe = main.menu_is_open

main.menu_is_open = lambda: True          # 用户正开着菜单
main.refresh_tray_menu()
assert main.MENU_DIRTY["dirty"] is True, "菜单开着时应记为待重画"
assert main.TRAY_ICON.menu == "old-menu", "菜单开着时不该重画"

main.menu_is_open = lambda: False         # 菜单关掉之后补画
main.refresh_tray_menu()
assert main.MENU_DIRTY["dirty"] is False, main.MENU_DIRTY
assert main.TRAY_ICON.menu != "old-menu", "菜单关掉后应当重画"

main.menu_is_open = _saved_probe
main.TRAY_ICON = _saved_icon
main.MENU_DIRTY["dirty"] = False

# 18) 托盘“退出”不能在 pystray 的菜单回调线程内同步清理；无 Tk 根窗口也必须有兜底。
_saved_shutdown = main.shutdown_tray
_shutdown_called = main.threading.Event()
_shutdown_args = []
main.SHUTDOWN_STARTED.clear()


def _record_shutdown(icon, *, claimed=False):
    _shutdown_args.append((icon, claimed))
    _shutdown_called.set()


main.shutdown_tray = _record_shutdown
_quit_icon = object()
_quit_started = main.time.monotonic()
main.quit_app(_quit_icon, None)
assert main.time.monotonic() - _quit_started < 0.1, "托盘退出回调必须立即返回"
assert _shutdown_called.wait(1.0), "托盘退出应把清理交给后台线程"
assert _shutdown_args == [(_quit_icon, True)], _shutdown_args
main.shutdown_tray = _saved_shutdown
main.STOP_EVENT.clear()


class _FakeTimer:
    started = False
    daemon = False

    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback

    def start(self):
        self.started = True


class _StoppingIcon:
    stopped = False

    def stop(self):
        self.stopped = True


_saved_timer = main.threading.Timer
_saved_begin_shutdown = main.begin_shutdown
_saved_ui_root = main.UI_HOST.get("root")
_timer_box = {}


def _fake_timer(interval, callback):
    timer = _FakeTimer(interval, callback)
    _timer_box["timer"] = timer
    return timer


try:
    main.threading.Timer = _fake_timer
    main.begin_shutdown = lambda: None
    main.UI_HOST["root"] = None
    _stopping_icon = _StoppingIcon()
    main.shutdown_tray(_stopping_icon, claimed=True)
    assert _timer_box["timer"].started is True, "没有 Tk 根窗口也必须启动退出兜底"
    assert _timer_box["timer"].interval == main.SHUTDOWN_FORCE_TIMEOUT
    assert _timer_box["timer"].daemon is True
    assert _stopping_icon.stopped is True
finally:
    main.threading.Timer = _saved_timer
    main.begin_shutdown = _saved_begin_shutdown
    main.UI_HOST["root"] = _saved_ui_root
    main.SHUTDOWN_STARTED.clear()
    main.STOP_EVENT.clear()

# 已经在执行的启动动作可以晚于退出请求返回，但它的迟到结果不能再弹“启动成功”。
_saved_notify = main.notify
_notifications = []
_action_entered = main.threading.Event()
_action_release = main.threading.Event()


def _slow_start_action():
    _action_entered.set()
    _action_release.wait(1.0)
    return True, "ReMe 已启动（测试）"


try:
    main.notify = lambda message: _notifications.append(message)
    main.SHUTDOWN_STARTED.clear()
    main.STOP_EVENT.clear()
    main.run_action(_slow_start_action, refresh=False)
    assert _action_entered.wait(1.0), "测试启动动作没有进入执行"
    assert main.claim_shutdown() is True
    main.STOP_EVENT.set()
    _action_release.set()
    deadline = main.time.monotonic() + 1.0
    while main.ACTION_LOCK.locked() and main.time.monotonic() < deadline:
        main.time.sleep(0.01)
    assert not main.ACTION_LOCK.locked(), "退出前应等待活动动作释放锁"
    assert not _notifications, f"退出期间不应发送迟到的动作通知：{_notifications}"
    called = []
    main.run_action(lambda: called.append(True) or (True, "不应执行"), refresh=False)
    main.time.sleep(0.05)
    assert not called, "退出开始后不应接受新的动作"
finally:
    main.notify = _saved_notify
    main.SHUTDOWN_STARTED.clear()
    main.STOP_EVENT.clear()

# 退出取消信号要让启动健康等待立刻返回，不能继续等满原来的 35 秒。
_saved_probe_for_wait = main.probe_health
try:
    main.STOP_EVENT.set()
    main.probe_health = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("退出后不应继续健康探测"))
    started_at = main.time.monotonic()
    assert main.wait_for_health(True, 35) is False
    assert main.time.monotonic() - started_at < 0.1
finally:
    main.probe_health = _saved_probe_for_wait
    main.STOP_EVENT.clear()

# 18) Explorer 暂态拒绝 NIM_ADD 时要自愈；健康图标不做多余注册。
class _RetryIcon:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def _show(self):
        self.calls += 1
        result = next(self.results)
        main.TRAY_ADD_STATE.update(result=result, error=0 if result else -2147467259)


_saved_add_state = dict(main.TRAY_ADD_STATE)
_warnings = []
try:
    main.TRAY_ADD_STATE.update(result=False, error=-2147467259, attempts=1)
    _retry_icon = _RetryIcon([False, True])
    assert main.recover_tray_registration(
        _retry_icon, delays=(0, 0), wait=lambda _delay: False,
        warn=lambda error: _warnings.append(error)) is True
    assert _retry_icon.calls == 2, _retry_icon.calls
    assert not _warnings, _warnings

    main.TRAY_ADD_STATE.update(result=True, error=0, attempts=1)
    _healthy_icon = _RetryIcon([False])
    assert main.recover_tray_registration(
        _healthy_icon, delays=(0,), wait=lambda _delay: False,
        warn=lambda error: _warnings.append(error)) is True
    assert _healthy_icon.calls == 0, "健康图标不应重复 NIM_ADD"

    main.TRAY_ADD_STATE.update(result=False, error=-2147467259, attempts=1)
    _failed_icon = _RetryIcon([False, False, False])
    assert main.recover_tray_registration(
        _failed_icon, delays=(0, 0, 0), wait=lambda _delay: False,
        warn=lambda error: _warnings.append(error)) is False
    assert _warnings == [-2147467259], _warnings

    # 连失败到阈值后必须换身份重试：外壳拒绝 uID 身份的那段时间里 GUID 身份能注册成功。
    main.TRAY_IDENTITY["mode"] = "uid"
    main.TRAY_ADD_STATE.update(result=False, error=-2147467259, attempts=1)
    _switch_icon = _RetryIcon([False] * 6)
    assert main.recover_tray_registration(
        _switch_icon, delays=(0,) * 6, wait=lambda _delay: False,
        warn=lambda error: None) is False
    assert main.TRAY_IDENTITY["mode"] == "guid", main.TRAY_IDENTITY
    assert _switch_icon.calls == 6, _switch_icon.calls
    main.TRAY_IDENTITY["mode"] = "uid"
finally:
    main.TRAY_ADD_STATE.clear()
    main.TRAY_ADD_STATE.update(_saved_add_state)

# 19) 注册身份：pystray 传的 hID 被忽略（字段名是 uID），我们必须自己发非零 uID / GUID。
try:
    import pystray._win32 as _backend

    _sent = []
    _saved_notify = _backend.win32.Shell_NotifyIcon
    _backend.win32.Shell_NotifyIcon = lambda code, data: (_sent.append((code, data)), True)[1]
    try:
        main.TRAY_IDENTITY["mode"] = "uid"
        main.install_tray_identity()

        class _FakeIcon:
            _hwnd = 0x1234

        _backend.Icon._message(_FakeIcon(), 0, 0x01 | 0x02, uCallbackMessage=1, hIcon=0, szTip="x")
        assert _sent and _sent[-1][1].uID == main.TRAY_UID, _sent
        assert _sent[-1][1].uFlags & _backend.win32.NIF_GUID == 0, _sent[-1][1].uFlags

        main.TRAY_IDENTITY["mode"] = "guid"
        _backend.Icon._message(_FakeIcon(), 0, 0x01 | 0x02, uCallbackMessage=1, hIcon=0, szTip="x")
        assert _sent[-1][1].uFlags & _backend.win32.NIF_GUID, _sent[-1][1].uFlags
        assert _sent[-1][1].guidItem.Data1 == 0x0F0A6D2C, hex(_sent[-1][1].guidItem.Data1)
    finally:
        main.TRAY_IDENTITY["mode"] = "uid"
        _backend.win32.Shell_NotifyIcon = _saved_notify
except ImportError:      # 非 win32 平台没有这个后端，跳过
    pass

# 20) 注册失败提示每次进程只弹一次
_dialogs = []
_saved_dialog = main.ui_dialog
_saved_warned = dict(main.TRAY_WARNED)
try:
    main.ui_dialog = lambda title, text, buttons=None: _dialogs.append(title)
    main.TRAY_WARNED["done"] = False
    main.warn_tray_registration_failed(-2147467259)
    main.warn_tray_registration_failed(-2147467259)
    assert len(_dialogs) == 1, _dialogs
finally:
    main.ui_dialog = _saved_dialog
    main.TRAY_WARNED.clear()
    main.TRAY_WARNED.update(_saved_warned)

# ---------------------------------------------------------------------------
# 隧道自动重连的语义（不需要真实 VM：把 ssh 换成一个必然失败的命令即可）
#
# 这段守的是两个真实故障：
#   ① 启动时 ReMe 已经在跑 -> start_service 提前返回，挂在它后面的「启动隧道」根本
#      不执行，「ReMe启动后启动隧道」等于失效，用户得自己去托盘点一次；
#   ② ssh 进程中途消失 -> 旧实现只看状态，隧道断了就一直断着。
# ---------------------------------------------------------------------------
_fake_target = {"name": "T", "user": "u", "host": "10.255.255.1", "port": 22,
                "key": "", "remote_port": 22333, "enabled": True}
_fake_key = main.target_key(_fake_target)
_saved_targets = main.CFG["targets"]
_saved_tunnels_on = main.CFG.get("start_tunnels_with_reme")
_saved_up = main.service_up
_saved_probe = main.probe_health
_saved_tunnel_probe = main.probe_tunnel
_saved_command = main.ssh_command
_saved_tray_icon = main.TRAY_ICON
_saved_make_icon = main.make_icon
_saved_tunnel_notify = main.notify
_tunnel_events = []


class _TunnelIcon:
    visible = True
    icon = None


_tunnel_icon = _TunnelIcon()
main.TRAY_ICON = _tunnel_icon
# 托盘图现在统一走 tray_icon_image(running=, tunnels=, size=)：它内部再调 make_icon，
# 所以替身要接受同样的关键字参数。
main.make_icon = lambda running=True, tunnels=False, size=64: (running, tunnels)
main.notify = lambda message: _tunnel_events.append(message)
main.STATE["healthy"] = True

main.CFG["targets"] = [_fake_target]
main.ssh_command = lambda target, remote=None: ["cmd", "/c", "exit", "1"]   # 起不来，但会被尝试
main.service_up = lambda timeout=3.0: True                                  # 假装 ReMe 可用
# start_tunnel 里还有一道自己的健康检查（真的去问 127.0.0.1:2333），refresh_tunnels 那道
# service_up 管不着它：本机 ReMe 正在跑，以前这道"顺手"就过了；没有服务在跑的机器（CI）
# 会在 start_tunnel 里被「ReMe尚未运行」挡回去，第 4 条断言于是假红。一并假装它在跑。
main.probe_health = lambda *_args, **_kwargs: True

# 1. 打开「随 ReMe 启动隧道」时，启用的目标应被播种为「希望连着」
main.TUNNEL_WANTED.clear()
main.CFG["start_tunnels_with_reme"] = True
main.seed_tunnels_wanted()
assert main.TUNNEL_WANTED[_fake_key] is True, main.TUNNEL_WANTED

# 2. 关掉该选项时不应播种（尊重用户已经关掉的行为）
main.TUNNEL_WANTED.clear()
main.CFG["start_tunnels_with_reme"] = False
main.seed_tunnels_wanted()
assert main.TUNNEL_WANTED[_fake_key] is False, main.TUNNEL_WANTED

# 3. 用户手动停掉的隧道不会被健康检查自动拉起
main.TUNNEL_WANTED[_fake_key] = True
main.TUNNEL_PROCS.clear()
main.TUNNEL_STATE.clear()
main.TUNNEL_STATE[_fake_key] = True
main.stop_tunnel(_fake_target)
assert main.TUNNEL_WANTED[_fake_key] is False, "手动停止必须清掉期望标记"
assert _tunnel_icon.icon == (True, False), "主动停止返回前应立即移除托盘黄色点"
assert _tunnel_events[-1] == "T 隧道已断开", _tunnel_events
main.TUNNEL_STATE.clear()
main.refresh_tunnels()
assert main.TUNNEL_STATE[_fake_key] is False, "刚停掉的隧道不应被自动重连"

# 4. 主动启动发现隧道已经可用时，应在返回前立即显示黄色点
main.probe_tunnel = lambda _target: True
main.TUNNEL_STATE.clear()
_tunnel_icon.icon = None
ok, _detail = main.start_tunnel(_fake_target)
assert ok is True
assert _tunnel_icon.icon == (True, True), "主动启动成功后应立即显示托盘黄色点"
assert _tunnel_events[-1] == "T 隧道已连接", _tunnel_events

# 5. 句柄丢失但转发仍在：不许先报「已断开」再报「已连接」，也不许重复拉起 ssh
#    （以前 refresh_tunnels 先无条件写 False，于是每个轮询周期都成对刷两条气泡）
main.probe_tunnel = lambda _target: True
main.TUNNEL_PROCS.clear()
main.TUNNEL_WANTED[_fake_key] = True
main.TUNNEL_STATE[_fake_key] = True
_tunnel_events.clear()
main.refresh_tunnels()
assert main.TUNNEL_STATE[_fake_key] is True, "句柄为空但探测通过时应保持已连接"
assert _tunnel_events == [], f"隧道状态没变就不该发通知：{_tunnel_events}"
assert not main.TUNNEL_PROCS, "探测通过时不该新建 ssh 转发进程"

# 6. 期望连着的隧道掉线后会被重新尝试（尝试失败也无妨，关键是真去试了）
main.probe_tunnel = _saved_tunnel_probe
main.TUNNEL_WANTED[_fake_key] = True
started = []


def _recorded_command(target, remote=None):
    started.append(1)
    return ["cmd", "/c", "exit", "1"]


main.ssh_command = _recorded_command
main.TUNNEL_PROCS.clear()
main.TUNNEL_STATE.clear()
main.refresh_tunnels()
assert started, "期望连着的隧道掉线后应当被重新拉起"

# 7. 从未要求连接的目标不应被无谓地重试
main.TUNNEL_WANTED.clear()
started.clear()
main.TUNNEL_PROCS.clear()
main.TUNNEL_STATE.clear()
main.refresh_tunnels()
assert not started, "从未要求连接的隧道不该被自动拉起"

main.CFG["targets"] = _saved_targets
main.CFG["start_tunnels_with_reme"] = _saved_tunnels_on
main.service_up = _saved_up
main.probe_health = _saved_probe
main.probe_tunnel = _saved_tunnel_probe
main.ssh_command = _saved_command
main.TRAY_ICON = _saved_tray_icon
main.make_icon = _saved_make_icon
main.notify = _saved_tunnel_notify
main.TUNNEL_PROCS.clear()
main.TUNNEL_STATE.clear()
main.TUNNEL_WANTED.clear()

print("reme-helper settings matrix: PASS")
