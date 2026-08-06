# DeepSeek/API 版 JD 技能抽取

这个流程用于“新招聘启事输入后，直接调用 LLM API 做技能抽取”。当前保留两个版本：DeepSeek 版和 GPT/OpenAI-compatible 版，输出格式对齐现有 `job_skill_mentions*.csv/jsonl`。

## 位置

```text
新 JD
 -> DeepSeek 或 GPT/OpenAI-compatible API 技能抽取
 -> skill_extract/output/job_skill_mentions_deepseek.csv/jsonl
 -> skill_extract/output/job_skill_mentions_gpt.csv/jsonl
 -> 按岗位聚合的 *_by_job.csv/jsonl
 -> 后续可用于 Neo4j 岗位-技能图谱
```

## 规则来源

脚本使用：

- 人工拍板的规则，例如 `大模型 -> LLM`、`提示词 -> prompt工程`、`多智能体 -> multi-agent`、`后训练 -> 大模型后训练`、`数据技术语境 -> 数据工程`、`编译器后端 CodeGen 不算后端开发`。
- 干净金标文件：`skill_extract/job_skill_gold/job_skill_gold_clean.csv`

脚本会从金标 CSV 中读取已确认的 `normalized_skill` 和 `category`，作为 API 抽取时的优先技能本体。如果 clean 版不存在，会自动退回读取原始审稿表 `job_skill_gold_ai_reviewed_all.csv`。

如果需要重新生成 clean 版：

```powershell
python skill_extract/job_skill_gold/build_job_skill_gold_clean.py
```

## 命令

DeepSeek 版：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
npm run extract:job-skills-deepseek -- --limit 20
```

也可以写入本地 `dataset/.env`

GPT/OpenAI-compatible 版：

```powershell
$env:GPT_API_KEY="你的 key"
$env:GPT_BASE_URL="https://你的中转站地址/v1"
$env:GPT_MODEL="gpt-4.1-mini"
npm run extract:job-skills-gpt -- --limit 20
```

如果你的中转站不是 `/v1`，而是直接给完整接口，也可以传：

```powershell
npm run extract:job-skills-gpt -- --base-url "https://你的中转站地址/v1" --model "你的模型名" --limit 20
```

只检查输入和 prompt，不调用 API：

```powershell
npm run extract:job-skills-deepseek -- --limit 2 --dry-run
npm run extract:job-skills-gpt -- --limit 2 --dry-run
```

直接输入一段新的 JD 文本：

```powershell
npm run extract:job-skills-deepseek -- --jd-title "AI大模型推理工程师" --single-job-id manual_001 --jd-text "负责大模型推理服务化引擎开发，优化KV Cache、量化和高吞吐低时延性能。"
```

评测两个版本：

```powershell
npm run eval:job-skills-deepseek -- --split test --limit 50
npm run eval:job-skills-gpt -- --split test --limit 50
```

建议评测时按 20 条一批跑，避免一次请求太长导致模型返回 JSON 被截断或格式破损：

```powershell
npm run eval:job-skills-deepseek -- --split test --offset 0 --limit 20
npm run eval:job-skills-deepseek -- --split test --offset 20 --limit 20
npm run eval:job-skills-deepseek -- --split test --offset 40 --limit 20
```

当前公开版默认版本是 `job_skill_api_v1_2026_07_12`。流程不依赖固定20条输入：一次任务可以只有1条句子，也可以是一份包含多条句子的完整 JD。

每次任务按以下顺序执行：

```text
原始任务
 -> DeepSeek 单次语义抽取
 -> 项目强制字面规则和 gold ontology 字面技能补漏并归一
 -> 边界过滤、校验、去重后输出
```

强制字面规则保证已经拍板的显式触发不依赖模型运气，例如 `大模型 -> LLM`、`算子 -> 算子开发`、`分布式 -> 分布式系统`。gold ontology 中原文直接出现的具体技能（如 Java、Rust、Deep Learning）也会自动补齐。`AI基础设施`、`模型服务化`、`SRE` 等需要上下文理解的技能由单次 DeepSeek 抽取结合 gold 语义规则和 few-shot 完成。

最终还有一层负向边界过滤，用于删除普通部署流程被误抽成模型服务化、全栈职位名被自动拆成前后端、业务场景举例被误抽成推荐/检索算法等无依据结果。

每个任务只调用一次 API，之后的补漏、归一、边界过滤和去重均在本地完成。

流程还会从人工 gold 的 train split 中构建语义归纳规则和 few-shot 示例。当前注入 17 类语义规则，每类最多 3 条代表性 gold 示例；测试句本身不会进入 prompt。DeepSeek 并不会被永久训练，而是在每次请求中读取这些规则和示例后完成抽取。

语义规则重点覆盖：`AI基础设施`、`模型服务化`、`SRE`、`高性能计算`、`数据工程`、`bug分析`、`推荐系统算法`、`检索排序算法`、`后端开发`、`前端架构设计`、`AI工作流设计`、`游戏引擎开发`、`大模型安全`、`智能体安全`、`大模型评测`、`模型训练`、`模型推理`。

注意：`span_text` 只是原文证据，`normalized_skill` 才是最终技能名。

评测报告里优先看 `sentence_skill`，它只比较同一句里是否抽到了相同的 `normalized_skill`，不看 `span_start/span_end`。`strict_span_skill` 只是调试用，会把 span 起止位置不一致也算错。

| 原文/API可能返回 | 修正后的 span_text | 最终 normalized_skill |
| --- | --- | --- |
| 基座大模型、AI大模型 | 大模型 | LLM |
| llm大模型 | llm | LLM |
| UE5引擎 | UE5 | UE |
| C/C++ | C++ | C++ |
| 分布式训练、分布式推理、分布式计算 | 分布式 | 分布式系统 |
| Spark、Flink、Hadoop、ETL | 原文触发词 | 数据工程 |

评测输出文件名会带上版本和 offset，方便比较不同规则版本的效果。

## 输出

默认输出：

```text
skill_extract/output/job_skill_mentions_deepseek.csv
skill_extract/output/job_skill_mentions_deepseek.jsonl
skill_extract/output/job_skill_mentions_deepseek_by_job.csv
skill_extract/output/job_skill_mentions_deepseek_by_job.jsonl
skill_extract/output/job_skill_mentions_deepseek_report.json

skill_extract/output/job_skill_mentions_gpt.csv
skill_extract/output/job_skill_mentions_gpt.jsonl
skill_extract/output/job_skill_mentions_gpt_by_job.csv
skill_extract/output/job_skill_mentions_gpt_by_job.jsonl
skill_extract/output/job_skill_mentions_gpt_report.json
```

`job_skill_mentions_*.csv/jsonl` 是句子级技能证据：同一岗位中的同一技能可以有多条记录。每次抽取完成后，脚本会同时生成 `*_by_job.csv/jsonl`，以 `(job_id, normalized_skill)` 合并为一条岗位-技能关系。汇总记录保留 `mention_count`、`max_confidence` 和全部 `evidence`，其中 CSV 将证据列表序列化为 JSON 字符串。

脚本会校验 API 返回的 `span_text` 必须真实出现在原句中，否则写入 report 的 `rejected_samples`，不进入正式 mentions。

## 缓存

默认缓存：

```text
skill_extract/cache/job_skill_extract_api_cache.jsonl
```

同一个模型、同一组句子、同一版 gold ontology 会复用缓存，避免重复请求。
