"""中英对照文案表 —— 一个配置表，一式两份。

用法：main.py 里的界面文案照旧写中文，`t()` 会在英文模式下查这张表。
表里一行一个词条：左边是源码里写的中文，右边是英文。改文案时两列一起看即可。

规则（由 test_i18n.py 自动检查）：
  * 中文列不能重复（否则无法判断该用哪条）；
  * 英文列不能为空、不能残留中文（漏译会当场红灯）；
  * main.py 里出现的每一条中文字面量，要么在本表里，要么在 EXEMPT 里（附理由）；
  * 两个字符以上的词条同时充当「片段」：像 「已保存：xxx（窗口保持打开）」 这种拼接出来的
    句子，会按最长片段替换成英文；一个字的词条只做整串匹配（否则「中」会到处误伤）。

检查命令：
    python main.py --lang-audit      # 打印未收录的中文，并生成 i18n_review.md（左右对照）
"""
from __future__ import annotations

import json
from pathlib import Path

def _load_text_pairs():
    """词条数据：src/modules/i18n/pairs.json（代码与数据分离，加词条不改代码）。"""
    path = Path(__file__).resolve().parent / "pairs.json"
    with open(path, encoding="utf-8") as f:
        return [tuple(pair) for pair in json.load(f)]


TEXT: list[tuple[str, str]] = _load_text_pairs()

# ============================== 引擎 ==============================
import ast
import re
from pathlib import Path

HAN = re.compile(r"[\u4e00-\u9fff]")
FULLWIDTH = re.compile(r"[，。：；！？（）【】“”、《》]")

# 单个标点也当片段替换（中文标点在英文里本来就该换掉）
PUNCT: dict[str, str] = {
    "（": " (", "）": ")", "，": ", ", "。": ". ", "：": ": ", "；": "; ",
    "、": ", ", "！": "!", "？": "?", "【": " [", "】": "]", "“": "\"", "”": "\"",
}

# 这两个词条故意在英文里保留中文（语言开关本身要显示“中文”）
ALLOW_CJK_IN_EN: frozenset[str] = frozenset({"中文", "English / 中文"})

# 明确不翻译的中文，每条都要有理由
EXEMPT: frozenset[str] = frozenset({
    "ReMe-启动与接入说明.md",     # 磁盘上的真实文件名
    "== 未覆盖 ==",               # --lang-audit 的命令行输出，给开发者看，不进界面
    "== 表里没被用上 ==",
    "对照表已生成：",
})

_EN: dict[str, str] = {}
_DUPLICATES: list[str] = []
for _zh, _en in TEXT:
    if _zh in _EN:
        _DUPLICATES.append(_zh)
    _EN[_zh] = _en

# 片段按长度倒序：长词条优先，避免「打开」把「打开控制台说明」提前吃掉
_FRAGMENTS: list[tuple[str, str]] = sorted(
    ((zh, en) for zh, en in TEXT if len(zh) >= 2),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def translate(text, lang: str = "en") -> str:
    """把一条界面文案翻成当前语言。

    中文模式原样返回；英文模式先整串查表，再按最长片段替换——这样
    「已保存：xxx（窗口保持打开）」这类拼接出来的句子也能整体变成英文。
    查不到的条目原样返回（宁可显示中文，也不要空白）。
    """
    value = "" if text is None else str(text)
    if lang != "en" or not value:
        return value
    exact = _EN.get(value)
    if exact is not None:
        return exact
    if not HAN.search(value) and not FULLWIDTH.search(value):
        return value                     # 纯英文/符号，不用处理
    out = value
    for zh, en in _FRAGMENTS:
        if zh in out:
            out = out.replace(zh, en)
    for zh, en in PUNCT.items():
        if zh in out:
            out = out.replace(zh, en)
    return out


def untranslated(value: str) -> bool:
    """英文模式下这条文案是否还残留中文（审查与测试用它当红灯）。"""
    if value in ALLOW_CJK_IN_EN:
        return False
    result = translate(value, "en")
    return bool(HAN.search(result) or FULLWIDTH.search(result))


# ------------------------------ 源码审查 ------------------------------
def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _excluded_ids(tree: ast.AST) -> set[int]:
    """不参与翻译审查的字符串：docstring 与 re.compile 的模式。"""
    ids = _docstring_ids(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "compile":
            continue
        for arg in node.args:
            for child in ast.walk(arg):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    ids.add(id(child))
    return ids


def collect_literals(path) -> list[tuple[int, str]]:
    """源码里需要翻译的中文字面量：跳过 docstring、正则、以及 log(...) 里的日志文案。

    f-string 会拆成常量片段（「已保存：」这种），这样拼接句也能逐段翻译。
    返回 [(行号, 文案)]，按行号排序，同一条只保留一次。
    """
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    skip = _excluded_ids(tree)
    found: dict[str, int] = {}

    def is_log_line(lineno: int) -> bool:
        line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return False
        return bool(re.search(r"(^|[^\w.])log\(", line))

    def add(node: ast.Constant) -> None:
        value = node.value
        if not isinstance(value, str) or id(node) in skip or not HAN.search(value):
            return
        if is_log_line(node.lineno):
            return
        found.setdefault(value, node.lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            add(node)
        elif isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    add(piece)

    return [(lineno, value) for value, lineno in sorted(found.items(), key=lambda pair: pair[1])]


def audit(paths) -> dict:
    """审查：表里缺哪些中文（missing）、哪些词条没被用上（table_only）。"""
    used: set[str] = set()
    missing: list[tuple[str, int, str]] = []
    for path in paths:
        for lineno, value in collect_literals(path):
            used.add(value)
            if value in EXEMPT:
                continue
            if untranslated(value):
                missing.append((Path(path).name, lineno, value))
    return {
        "missing": missing,
        "table_only": [zh for zh, _ in TEXT if zh not in used],
        "duplicates": list(_DUPLICATES),
        "empty_en": [zh for zh, en in TEXT if not en.strip()],
        "cjk_en": [(zh, en) for zh, en in TEXT
                   if en not in ALLOW_CJK_IN_EN and (HAN.search(en) or FULLWIDTH.search(en))],
    }


def review_markdown() -> str:
    """生成左右对照的 Markdown，方便逐条检查中英是否得当。"""

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>").replace("\r", "")

    rows = ["# 中英对照表（由 i18n.py 自动生成）", "",
            f"共 {len(TEXT)} 条。左列是源码里写的中文，右列是英文模式下显示的内容。", "",
            "| # | 中文 | English |", "|---|------|---------|"]
    for index, (zh, en) in enumerate(TEXT, 1):
        rows.append(f"| {index} | {cell(zh)} | {cell(en)} |")
    return "\n".join(rows) + "\n"
