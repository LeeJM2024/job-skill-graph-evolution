# 既有岗位更新系统原型

这个目录实现“新招聘启事输入后，先路由到岗位大族和标准岗位，再维护既有岗位技能频率”的第一版系统骨架。

当前版本先完成主流程：

- 岗位大族直接使用 `standard_job_title_dictionary.csv` 中的 `standard_category`。
- 默认大族阈值是 `0.6`，具体岗位阈值默认是 `0.85`。
- 路由强制使用 `shibing624/text2vec`，默认模型是 `shibing624/text2vec-base-chinese`。
- 技能抽取和归一化暂不内置，只保留接口。
- 可以通过 `--extract-skills` 调用已有 `dataset/skill_extract`，不传该参数时仍可手动传入技能。
- 同时维护 `monthly_*` 当月趋势和 `cumulative_*` 累计稳定性。

## 输入技能结构

后续技能抽取模块只需要把结果转成下面的列表结构即可：

```json
[
  {
    "raw_skill": "大语言模型",
    "normalized_skill": "LLM",
    "category": "AI算法",
    "skill_type": "required",
    "confidence": 0.92,
    "evidence_field": "job_requirement",
    "evidence_sentence": "熟悉大语言模型训练和推理优化",
    "span_text": "大语言模型",
    "metadata": {}
  }
]
```

当前 `PassthroughSkillNormalizer` 的规则很简单：优先使用 `normalized_skill`，否则使用 `raw_skill`。以后人工强制规则、技能本体映射和大模型 API 辅助判断都可以替换 `SkillNormalizer` 接口。

## 接入已有 skill_extract

`dataset/skill_extract/extractor.py` 提供了稳定的程序接口：

```python
from skill_extract import JobSkillExtractor, SkillExtractionConfig

extractor = JobSkillExtractor(SkillExtractionConfig(provider="deepseek"))
result = extractor.extract(
    job_id="manual_001",
    job_title="大模型算法工程师",
    requirements="熟悉大语言模型训练、推理优化和 Python。",
)

print(result.job_skills)
```

`job_update` 通过 `ExistingSkillExtractAdapter` 把 `result.job_skills` 转成 `SkillMention`。后续如果 `skill_extract` 内部继续调整 prompt、规则、缓存或大模型供应商，只要维持 `JobSkillExtractor.extract(...) -> SkillExtractionResult.job_skills` 这个边界，`job_update` 不需要改。

## 命令示例

路由一个岗位标题：

```powershell
python -m job_update.cli route `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --job-title "大模型算法工程师"
```

使用 text2vec 路由：

```powershell
python -m job_update.cli route `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --job-title "大模型算法工程师" `
  --text2vec-model "shibing624/text2vec-base-chinese"
```

重建频率表：

```powershell
python -m job_update.cli rebuild-frequency `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.rebuilt.csv"
```

处理一条新招聘启事。若路由结果是 `existing_job`，会追加事件流并重建频率表；若是 `new_family` 或 `potential_new_job`，只返回判断结果，不写入既有岗位更新。

```powershell
python -m job_update.cli process-one `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --frequency-output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.csv" `
  --job-id "manual_001" `
  --month "2026-07" `
  --job-title "大模型算法工程师" `
  --skills-json "[{\"raw_skill\":\"大语言模型\",\"normalized_skill\":\"LLM\"},{\"raw_skill\":\"Python\"}]" `
  --dry-run
```

调用已有 `skill_extract` 抽取技能再更新：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
python -m job_update.cli process-one `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --frequency-output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.csv" `
  --job-id "manual_002" `
  --month "2026-07" `
  --job-title "大模型算法工程师" `
  --requirement "熟悉大语言模型训练、推理优化和 Python。" `
  --extract-skills `
  --dry-run
```

## 代码结构

- `job_update/taxonomy.py`：加载标准岗位字典，完成大族和岗位两阶段路由。
- `job_update/similarity.py`：text2vec 相似度后端。
- `job_update/skill_extraction.py`：接入已有 `dataset/skill_extract` 的 adapter。
- `job_update/skill_normalizer.py`：技能归一化接口占位。
- `job_update/frequency_store.py`：事件流追加、月度频率和累计频率重建。
- `job_update/service.py`：串联路由、归一化和既有岗位更新。
- `job_update/cli.py`：命令行入口。
