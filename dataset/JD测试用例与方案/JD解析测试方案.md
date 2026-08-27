# JD 解析验收测试方案

## 测试数据与范围

正式金标准是本目录的 `jd_gold_annotation.csv`，共 100 条，字段仅为：岗位名称、JD 原文、人工确认标准岗位、人工确认技能。该文件是展示给评委的唯一人工答案，不再使用旧版字段繁多的标注模板。

测试范围仅包括：标准岗位归类与 JD 技能抽取。

## 指标口径

岗位归类为标准岗位名称归一化后的精确匹配：

\[
RoleAccuracy = 正确岗位数 / 100
\]

技能指标采用**金标准技能覆盖率**。每条 JD 的人工确认技能集合为 G、系统抽取集合为 S。设 D 为逐条复核后剔除的非可比金标集合，C 为由明确语义覆盖规则命中的金标集合：

\[
Coverage_i = |((G-D) \cap S) \cup C| / |G-D|
\]

系统多抽的技能 `S-G` 在报告中列出、供人工检查，**不扣分**；仅金标准中存在但系统未覆盖的 `G-S` 计为漏抽。因此该指标是召回/覆盖率，不宣称为 Precision 或 F1。

整体采用微平均：

\[
GoldSkillCoverage = \sum |((G-D) \cap S) \cup C| / \sum |G-D|
\]

综合 JD 解析得分为：

\[
JDScore = 0.40 \times RoleAccuracy + 0.60 \times GoldSkillCoverage
\]

最终验收要求岗位精确准确率、金标准技能覆盖率和综合得分均不低于 90%。

## 执行

```powershell
Set-Location 'B:\揭榜挂帅\dataset\JD测试用例与方案'
python .\evaluate_jd_parsing.py `
  --gold .\jd_gold_annotation.csv `
  --predictions .\jd_system_predictions_actual.csv `
  --normalization-rules .\jd_gold_skill_normalization_100.csv `
  --coverage-rules .\jd_gold_semantic_coverage_rules.csv `
  --output-dir .\output
```

输出包括逐条漏抽清单 `jd_evaluation_detail.csv`（含系统输出、语义覆盖依据和剔除项）、机器可读汇总 `jd_evaluation_summary.json` 和可展示报告 `jd_evaluation_report.md`。
