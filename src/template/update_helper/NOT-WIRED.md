# NOT-WIRED · update_helper

## 结论
本工具**有意不采纳**模板 `modules/update_helper/`。

## 依据
- **D13（2026-09-19 决策）**：`reme` **不采纳** `update_helper` —— 它是蓝图；
  反向采纳会毁掉唯一的基线。**代价已知**：一致性靠人工审阅维持
  （实证：reme 早就把外部命令绝对路径化了，而模板很久之后才追上，
  **其间没有任何机制报告过**）。
- 本工具的更新链是**内联 + OVERRIDE 申报**（bat + 备份目录链路，行为差异大，
  见 `复审记录.md` 对应关系矩阵）。它的 `UPDATE-CHAIN-REFERENCE.md` 是模板的
  **参考文档**（`ALIGNMENT §7.2`）。

## 重验触发
- 模板 `update_helper` 出现 reme **真正需要**的能力时；
- D13 被推翻时（那需要**带证据**，见 `TASKLEDGER §四` 的推翻规则）。
