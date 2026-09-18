"""中英对照表的检查与覆盖测试（无需窗口）。

直接扫源码：main.py 里出现的每一条中文字面量，都必须能在 i18n.py 的表里翻成
不含中文的英文。界面上的**动态**文案（刷新时才写进去的状态、页脚、表格行）由
test_en_mode.py 的英文模式全树扫描兜底。
"""
import sys
from pathlib import Path

from conftest import SRC_DIR as SRC, TOOL  # noqa: E402  (puts src/ on sys.path)
from modules.i18n import i18n  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), str(detail)))


def run() -> int:
    # ---------------- 表本身 ----------------
    check("中文键不重复", not i18n._DUPLICATES, str(i18n._DUPLICATES[:5]))
    check("英文列不为空", not [zh for zh, en in i18n.TEXT if not en.strip()])
    cjk_en = [(zh, en) for zh, en in i18n.TEXT
              if en not in i18n.ALLOW_CJK_IN_EN and i18n.HAN.search(en)]
    check("英文列不残留中文", not cjk_en, str(cjk_en[:3]))
    check("词条数量合理（>300）", len(i18n.TEXT) > 300, str(len(i18n.TEXT)))

    # ---------------- 源码覆盖 ----------------
    report = i18n.audit([SRC / "main.py"])
    detail = "; ".join(f"{name}:{line} {value[:40]}" for name, line, value in report["missing"][:6])
    check("main.py 的中文字面量全部有英文", not report["missing"], detail)

    # ---------------- 翻译行为 ----------------
    check("中文模式原样返回", i18n.translate("测试连接", "zh") == "测试连接")
    check("整串命中", i18n.translate("测试连接", "en") == "Test connection",
          i18n.translate("测试连接", "en"))
    composed = i18n.translate("已保存：LLM 参数（窗口保持打开）", "en")
    check("拼接句按片段翻译", "Saved" in composed and "LLM settings" in composed and "window stays open" in composed,
          composed)
    check("未收录的整句回退原文", i18n.translate("完全没收录的句子", "en") == "完全没收录的句子")
    check("英文原文不被改动", i18n.translate("Saved: ok", "en") == "Saved: ok")
    check("中文标点会换成英文标点", "（" not in i18n.translate("（测试）", "en"),
          i18n.translate("（测试）", "en"))
    check("一句话只翻一次（幂等）",
          i18n.translate(i18n.translate("测试连接", "en"), "en") == "Test connection")
    check("模式名能在句子里被翻掉",
          "Full" in i18n.translate("模式：基础模式 → 全功能模式", "en"),
          i18n.translate("模式：基础模式 → 全功能模式", "en"))

    # ---------------- 内置说明：脱敏 + 通用性 ----------------
    guide_source = (SRC / "guide.py").read_text(encoding="utf-8")
    for leak in ("H:\\Tools", "C:\\Users", "xzy", "opencodex", "code-compass",
                 "ReMe-启动与接入说明.md"):
        check(f"内置说明不含机器专属内容（{leak}）", leak not in guide_source, leak)
    import guide as guide_module
    sample = guide_module.guide_markdown({
        "lang": "zh", "reme_root": r"D:\ReMe", "mode_label": "基础模式",
        "config_path": r"D:\ReMe\config\app.yaml", "workspace": r"D:\ReMe\workspace",
        "env_path": r"D:\ReMe\.env", "logs": r"D:\ReMe\logs",
        "service_url": "http://127.0.0.1:2333/", "version": "9.9",
    })
    check("内置说明能渲染出正文", len(sample) > 1500, str(len(sample)))
    check("渲染时用的是传入的本机路径", "D:\\ReMe\\workspace" in sample, sample[:120])
    english = guide_module.guide_markdown({
        "lang": "en", "reme_root": r"D:\ReMe", "mode_label": "Basic",
        "config_path": r"D:\ReMe\config\app.yaml", "workspace": r"D:\ReMe\workspace",
        "env_path": r"D:\ReMe\.env", "logs": r"D:\ReMe\logs",
        "service_url": "http://127.0.0.1:2333/", "version": "9.9",
    })
    leftover = [line for line in english.splitlines()
                if i18n.HAN.search(line) or i18n.FULLWIDTH.search(line)]
    check("内置说明的英文版没有中文残留", not leftover, "; ".join(leftover[:3]))

    # ---------------- 对照表 ----------------
    markdown = i18n.review_markdown()
    check("能生成中英对照表", markdown.count("\n|") > len(i18n.TEXT),
          str(markdown.count("\n|")))

    failed = [(name, detail) for name, ok, detail in CHECKS if not ok]
    log = TOOL / "log" / "tests" / "i18n-test.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("i18n test: " + ("PASS" if not failed else f"FAIL ({len(failed)})") + "\n"
                   + "\n".join(f"{'ok  ' if ok else 'FAIL'} {name} {detail}"
                               for name, ok, detail in CHECKS) + "\n", encoding="utf-8")
    for name, ok, detail in CHECKS:
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else "  " + detail))
    print(f"i18n test: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(run())
