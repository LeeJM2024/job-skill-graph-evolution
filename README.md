# 中文岗位 JD 数据采集说明

这个目录用于采集、保存和清洗中文岗位 JD 数据。当前主线已经从 Boss/猎聘这类强反爬招聘平台，切换为更稳定、可复现的企业官网公开招聘接口。

## 当前数据源

| 数据源 | 类型 | 当前用途 |
| --- | --- | --- |
| 腾讯招聘公开接口 | 企业官网招聘 | 补充互联网、云、AI、产品、测试、运营等岗位 JD |
| 华为招聘公开接口 | 企业官网招聘 | 扩大企业范围，补充 ICT、研发、云、数据、硬件、解决方案等岗位 JD |
| 政府/公务员/事业单位职位表 | 官方表格导入 | 补充公共部门岗位、专业要求、学历要求、招考人数等结构化字段 |

这两个源都返回 JSON，适合比赛原型阶段做“岗位 JD 抓取、清洗、标注、岗位-能力图谱构建”。

政府/公务员/事业单位数据通常由官方网站发布为 Excel/CSV 附件，当前采用“下载官方职位表后本地导入”的方式，稳定性比直接爬网页更高。

## 安装

当前脚本只使用 Node.js 内置能力，没有额外运行依赖。仍建议执行一次安装，保证 `package-lock.json` 与本地环境一致：

```powershell
cd C:\Users\A\Desktop\揭榜挂帅\job-hunt-AI\dataset
npm install
```

如果要导入公务员或事业单位 `.xlsx/.xls/.csv` 职位表，还需要 Python 表格依赖：

```powershell
python -m pip install -r requirements.txt
```

## 采集 3000 条岗位 JD

默认命令会同时采集腾讯和华为，目标 3000 条：

```powershell
npm run collect
```

等价于：

```powershell
node scripts/collect_public_jobs.mjs --source all --target 3000
```

也可以单独采集某个企业：

```powershell
npm run collect:tencent
npm run collect:huawei
```

原始结果会保存到：

```text
dataset/raw/chinese_jobs/*_public_jobs.json
```

raw 文件会保留每个查询的页码、接口 URL、返回数量、错误信息和岗位原始字段，方便后续追溯。

默认配置开启 `domesticOnly: true`，会跳过明显的海外岗位，例如东京、新加坡、美国、欧洲等地点，尽量保证当前数据集服务“本地中文岗位 JD”目标。

## 清洗并导出 JSONL/CSV

采集完成后运行：

```powershell
npm run normalize
```

默认读取最新 raw JSON，输出：

```text
dataset/cleaned/chinese_jobs_normalized.jsonl
dataset/cleaned/chinese_jobs_normalized.csv
```

如果要指定某个 raw 文件：

```powershell
node scripts/normalize_jobs.mjs --input raw/chinese_jobs/某个文件.json
```

CSV 带 UTF-8 BOM，方便 Excel/WPS 打开。数组字段如 `tags` 会用 `;` 拼接，长文本 JD 会保留完整内容并做 CSV 转义。

## 导入政府/公务员职位表

把国家公务员、省考、事业单位等官方职位表放到：

```text
dataset/raw/government_jobs/
```

支持 `.xlsx`、`.xls`、`.csv`。导入示例：

```powershell
python scripts/import_government_jobs.py --input raw/government_jobs/2026国家公务员职位表.xlsx --source-name 国家公务员2026职位表
```

如果 Excel 有多个 sheet，可以指定：

```powershell
python scripts/import_government_jobs.py --input raw/government_jobs/某省省考职位表.xlsx --sheet 0 --source-name 某省省考职位表
```

导入后会生成：

```text
dataset/raw/chinese_jobs/*_government_jobs.json
```

然后继续用同一个清洗命令：

```powershell
npm run normalize -- --input raw/chinese_jobs/某个_government_jobs.json
```

导入器会尽量识别这些常见列：`部门名称`、`招录机关`、`职位名称`、`职位代码`、`工作地点`、`学历`、`学位`、`专业`、`基层工作最低年限`、`招考人数`、`职位简介`、`备注`。

## 当前采集范围

配置文件：

```text
dataset/config/seed_queries.json
```

当前围绕赛题扩展了这些岗位群：

- 人工智能与大模型
- 算法与机器学习
- 数据工程与数据治理
- Java/Python/软件工程
- 云计算与云原生
- 物联网、嵌入式与智能硬件
- 网络安全
- 测试与质量保障
- 产品与业务分析
- 行业解决方案
- 运维与平台工程
- 数据库

最后保留了一个“全量补充岗位”查询，用于在关键词结果不足时继续补齐目标数量。

## 清洗字段

每条标准记录包含：

```text
source
source_name
keyword
city
crawl_time
job_title
company_name
salary_text
location
tags
job_description
source_url
publish_time
raw
```

其中：

- `job_description`：岗位职责和任职要求文本。
- `tags`：企业接口里的岗位族、部门、产品线、经验等标签。
- `raw`：保留企业接口原始字段，便于后续做字段扩展或证据追溯。

## 后续建议

1. 抽查 CSV 中 30-50 条 JD，确认岗位标题、企业、职责文本没有串列。
2. 用 `job_description` 做技能短语抽取，形成“岗位-技能”初始边。
3. 用 `source_name`、`publish_time`、`location` 支撑后续动态演化和区域分析。
4. 后续继续增加百度、阿里、美团、科大讯飞、小米、京东等企业官网公开源，提高行业覆盖度。
5. 公共部门数据优先收集国家公务员、省考、事业单位、国企校招/社招职位表，形成“企业岗位”和“公共岗位”的对照样本。
## 合并企业岗位与公务员岗位

在 `dataset/` 目录执行：

```powershell
npm run merge:jobs
```

输入文件：

- `cleaned/enterprise_jobs_3000_normalized.jsonl`
- `cleaned/government_jobs_2026_normalized.jsonl`

输出文件：

- `cleaned/all_jobs_23714_normalized.jsonl`
- `cleaned/all_jobs_23714_normalized.csv`

合并脚本保留全部岗位，并增加 `job_id`、`source_type`、`content_hash`、`is_content_duplicate` 和 `duplicate_of`。内容重复岗位只做标记，不会在合并阶段直接删除，便于后续按检索实验需要选择保留或折叠。

## 处理中文简历

在 `dataset/` 目录执行：

```powershell
npm run process:resumes
```

脚本同时读取原版和修订版中文简历，使用修订版作为当前辅助筛选标签，并保留原版标签用于审计。姓名、性别、年龄、电话和邮箱不会写入处理结果。

主要输出：

- `processed/resumes_anonymized.jsonl`
- `processed/resumes_anonymized.csv`
- `processed/resume_quality_report.json`
- `benchmark/resume_train_manifest.jsonl`
- `benchmark/resume_dev_manifest.jsonl`
- `benchmark/resume_test_manifest.jsonl`
- `annotations/pilot_resumes_30.jsonl`
- `annotations/resume_job_gold_template.csv`

`pilot_resumes_30.jsonl` 从 10 个岗位族中各选择 3 份简历。当前只生成简历样本，岗位候选需要在 BM25 索引完成后补充。
# 30 份简历 BM25 + BGE-M3 实验

确保 Docker 中的 Elasticsearch 已启动，并且 `chinese_jobs_v1` 已写入统一岗位主表后运行：

```powershell
cd dataset
npm run experiment:test30
```

也可以分阶段执行，首次运行 BGE-M3 会下载约 2.27GB 模型权重：

```powershell
python scripts/run_bm25_bge_m3_experiment.py --stage bm25
python scripts/run_bm25_bge_m3_experiment.py --stage rerank --batch-size 2 --max-length 1024
```

RTX 4060 8GB 建议使用 `--batch-size 2`。结果输出到 `dataset/retrieval/test_30/`：

- `bm25_top200_30.jsonl`：30 份简历各自完整的 BM25 Top200。
- `bge_m3_reranked_top200_30.jsonl`：相同候选经过 BGE-M3 余弦相似度重排后的顺序。
- `resume_job_silver_30.jsonl`：6000 个简历-岗位对的可解释银标。
- `resume_job_rankings_30.csv`：适合 Excel/WPS 查看和筛选的扁平排名表。
- `experiment_summary.json`：运行耗时、相似度、排名变化和银标分布统计。

银标是自动规则标签，只用于开发、抽样和人工金标候选池构造，不能当作最终测试真值。

## JD 技能抽取与标准化

该步骤位于统一岗位主表生成之后、图谱和人工金标之前。它不会修改现有 BM25/BGE-M3 实验结果，只是在 `dataset/structured/` 下新增岗位技能结构化输出。

在 `dataset/` 目录执行：

```powershell
npm run extract:job-skills
```

等价于：

```powershell
python scripts/extract_job_skills.py
```

默认输入：

```text
dataset/cleaned/all_jobs_23714_normalized.jsonl
dataset/config/skill_aliases.json
```

默认输出：

```text
dataset/structured/skill_alias_table.csv
dataset/structured/job_skill_mentions.jsonl
dataset/structured/job_skill_mentions.csv
dataset/structured/job_skill_extract_report.json
```

`job_skill_mentions.jsonl` 一行表示一个岗位中的一个技能命中，包含标准技能名和证据句，例如：

```json
{
  "job_id": "job_2e8a95fed4174a85fb3a",
  "job_title": "AI Infra高级工程师",
  "raw_skill": "PyTorch",
  "normalized_skill": "PyTorch",
  "category": "数据与算法",
  "span_text": "PyTorch",
  "span_start": 11,
  "span_end": 18,
  "skillspan_label": "knowledge",
  "skill_type": "required",
  "evidence_sentence": "对接主流AI框架（如PyTorch、TensorFlow）",
  "confidence": 1.0,
  "match_method": "dictionary"
}
```

第一版采用确定性词典匹配，不调用 LLM。设计上借鉴 SkillSpan 这类 span-level 数据集：抽取结果必须来自 JD 原文，并保留 `evidence_sentence`、`span_text`、`span_start`、`span_end`，方便后续人工抽查、金标标注和图谱导入。

详细说明见：

```text
dataset/structured/README_job_skill_extraction.md
```

## Neo4j Job-Skill 图谱与 UI

该步骤位于 `JD 技能抽取与标准化` 之后，用 `structured/job_skill_mentions.jsonl` 构建第一版岗位-技能图谱。

生成本地图谱 JSON：

```powershell
npm run graph:build
```

如需导入 Neo4j，先配置连接信息后执行：

```powershell
$env:NEO4J_URI="bolt://localhost:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="你的密码"
npm run graph:import
```

打开本地 UI：

```powershell
npm run graph:ui
```

然后访问：

```text
http://localhost:8010/ui/job_skill_graph.html
```

详细说明见：

```text
graph/README_neo4j_job_skill_graph.md
```

