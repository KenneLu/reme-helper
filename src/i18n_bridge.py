# -*- coding: utf-8 -*-
"""W3 后段迁移垫层（R 方案）：重形态调用点 → 轻形态 T5（template/i18n 2.3.0）的桥。

- 词表：locales/{zh,en}.json（数据驱动，加词条/加语言只改 JSON）
- 反查：_ZH2KEY 由 zh 表逆转（851+ 词条中文全唯一，准备期已验证）；历史调用点
  传中文原文，经反查转键后走轻形态取词——迁移期双轨，未收录词条两模式都
  原样返回（与旧重形态「未收录原样返回」语义一致）。
- 语言态：i18n._STATE 是唯一真值，sync_lang() 由消费方驱动（main.ui_lang /
  guide_markdown 的 context lang）。
"""
from template.i18n import i18n

_ZH2KEY: dict = {}


def _rebuild() -> None:
    _ZH2KEY.clear()
    _ZH2KEY.update({v: k for k, v in i18n.TABLES.get("zh", {}).items()})


def sync_lang(lang: str) -> None:
    i18n.init(lang)


def tt(text) -> str:
    if not _ZH2KEY:
        _rebuild()
    try:
        key = _ZH2KEY.get(text)
        if key is not None:
            return i18n.t(key)
        return _fragment_translate(text)
    except Exception:  # noqa: BLE001 - translation must never break the UI
        return str(text)


# 中文标点（英文里本来就该换掉；自旧重形态引擎平移）
PUNCT: dict = {
    "（": " (", "）": ")", "，": ", ", "。": ". ", "：": ": ", "；": "; ",
    "、": ", ", "！": "!", "？": "?", "【": " [", "】": "]", "\u201c": "\"", "\u201d": "\"",
}
_FRAGMENTS: list = []


def _build_fragments() -> None:
    """片段 = zh 表值（len>=2）→ 对应英文，按值长度倒序（长片段优先，防止误吞）。"""
    _FRAGMENTS.clear()
    en_items = i18n.TABLES.get("en", {})
    frags = [(zh, en_items.get(key, zh)) for key, zh in i18n.TABLES.get("zh", {}).items()
             if len(zh) >= 2]
    frags.sort(key=lambda pair: len(pair[0]), reverse=True)
    _FRAGMENTS.extend(frags)


def _fragment_translate(text) -> str:
    """反查 miss 的兜底：按最长片段替换（运行时拼接句的唯一翻译路径）。

    中文模式原样返回；纯 ASCII/无中文无全角返回原文；否则片段替换 + 标点替换。
    查不到的字符原样保留（宁可显示中文，也不要空白）。
    """
    value = "" if text is None else str(text)
    if i18n.current_lang() != "en" or not value:
        return value
    if not HAN.search(value) and not FULLWIDTH.search(value):
        return value
    if not _FRAGMENTS:
        _build_fragments()
    out = value
    for zh, en in _FRAGMENTS:
        if zh in out:
            out = out.replace(zh, en)
    for zh, en in PUNCT.items():
        if zh in out:
            out = out.replace(zh, en)
    return out


# ============================== 源码审计（自旧重形态引擎平移） ==============================
import ast
import re
from pathlib import Path

# 中文字符与全角标点检测（审计与英文模式残留扫描共用）
HAN = re.compile(r"[\u4e00-\u9fff]")
FULLWIDTH = re.compile("[，。：；！？（）【】\u201c\u201d、《》]")

# 这两个词条故意在英文里保留中文（语言开关本身要显示"中文"）
ALLOW_CJK_IN_EN: frozenset = frozenset({"中文", "English / 中文"})

# 明确不翻译的中文，每条都要有理由
EXEMPT: frozenset = frozenset({
    "ReMe-启动与接入说明.md",     # 磁盘上的真实文件名
    "== 未覆盖 ==",               # --lang-audit 的命令行输出，给开发者看，不进界面
    "== 表里没被用上 ==",
    "对照表已生成：",
})


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _excluded_ids(tree):
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


def collect_literals(path):
    """源码里需要翻译的中文字面量：跳过 docstring、正则、以及 log(...) 里的日志文案。

    f-string 会拆成常量片段（「已保存：」这种），拼接句逐段进词表。
    返回 [(行号, 文案)]，按行号排序，同一条只保留一次。
    """
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    skip = _excluded_ids(tree)
    found: dict = {}

    def is_log_line(lineno):
        line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return False
        return bool(re.search(r"(^|[^\w.])log\(", line))

    def add(node):
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


def untranslated(value) -> bool:
    """英文模式下这条文案是否还残留中文（轻形态：反查 miss 或译文残中文）。"""
    if value in ALLOW_CJK_IN_EN:
        return False
    if not _ZH2KEY:
        _rebuild()
    result = tt(value)
    return bool(HAN.search(result) or FULLWIDTH.search(result))


def audit(paths) -> dict:
    """审查：词表缺哪些中文（missing）、哪些词条没被用上（table_only）。

    审计以英文模式为准（untranslated 检查译文残留），语言态自管：进入切 en，
    退出还原调用方的语言。
    """
    if not _ZH2KEY:
        _rebuild()
    saved_lang = i18n.current_lang()
    i18n.init("en")
    try:
        zh_items = sorted(i18n.TABLES.get("zh", {}).items())
        en_items = i18n.TABLES.get("en", {})
        used = set()
        missing = []
        for path in paths:
            for lineno, value in collect_literals(path):
                used.add(value)
                if value in EXEMPT:
                    continue
                if untranslated(value):
                    missing.append((Path(path).name, lineno, value))
        seen = set()
        duplicates = []
        for _, zh in zh_items:
            if zh in seen:
                duplicates.append(zh)
            seen.add(zh)
        report = {
            "missing": missing,
            "table_only": [zh for _, zh in zh_items if zh not in used],
            "duplicates": duplicates,
            "empty_en": [key for key, en in en_items.items() if not str(en).strip()],
            "cjk_en": [(key, en) for key, en in en_items.items()
                       if str(en) not in ALLOW_CJK_IN_EN and (HAN.search(str(en)) or FULLWIDTH.search(str(en)))],
        }
    finally:
        i18n.init(saved_lang)
    return report


def review_markdown() -> str:
    """键/中文/英文三列对照表（--lang-audit 输出，供人工校对）。"""
    if not _ZH2KEY:
        _rebuild()
    zh_items = sorted(i18n.TABLES.get("zh", {}).items())
    en_items = i18n.TABLES.get("en", {})
    lines = ["| 键 | 中文 | English |", "|---|---|---|"]
    lines += [f"| `{key}` | {zh} | {en_items.get(key, '')} |" for key, zh in zh_items]
    return "\n".join(lines) + "\n"
