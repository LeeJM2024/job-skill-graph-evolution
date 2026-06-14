# JD 技能抽取与标准化说明

## 所属阶段

该流程位于现有 dataset 主线中的“岗位主表清洗之后、BM25/BGE-M3/图谱/金标之前”。

```text
cleaned/all_jobs_23714_normalized.jsonl
        |
        v
scripts/extract_job_skills.py
        |
        v
structured/job_skill_mentions.jsonl
structured/skill_alias_table.csv
structured/job_skill_extract_report.json
```

它不替换原 demo 的 BM25、BGE-M3、银标实验，也不修改后端接口。它只是补充一个可复用的 JD 结构化中间层，让后续图谱、硬条件判断、能力差距分析和人工金标标注可以使用同一套技能标准。

## 设计原则

第一版采用确定性词典匹配，不调用 LLM。

实现参考了 Chinese SkillSpan 这类中文能力抽取数据集的标注思想：技能 span 必须来自原文，抽取结果需要保留证据句，不能凭常识补技能。当前脚本只做工程可复现的词典 baseline，后续可以再用人工标注或模型增强。

补充参考了 SkillSpan 项目的数据设计：它把岗位文本拆成句子/token，并用 BIO 标签标注技能/知识 span。当前 demo 不引入它的训练框架，但在输出里保留了 `span_text`、`span_start`、`span_end` 和 `skillspan_label`，方便后续人工金标或模型训练。

## 运行命令

在 `dataset/` 目录执行：

```powershell
npm run extract:job-skills
```

等价于：

```powershell
python scripts/extract_job_skills.py
```

调试前 100 条岗位：

```powershell
python scripts/extract_job_skills.py --limit 100
```

指定输入和输出：

```powershell
python scripts/extract_job_skills.py `
  --input cleaned/all_jobs_23714_normalized.jsonl `
  --aliases-json config/skill_aliases.json `
  --output-dir structured
```

## 输入文件

### `cleaned/all_jobs_23714_normalized.jsonl`

统一岗位主表，一行一个岗位。关键字段：

```text
job_id
source_type
source_name
keyword
job_title
company_name
location
tags
job_description
source_url
content_hash
is_content_duplicate
duplicate_of
```

### `config/skill_aliases.json`

原 demo 中已有的简历技能组合拆分表，例如：

```json
{
  "TensorFlow/PyTorch": ["TensorFlow", "PyTorch"],
  "Docker/Kubernetes": ["Docker", "Kubernetes"]
}
```

脚本会在此基础上叠加内置中文 JD 技能词表，生成 `structured/skill_alias_table.csv`。

## 输出文件

### `structured/skill_alias_table.csv`

技能标准化词表。

字段：

```text
raw_skill
normalized_skill
category
source
confidence
```

例子：

```csv
raw_skill,normalized_skill,category,source,confidence
K8s,Kubernetes,云计算/运维,seed,0.98
大模型,Large Language Model,数据与算法,seed,0.90
SpringCloud,Spring Cloud,后端技术,seed,0.95
```

### `structured/job_skill_mentions.jsonl`

一行代表一个岗位中的一个技能命中。

字段：

```text
job_id
job_title
source_type
source_name
raw_skill
normalized_skill
category
span_text
span_start
span_end
skillspan_label
skill_type
evidence_sentence
evidence_field
confidence
match_method
```

例子：

```json
{
  "job_id": "job_2e8a95fed4174a85fb3a",
  "job_title": "AI Infra高级工程师",
  "source_type": "enterprise",
  "raw_skill": "PyTorch",
  "normalized_skill": "PyTorch",
  "category": "数据与算法",
  "span_text": "PyTorch",
  "span_start": 11,
  "span_end": 18,
  "skillspan_label": "knowledge",
  "skill_type": "required",
  "evidence_sentence": "对接主流AI框架（如PyTorch、TensorFlow）、语言运行时（如Python/Rust）和开源社区（如LLVM、MPI、KVM），推动技术落地和竞争力构建",
  "evidence_field": "job_description",
  "confidence": 1.0,
  "match_method": "dictionary"
}
```

`skill_type` 的规则：

- 证据句包含“优先、加分、更佳、preferred、nice to have”等词，标为 `preferred`。
- 其他命中默认标为 `required`。

### `structured/job_skill_mentions.csv`

与 JSONL 内容相同，方便 Excel/WPS 抽查。

### `structured/job_skill_extract_report.json`

本次抽取统计报告。

字段：

```text
input_jobs
jobs_with_skills
jobs_without_skills
job_skill_coverage
skill_mentions
unique_normalized_skills
top_skills
category_counts
coverage_by_source_type
method
```

## 当前边界

该流程第一版只做技能抽取和标准化，不做：

- 岗位标题强归一。
- Neo4j 导入。
- LLM 技能补全。
- 人工金标。
- 动态演化分析。

这些都可以在 `job_skill_mentions.jsonl` 稳定后继续接上。

## 后续接法

后续如果要建图，可以从 `job_skill_mentions.jsonl` 聚合生成：

```text
Skill 节点：normalized_skill
Job 节点：job_id
Job -[:REQUIRES_SKILL {evidence_sentence, confidence}]-> Skill
```

后续如果要辅助人工金标，可以用 `normalized_skill` 与简历中的 `skills_normalized` 做交集，提前生成：

```text
matched_skills
missing_required_skills
missing_optional_skills
```
