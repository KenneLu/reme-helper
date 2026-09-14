"""End-to-end check of the settings window: drives the real widgets via the harness seam.

Checks the combinations that are easy to get wrong in the UI layer (which the pure-logic
matrix in test_helper.py cannot see): which controls are enabled in each mode, whether the
“恢复默认” links are offered while a fixed preset is selected, and what the footer reports.
"""
import sys
import time
import traceback

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402
import test_baseline  # noqa: E402

# 断言里「固定预设下不应有可回到基线的项」比对的是预设的公共参数；不钉死的话，
# 本机 config.json 里调过的 llm 参数会让它一直判定为可恢复。理由见 test_baseline。
test_baseline.pin_clean_baseline()

LOG_PATH = TOOL / "log" / "tests" / "settings-ui-test.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
results = []
finished = {"done": False, "failures": 0}
dialogs = {"warnings": [], "errors": [], "infos": [], "confirm": []}


class _DialogRecorder:
    """Collect dialogs instead of blocking the test run."""

    def __init__(self, sink, key):
        self.sink = sink
        self.key = key

    def __call__(self, *args, **kwargs):
        # messagebox.showX(title, message, ...) → 只记录正文，标题不参与断言
        text = " ".join(str(arg) for arg in args[1:])
        self.sink[self.key].append(text)
        return True


def patch_dialogs():
    main.messagebox.showwarning = _DialogRecorder(dialogs, "warnings")
    main.messagebox.showerror = _DialogRecorder(dialogs, "errors")
    main.messagebox.showinfo = _DialogRecorder(dialogs, "infos")

    def _no(*args, **kwargs):
        dialogs["confirm"].append(" ".join(str(arg) for arg in args[1:]))
        return False  # 一律选“否”，测试里不进入后续分支

    main.messagebox.askyesno = _no
    # 让“是否有 Key”只取决于输入框，测试才能确定性地覆盖“未填 Key”的分支
    main.read_env_values = lambda: {}
    main.save_config = lambda *a, **k: None   # 测试不写用户的 config.json
    main.last_dream_summary = lambda: (
        True,
        "上次整理：2026-01-01 23:00:21 · 写入 3 个节点（扫描 6 个文件、其中 2 个有变化）",
    )


def check(name, condition, detail=""):
    ok = bool(condition)
    results.append((name, ok, detail))
    if not ok:
        safe = str(detail).encode("gbk", "replace").decode("gbk")
        print(f"FAIL: {name}  {safe}", flush=True)


def build_steps(api):
    steps = []

    def step(fn):
        steps.append(fn)
        return fn

    @step
    def initial():
        state = api["ui_state"]()
        check("初始：保存按钮禁用", state["save_button"] == "disabled", state["save_button"])
        check("初始：放弃按钮禁用", state["footer"].startswith("没有未保存") or "待保存" not in state["footer"],
              state["footer"])
        links = {k: v for k, v in api["reset_links"]().items() if v is not None}
        check("初始：所有恢复链接禁用", links and not any(links.values()), str(links))
        check("初始：footer 无改动", "没有未保存的改动" in state["footer"], state["footer"])

    @step
    def preset_minimal():
        api["set_mode"]("minimal")
        state = api["ui_state"]()
        check("基础模式：状态条显示基础模式", state["chips"]["模式"] == "基础模式", state["chips"]["模式"])
        check("基础模式：Dream 控件禁用", set(state["dream_fields"]) == {"disabled"}, str(state["dream_fields"]))
        check("基础模式：Embedding 字段禁用", set(state["emb_fields"]) == {"disabled"}, str(state["emb_fields"]))
        check("基础模式：立即整理禁用", state["dream_button"] == "disabled", state["dream_button"])
        check("基础模式：基础 job 可用且 auto_* 禁用",
              state["jobs"]["search"] == "normal" and state["jobs"]["auto_dream"] == "disabled",
              str(state["jobs"]))
        links = {k: v for k, v in api["reset_links"]().items() if v is not None}
        check("基础模式：恢复链接全部禁用", not any(links.values()), str(links))
        check("基础模式：自定义功能为预设值（auto_dream 未勾）",
              api["display_features"]()["auto_dream"] is False, str(api["display_features"]()))
        check("基础模式：无可恢复项", api["resettable"]() == set(), str(api["resettable"]()))

    @step
    def switch_to_full():
        api["set_mode"]("full")
        feats = api["display_features"]()
        check("全功能模式：能力全开", feats["auto_memory"] and feats["auto_dream"] and feats["chat"], str(feats))
        state = api["ui_state"]()
        fields = state["dream_fields"][:-1]  # 末尾是“立即整理”按钮，受服务/LLM 状态影响
        check("全功能模式：Dream 输入控件启用", all(s in ("normal", "readonly") for s in fields), str(state["dream_fields"]))
        check("全功能模式：恢复链接仍禁用（固定预设）",
              not any(v for k, v in api["reset_links"]().items() if v is not None), str(api["reset_links"]()))
        check("全功能模式：待保存计数反映模式变更", state["chips"]["未保存改动"] != "0",
              state["chips"]["未保存改动"])
        check("全功能模式：状态条显示全功能模式", state["chips"]["模式"] == "全功能模式", state["chips"]["模式"])

    @step
    def shared_settings_keep_preset():
        """公共设置（参数/凭据）改了也不该离开预设——曾经在全功能模式下选个思考强度就变自定义。"""
        api["set_mode"]("full")
        api["edit"]("llm", "max_tokens", 8192)
        draft = api["draft"]()
        check("改参数：模式保持全功能", draft["mode"] == "full", draft["mode"])
        check("改参数：值确实写进草稿", draft["llm"]["max_tokens"] == 8192, str(draft["llm"]))
        api["edit"]("llm", "reasoning_effort", "high")
        draft = api["draft"]()
        check("改思考强度：模式仍是全功能", draft["mode"] == "full", draft["mode"])
        check("改思考强度：状态条仍显示全功能模式",
              api["ui_state"]()["chips"]["模式"] == "全功能模式", api["ui_state"]()["chips"]["模式"])
        check("改思考强度：基线仍是全功能预设",
              api["ui_state"]()["chips"]["基线"] == "全功能模式", api["ui_state"]()["chips"]["基线"])
        api["edit"]("pipeline", "scan_days", 7)
        check("改整理参数：模式仍是全功能", api["draft"]()["mode"] == "full", api["draft"]()["mode"])
        check("改参数：能力集合未被动过",
              api["draft"]()["features"] == main.preset_features("full"), str(api["draft"]()["features"]))
        state = api["ui_state"]()
        check("改参数：保存按钮启用", state["save_button"] == "normal", state["save_button"])
        check("改参数：待保存计数增加", state["chips"]["未保存改动"] != "0", state["chips"]["未保存改动"])
        check("改参数：llm_tokens 恢复链接可用", api["reset_links"]().get("llm_tokens") is True,
              str(api["reset_links"]))

    @step
    def capability_edit_degrades():
        """只有能力项才会离开预设，改回来又会自动归位。"""
        api["set_mode"]("full")
        api["edit"]("feature", "chat", False)
        check("改能力项：模式转为自定义", api["mode"]() == "custom", api["mode"]())
        check("改能力项：基线是全功能预设", api["baseline_label"]() == "全功能模式", api["baseline_label"]())
        api["edit"]("feature", "chat", True)
        check("能力项改回：模式自动归位全功能", api["mode"]() == "full", api["mode"]())

    @step
    def embedding_dependency():
        api["edit"]("feature", "embedding", True)
        state = api["ui_state"]()
        check("开 Embedding：字段启用", set(state["emb_fields"]) == {"normal"}, str(state["emb_fields"]))
        api["edit"]("feature", "faiss", True)
        check("开 FAISS：勾选生效", api["draft"]()["features"]["faiss"] is True)
        api["edit"]("feature", "embedding", False)
        draft = api["draft"]()
        check("关 Embedding：FAISS 自动关闭", draft["features"]["faiss"] is False, str(draft["features"]))
        check("关 Embedding：scope 收窄", api["gate"]()["reindex_scopes"] == ["all", "bm25"],
              str(api["gate"]()["reindex_scopes"]))

    @step
    def reset_feedback():
        api["edit"]("pipeline", "max_units", 10)
        api["reset_section"]("pipeline")
        state = api["ui_state"]()
        check("回到基线：弹出 toast 提示", "回到基线" in api["last_toast"](), api["last_toast"]())
        check("回到基线：值回到 5", api["draft"]()["pipeline"]["max_units"] == main.PRESET_PIPELINE["max_units"],
              str(api["draft"]()["pipeline"]))

    @step
    def mode_change_toast():
        api["set_mode"]("minimal")
        check("模式切换：弹出 toast 提示", "模式" in api["last_toast"](), api["last_toast"]())
        check("模式切换：状态条同步", api["ui_state"]()["chips"]["模式"] == "基础模式",
              api["ui_state"]()["chips"]["模式"])
        check("模式切换：基线随动", api["ui_state"]()["chips"]["基线"] == "基础模式",
              api["ui_state"]()["chips"]["基线"])

    @step
    def collapse_to_preset():
        # 折叠只看能力集合：参数与预设不同也不影响（这里故意留一个不同的参数）
        api["set_mode"]("minimal")
        api["edit"]("llm", "max_tokens", 8192)
        check("折叠前：改参数仍留在基础模式", api["mode"]() == "minimal", api["mode"]())
        api["edit"]("feature", "auto_memory", True)
        check("折叠前：模式为自定义", api["mode"]() == "custom", api["mode"]())
        api["edit"]("feature", "auto_memory", False)
        check("折叠后：模式自动回到基础模式", api["mode"]() == "minimal", api["mode"]())
        check("折叠后：给出 toast 说明", "自动切换" in api["last_toast"]() or "模式" in api["last_toast"](),
              api["last_toast"]())

    @step
    def typed_values_survive_other_edits():
        # 用户报的问题：选好模型后再点下面的开关，模型名与 Embedding 地址被清空
        api["set_mode"]("minimal")
        api["set_field"]("llm_model", "deepseek/deepseek-flash")
        api["set_field"]("llm_base", "http://127.0.0.1:10100/v1")
        api["set_field"]("emb_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api["set_field"]("emb_model", "text-embedding-v4")
        api["set_field"]("emb_dims", "1024")
        api["edit"]("llm", "thinking_enable", True)          # 点击“允许内部思考”
        check("点击开关后：模型名保留", api["field"]("llm_model") == "deepseek/deepseek-flash",
              api["field"]("llm_model"))
        check("点击开关后：Embedding 地址保留",
              api["field"]("emb_base") == "https://dashscope.aliyuncs.com/compatible-mode/v1",
              api["field"]("emb_base"))
        api["edit"]("llm", "reasoning_effort", "high")       # 再点“思考强度”
        check("点击思考强度后：模型名仍保留", api["field"]("llm_model") == "deepseek/deepseek-flash",
              api["field"]("llm_model"))
        check("点击思考强度后：Embedding 地址仍保留",
              api["field"]("emb_base") == "https://dashscope.aliyuncs.com/compatible-mode/v1",
              api["field"]("emb_base"))
        draft = api["draft"]()
        check("输入的值已进入草稿（保存时会写盘）",
              draft["llm"]["model"] == "deepseek/deepseek-flash"
              and draft["embedding"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
              and draft["embedding"]["dimensions"] == 1024,
              str(draft["llm"]) + str(draft["embedding"]))

    @step
    def tests_require_a_key_first():
        # 用户要求：没填 API Key 就不该发起测试，而是弹窗明确说缺哪个变量
        api["set_mode"]("minimal")
        api["set_field"]("llm_key", "")
        api["set_field"]("llm_base", "http://127.0.0.1:10100/v1")
        api["set_field"]("llm_model", "deepseek/deepseek-flash")
        api["run_llm_test"]()
        state = api["ui_state"]()
        check("缺 Key 时：LLM 测试未发起，状态说明缺 LLM_API_KEY",
              "LLM_API_KEY" in state["llm_status"] and "未测试" in state["llm_status"], state["llm_status"])
        check("缺 Key 时：弹出提示且点名 LLM_API_KEY",
              any("LLM_API_KEY" in text for text in dialogs["warnings"]), str(dialogs["warnings"]))

        api["set_field"]("emb_key", "")
        api["set_field"]("emb_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api["set_field"]("emb_model", "text-embedding-v4")
        api["run_emb_test"]()
        state = api["ui_state"]()
        check("缺 Key 时：Embedding 测试未发起，状态说明缺 EMBEDDING_API_KEY",
              "EMBEDDING_API_KEY" in state["emb_status"] and "未测试" in state["emb_status"], state["emb_status"])
        check("缺 Key 时：弹出提示且点名 EMBEDDING_API_KEY",
              any("EMBEDDING_API_KEY" in text for text in dialogs["warnings"]), str(dialogs["warnings"]))

        api["set_field"]("llm_model", "")
        api["run_llm_test"]()
        check("缺模型名时：提示填写地址与模型名",
              "Base URL" in api["ui_state"]()["llm_status"] or "模型名" in api["ui_state"]()["llm_status"],
              api["ui_state"]()["llm_status"])

    @step
    def vm_buttons_fit_their_labels():
        # 防回归：之前按钮列太窄，“扫描密钥”四个字被裁掉
        fit = api["vm_button_fit"]()
        check("VM 按钮：包含“扫描密钥…”且改到表格下方横排",
              any(text.startswith("扫描密钥") for text in fit), str(list(fit)))
        narrow = {text: size for text, size in fit.items() if size[0] < size[1]}
        check("VM 按钮：每个按钮宽度都放得下自己的文字", not narrow, str(narrow))

    @step
    def key_warning_is_short():
        for text in dialogs["warnings"]:
            if "LLM_API_KEY" in text or "EMBEDDING_API_KEY" in text:
                check("缺 Key 弹窗：文案简短（≤ 60 字）", len(text) <= 60, f"{len(text)} 字：{text}")
                break

    @step
    def window_is_called_console():
        title = api["window_title"]()
        check("窗口标题叫“控制台”（不再是“配置”）", "控制台" in title and "配置" not in title, title)

    @step
    def install_detection_and_onboarding():
        note = api["install_note"]()
        check("已安装场景：提示已检测到 ReMe", "已检测到 ReMe" in note, note)
        api["set_root"]("C:/Windows")
        note = api["install_note"]()
        check("未安装场景：提示未检测到 / 给出候选", ("未检测到 ReMe" in note) or ("扫描到候选" in note), note)
        check("扫描能列出本机已有的 ReMe 安装", bool(api["scan_installations"]()), str(api["scan_installations"]()))
        prompt = api["install_prompt"]()
        check("安装提示词包含关键步骤",
              all(part in prompt for part in ("reme-ai[core]", "service.backend=http", "2333")), prompt[:120])
        api["copy_prompt"]()
        check("复制提示词：给出剪贴板反馈", any("剪贴板" in text for text in dialogs["confirm"]),
              str(dialogs["confirm"][-3:]))
        api["set_root"](str(main.reme_root()))
        check("恢复目录后：重新显示已检测到", "已检测到 ReMe" in api["install_note"](), api["install_note"]())

    @step
    def save_keeps_window_open():
        api["edit"]("llm", "max_tokens", 12345)
        check("保存前：有未保存改动", api["ui_state"]()["chips"]["未保存改动"] != "0",
              api["ui_state"]()["chips"]["未保存改动"])
        api["apply_saved_state"]()   # 模拟保存成功后的收尾（真实 save 会走同样的函数）
        state = api["ui_state"]()
        check("保存后：窗口仍然打开", api["window_alive"]() is True, str(api["window_alive"]()))
        check("保存后：未保存改动归零", state["chips"]["未保存改动"] == "0", state["chips"]["未保存改动"])
        check("保存后：底部提示没有改动", "没有未保存的改动" in state["footer"], state["footer"])
        check("保存后：给出已保存提示", "已保存" in api["last_toast"](), api["last_toast"]())

    @step
    def dream_history_and_run_gating():
        history = api["dream_history"]()
        check("整理记录：显示真实解析结果", "写入 3 个节点" in history and "扫描 6 个文件" in history,
              history)
        api["begin_dream"]()
        check("整理期间：按钮禁用", api["ui_state"]()["dream_button"] == "disabled", api["ui_state"]()["dream_button"])
        check("整理期间：按钮文字变为整理中", "整理中" in api["dream_button_text"](), api["dream_button_text"]())
        api["finish_dream"](True, "auto_dream 完成（1s）：No changed dream input")
        check("整理结束：按钮文字复位", "整理中" not in api["dream_button_text"](), api["dream_button_text"]())
        history = api["dream_history"]()
        check("整理结束：仍显示真实解析结果", "写入 3 个节点" in history and "扫描 6 个文件" in history,
              history)

    @step
    def uninstalled_guidance():
        api["set_root"]("C:/Windows")
        state = api["ui_state"]()
        check("未安装：服务状态标红为“未安装”", state["chips"]["服务"] == "未安装", state["chips"]["服务"])
        check("未安装：保存按钮禁用", state["save_button"] == "disabled", state["save_button"])
        api["set_root"](str(main.reme_root()))
        check("恢复目录：服务状态不再是“未安装”", api["ui_state"]()["chips"]["服务"] != "未安装",
              api["ui_state"]()["chips"]["服务"])

    @step
    def theme_and_language():
        before = api["theme"]()
        api["toggle_theme"]()
        check("控制台内切主题：主题真的变了", api["theme"]() != before, api["theme"]())
        check("切主题：调色板跟着换", api["palette"]()["bg"] != "", api["palette"]()["bg"])
        api["toggle_theme"]()
        check("再切一次：回到原主题", api["theme"]() == before, api["theme"]())
        # 中英切换：只验证翻译函数本身（窗口重建由 reload_console 负责）
        check("中文模式下不翻译", api["translated"]("测试连接") == "测试连接", api["translated"]("测试连接"))
        main.CFG["ui_lang"] = "en"
        check("英文模式下翻译生效", api["translated"]("测试连接") == "Test connection",
              api["translated"]("测试连接"))
        check("未收录的文案回退为原文", api["translated"]("完全没收录的句子") == "完全没收录的句子")
        main.CFG["ui_lang"] = "zh"

    @step
    def custom_loads_saved_config():
        api["set_mode"]("minimal")   # 先离开自定义，再从预设进入自定义（此时应载入磁盘配置）
        api["set_mode"]("custom")
        draft = api["draft"]()
        check("切到自定义：模式为自定义", draft["mode"] == "custom", draft["mode"])
        check("切到自定义：基线是已保存配置", api["baseline_label"]() == "已保存配置", api["baseline_label"]())
        check("切到自定义：载入的是磁盘上的配置（而非预设副本）",
              draft["features"] == main.deep_copy(main.CFG["custom"]), str(draft["features"]))
        check("切到自定义：因凭据不算改动，回到基线按钮禁用",
              api["ui_state"]()["reset_all_button"] == "disabled", api["ui_state"]()["reset_all_button"])

    @step
    def mode_switch_keeps_typed_values():
        api["set_field"]("llm_model", "deepseek/deepseek-flash")
        api["set_field"]("emb_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api["set_mode"]("full")
        check("切模式后：模型名保留", api["field"]("llm_model") == "deepseek/deepseek-flash", api["field"]("llm_model"))
        check("切模式后：Embedding 地址保留",
              api["field"]("emb_base") == "https://dashscope.aliyuncs.com/compatible-mode/v1", api["field"]("emb_base"))
        api["set_mode"]("minimal")
        check("再切到基础模式：模型名仍保留", api["field"]("llm_model") == "deepseek/deepseek-flash",
              api["field"]("llm_model"))
        check("切换提示写明数据已保留", "保留" in api["last_toast"](), api["last_toast"]())

    @step
    def auto_memory_toggle():
        api["set_mode"]("minimal")
        api["reset_section"]("llm")      # 归零调参，确保当前确实处于基础模式预设
        api["edit"]("feature", "auto_memory", False)
        api["edit"]("feature", "auto_dream", False)
        check("基础模式：自动记忆开关为未勾选", api["auto_enabled"]() is False, str(api["auto_enabled"]()))
        check("基础模式：处于基础模式预设", api["mode"]() == "minimal", api["mode"]())
        api["toggle_auto"](True)
        draft = api["draft"]()
        check("点开关后：Auto Memory 与 Auto Dream 同时开启",
              draft["features"]["auto_memory"] and draft["features"]["auto_dream"], str(draft["features"]))
        check("点开关后：模式转为自定义", draft["mode"] == "custom", draft["mode"])
        check("点开关后：toast 说明依赖 LLM", "LLM" in api["last_toast"](), api["last_toast"]())
        api["toggle_auto"](False)
        draft = api["draft"]()
        check("取消开关：两项同时关闭",
              not draft["features"]["auto_memory"] and not draft["features"]["auto_dream"], str(draft["features"]))

    return steps


def main_run():
    def harness(api):
        root = api["root"]
        steps = build_steps(api)

        def runner(index=0):
            if index >= len(steps):
                failures = [name for name, ok, _ in results if not ok]
                finished["failures"] = len(failures)
                finished["done"] = True
                LOG_PATH.write_text(
                    "settings ui test: " + ("PASS" if not failures else f"FAIL ({len(failures)})") + "\n"
                    + "\n".join(f"{'ok  ' if ok else 'FAIL'} {name} {detail}" for name, ok, detail in results) + "\n",
                    encoding="utf-8",
                )
                root.after(200, api["close"])
                return
            try:
                steps[index]()
            except Exception:  # noqa: BLE001 - report instead of hanging the window
                results.append((f"step {index} crashed", False, traceback.format_exc(limit=3)))
            root.after(150, lambda: runner(index + 1))

        root.after(400, runner)

    main.enable_dpi_awareness()
    patch_dialogs()
    main.show_settings(autoclose_ms=40000, harness=harness)
    deadline = time.time() + 40
    while not finished["done"] and time.time() < deadline:
        time.sleep(0.3)
    total = len(results)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"settings ui test: {total - failed}/{total} checks passed")
    return 0 if (total and not failed) else 1


if __name__ == "__main__":
    raise SystemExit(main_run())
