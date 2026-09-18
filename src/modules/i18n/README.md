# i18n（reme-helper 重形态）

中文即键 + 片段组合翻译 + AST 覆盖率审计。机制（translate / audit / collect_literals /
review_markdown）与词表数据（pairs.json，826 对 `[zh,en]`）分离——加词条只改 pairs.json。

与模板 T5（轻量 `t(key)` + locales/*.json）**不同构，不互相替代**：百条级文案的工具用本
重形态；小工具用模板轻量形态。两形态共守「词表即数据」底线（STANDARDS E4）。

检查命令：`python main.py --lang-audit`（missing 必须 = 0）。
