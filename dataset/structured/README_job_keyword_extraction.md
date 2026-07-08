# 岗位关键词高召回抽取说明

## 所属阶段

该步骤位于岗位主表清洗之后、合成详细简历数据集之前。

它和 `extract_job_skills.py` 的定位不同：

- `extract_job_skills.py`：偏保守，只抽标准技能 span，适合图谱和能力差距分析。
- `extract_job_keywords.py`：偏高召回，抽技术词、岗位标签、业务场景、硬约束、英文工具/框架、自动短语，适合后续扩充合成简历。

## 运行命令

在 `dataset/` 目录执行：

```powershell
npm run extract:job-keywords
```

等价于：

```powershell
python scripts/extract_job_keywords.py
```

调试前 100 条：

```powershell
python scripts/extract_job_keywords.py --limit 100 --output-dir structured/keyword_debug
```

## 默认输入

```text
cleaned/all_jobs_23714_normalized.jsonl
```

## 默认输出

```text
structured/job_keyword_vocabulary.csv
structured/job_keyword_vocabulary_enterprise.csv
structured/job_keyword_vocabulary_government.csv
structured/job_keyword_mentions.jsonl
structured/job_keyword_mentions.csv
structured/job_keyword_extract_report.json
```

## 输出解释

### `job_keyword_vocabulary.csv`

全量岗位关键词词表，包含企业岗位和公务员岗位。

字段：

```text
normalized_keyword
category
keyword_type
doc_count
mention_count
source_type_counts
example_job_ids
example_job_titles
example_evidence
```

### `job_keyword_vocabulary_enterprise.csv`

只统计企业招聘岗位的关键词。

后续如果要基于现有简历生成更详细的 IT/AI/产品/云计算/游戏开发类简历，优先使用这个文件。

### `job_keyword_vocabulary_government.csv`

只统计公务员/事业单位岗位的关键词。

适合分析学历、专业、政治面貌、基层工作经历、考试类别等硬约束。

### `job_keyword_mentions.jsonl`

一行表示一个岗位中的一个关键词命中。

字段：

```text
job_id
job_title
company_name
source_type
source_name
raw_keyword
normalized_keyword
category
keyword_type
source
evidence_field
evidence_sentence
confidence
match_method
```

### `job_keyword_extract_report.json`

本次抽取的统计报告，包含输入岗位数、覆盖率、唯一关键词数、命中数、类别分布和 Top 关键词。

## 抽取方法

当前版本采用确定性规则，不调用 LLM：

```text
seed_dictionary
regex_english
regex_chinese_phrase
title_tag
```

设计目标是高召回，因此会保留一些比较泛的词，例如“产品”“技术”“运营”“学历”。这些词不建议直接作为技能，而适合作为合成简历时的候选背景词、岗位族词或过滤依据。

## 给合成简历的建议用法

后续生成详细简历时建议优先读取：

```text
job_keyword_vocabulary_enterprise.csv
```

推荐按类别取词：

```text
AI与大模型
AI基础设施
数据与算法
数据工程
云原生与运维
编程语言
数据库
软件工程
测试质量
游戏开发
产品运营
项目管理
硬约束
```

不要直接用某个具体 `job_id` 的 JD 来生成对应简历，否则会造成数据泄漏。更稳妥的方式是：

```text
原始简历字段
  + 岗位族关键词
  + 企业岗位高频技术/业务词
  + 项目经历模板
  -> 合成详细简历
```
