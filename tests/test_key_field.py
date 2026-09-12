"""密钥字段：从配置读出的 Key **不落进控件**（只填定长占位符，长度不泄漏）。

旧契约是「把真 Key 放进输入框、靠 show=* 渲染成星号」——星号数量因此等于 Key 长度，
.env 里写着 123 界面上就是 ***，长度直接泄漏。新契约：
  1. 已配置 → 字段填一个定长占位符，长度与真实 Key 无关；
  2. 占位符状态下「显示」没有意义，按钮禁用；
  3. 测试连接用 .env 里存的那份 Key（不能拿占位符去测）；
  4. 没动过字段 → 保存**不重写** .env 的 Key（否则 40 个星号会覆盖真 Key）。
用户自己敲的照常按真实长度掩码，那是他自己输的。
"""
import os
import sys
import time
from pathlib import Path

from conftest import TOOL  # noqa: E402  (puts src/ on sys.path)
import main  # noqa: E402

LOG = TOOL / "log" / "tests" / "key-field-test.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
FAKE_KEY = "sk-test-1234567890abcdef"
FAKE_EMB_KEY = "sk-emb-abcdef123456"
TYPED_KEY = "sk-typed-by-hand-001"
results: list[tuple[str, bool, str]] = []
finished = {"done": False}

for _name in ("showwarning", "showerror", "showinfo"):
    setattr(main.messagebox, _name, lambda *a, **k: True)
main.messagebox.askyesno = lambda *a, **k: False
main.save_config = lambda *a, **k: None
# 假装 .env 里已经有 Key，而且模型与保存值不同（外部工具改过 .env 的情形）
main.read_env_values = lambda: {"LLM_API_KEY": FAKE_KEY,
                                "EMBEDDING_API_KEY": FAKE_EMB_KEY,
                                "LLM_MODEL_NAME": "model-from-env",
                                "LLM_BASE_URL": "http://127.0.0.1:10100/v1"}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), str(detail)))


def check_pure() -> None:
    """不依赖窗口的那两条规则。"""
    placeholder = main.KEY_MASK_PLACEHOLDER
    check("占位符是定长的", len(placeholder) >= 32 and set(placeholder) == {"*"}, repr(placeholder))
    check("占位符长度不等于真 Key 长度", len(placeholder) != len(FAKE_KEY),
          f"{len(placeholder)} vs {len(FAKE_KEY)}")
    check("空字段算没动过", main.key_field_untouched("") is True)
    check("占位符算没动过", main.key_field_untouched(placeholder) is True)
    check("真实输入算动过", main.key_field_untouched("sk-x") is False)
    check("没动过时取 .env 的值", main.key_field_value(placeholder, FAKE_KEY) == FAKE_KEY)
    check("空字段也取 .env 的值", main.key_field_value("", FAKE_KEY) == FAKE_KEY)
    check("动过后取用户输入", main.key_field_value(TYPED_KEY, FAKE_KEY) == TYPED_KEY)


def main_run() -> int:
    main.enable_dpi_awareness()
    main.CFG["ui_lang"] = "zh"
    # 保存值故意与 .env 不同（外部工具改过 .env 的情形），用来验证「按 .env 校正」
    main.CFG["llm"]["model"] = "model-from-config"
    main.CFG["llm"]["base_url"] = "http://saved.example/v1"
    check_pure()

    def harness(api):
        def run():
            try:
                placeholder = api["placeholder"]()
                field = api["field"]("llm_key")

                # ---- 1. 载入：只放占位符，真 Key 一个字都不进控件 ----
                check("已配置的 Key 不进控件（字段是占位符）", field == placeholder, repr(field))
                check("字段里不含真 Key", FAKE_KEY not in field, repr(field))
                check("占位符长度不等于真 Key 长度", len(field) != len(FAKE_KEY),
                      f"{len(field)} vs {len(FAKE_KEY)}")
                check("Embedding Key 同样只放占位符",
                      api["field"]("emb_key") == placeholder, repr(api["field"]("emb_key")))

                # ---- 2. 掩码与「显示」按钮 ----
                check("默认是掩码（show=*）", api["key_masked"]("llm") is True,
                      str(api["key_masked"]("llm")))
                check("占位符状态下「显示」按钮禁用",
                      api["key_toggle_enabled"]("llm") is False,
                      str(api["key_toggle_enabled"]("llm")))
                api["reveal_key"]("llm")
                check("禁用状态下点「显示」不会变明文", api["key_masked"]("llm") is True,
                      str(api["key_masked"]("llm")))

                # ---- 3. 没动过＝用 .env 里那份（测试连接靠它）----
                check("没动过时测试用 .env 的 LLM Key",
                      api["effective_key"]("llm") == FAKE_KEY, api["effective_key"]("llm"))
                check("没动过时测试用 .env 的 Embedding Key",
                      api["effective_key"]("emb") == FAKE_EMB_KEY, api["effective_key"]("emb"))

                # ---- 4. 没动过＝保存不重写 .env 的 Key（占位符不能落盘）----
                updates = api["env_updates"]()
                check("没动过时不重写 LLM_API_KEY", "LLM_API_KEY" not in updates, str(updates))
                check("没动过时不重写 EMBEDDING_API_KEY",
                      "EMBEDDING_API_KEY" not in updates, str(updates))
                check("其余 .env 项照常写", "LLM_BASE_URL" in updates, str(updates))

                # ---- 5. 用户输入后：按钮可用、按真实长度掩码、保存才覆盖 ----
                api["set_field"]("llm_key", TYPED_KEY)
                check("输入后「显示」按钮可用",
                      api["key_toggle_enabled"]("llm") is True,
                      str(api["key_toggle_enabled"]("llm")))
                check("输入后测试用用户输入的 Key",
                      api["effective_key"]("llm") == TYPED_KEY, api["effective_key"]("llm"))
                check("输入后保存会覆盖 LLM_API_KEY",
                      api["env_updates"]().get("LLM_API_KEY") == TYPED_KEY,
                      str(api["env_updates"]()))
                api["reveal_key"]("llm")
                check("点「显示」后变明文", api["key_masked"]("llm") is False,
                      str(api["key_masked"]("llm")))
                api["reveal_key"]("llm")
                check("再点一次恢复掩码", api["key_masked"]("llm") is True,
                      str(api["key_masked"]("llm")))

                # ---- 6. 清空＝不改：回到 .env 那份，且不再覆盖 ----
                api["set_field"]("llm_key", "")
                check("清空后「显示」又禁用",
                      api["key_toggle_enabled"]("llm") is False,
                      str(api["key_toggle_enabled"]("llm")))
                check("清空后回到 .env 的 Key",
                      api["effective_key"]("llm") == FAKE_KEY, api["effective_key"]("llm"))
                check("清空后不重写 LLM_API_KEY",
                      "LLM_API_KEY" not in api["env_updates"](), str(api["env_updates"]()))
                api["set_field"]("llm_key", placeholder)

                # ---- 7. 敲键要整体替换占位符，不能拼成「星号 + 输入」----
                entry = api["key_entry"]("llm")
                entry.focus_force()
                api["root"].update_idletasks()
                entry.event_generate("<KeyPress>", keysym="a")
                api["root"].update_idletasks()
                after = api["field"]("llm_key")
                check("敲键后占位符被整体丢掉",
                      after == "a" and placeholder not in after, repr(after))

                # ---- 8. Key 不属于 config 草稿（只进 .env）----
                check("Key 不算未保存改动", "key" not in api["draft"]()["llm"],
                      str(api["draft"]()["llm"].keys()))
                check("Key 不写进 config 草稿", "key" not in api["draft"]()["embedding"],
                      str(api["draft"]()["embedding"].keys()))

                # ---- 9. .env 与保存值不同：以 .env 为准（ReMe 实际读 .env）----
                check("模型按 .env 校正", api["field"]("llm_model") == "model-from-env",
                      api["field"]("llm_model"))
                check("地址按 .env 校正", api["field"]("llm_base") == "http://127.0.0.1:10100/v1",
                      api["field"]("llm_base"))
                check("校正会被记录并提示", "llm.model" in api["env_corrected"](),
                      str(api["env_corrected"]()))
                check("校正提示出现在 toast 里", "校正" in api["last_toast"](), api["last_toast"]())
            except Exception as exc:  # noqa: BLE001
                check("密钥字段检查未崩溃", False, f"{type(exc).__name__}: {exc}")
            finished["done"] = True
            api["root"].after(200, api["close"])

        api["root"].after(500, run)

    main.show_settings(autoclose_ms=30000, harness=harness)
    deadline = time.time() + 30
    while not finished["done"] and time.time() < deadline:
        time.sleep(0.3)

    failed = [(n, d) for n, ok, d in results if not ok]
    LOG.write_text("key field test: " + ("PASS" if not failed else f"FAIL ({len(failed)})") + "\n"
                   + "\n".join(f"{'ok  ' if ok else 'FAIL'} {name} {detail}"
                               for name, ok, detail in results) + "\n", encoding="utf-8")
    print(f"key field test: {len(results) - len(failed)}/{len(results)} checks passed")
    return 0 if (results and not failed) else 1


if __name__ == "__main__":
    code = main_run()
    main.close_settings_window()
    time.sleep(0.2)
    os._exit(code)
