# 既有岗位更新系统

这个目录实现“新招聘启事输入后，先路由到岗位大族和标准岗位，再维护既有岗位技能频率”的流程。

当前边界：

- 岗位大族使用 `standard_job_title_dictionary.csv` 中的 `standard_category`。
- 岗位路由强制使用 `shibing624/text2vec`，默认模型是 `shibing624/text2vec-base-chinese`。
- `job_update` 不做技能抽取，也不做技能归一化。
- `process-one` 在识别为既有岗位后，默认调用 `dataset/skill_extract`。
- `skill_extract` 必须返回最终字段：`normalized_skill` 和 `kg_display_skill`。
- 频率表只使用 `normalized_skill` 计算。
- `kg_display_skill` 不参与频率计算，但会在结果中继续携带，供后续知识图谱使用。

## 技能结果边界

`job_update` 只接受最终技能结构：

```json
[
  {
    "normalized_skill": "Kubernetes",
    "kg_display_skill": "云原生",
    "skill_type": "required",
    "confidence": 0.95,
    "evidence_field": "job_requirement",
    "evidence_sentence": "熟悉 Kubernetes 架构和生态。"
  }
]
```

调试时也可以只传原始技能关键词，但它们不会直接进入频率表；系统会先调用
`skill_extract.normalizer` 转成最终 `normalized_skill + kg_display_skill`。

## 命令示例

路由一个岗位标题：

```powershell
python -m job_update.cli route `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --job-title "AI Infra工程师"
```

处理一条新招聘启事。若路由结果是 `existing_job`，系统会调用 `skill_extract` 产出最终技能，再用 `normalized_skill` 更新事件流和频率表；若是 `new_family` 或 `potential_new_job`，不会更新频率表。

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
python -m job_update.cli process-one `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --frequency-output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.csv" `
  --job-id "manual_001" `
  --month "2026-07" `
  --job-title "AI Infra工程师" `
  --requirement "熟悉 Kubernetes、Docker、RDMA 和高性能计算。" `
  --dry-run
```

调试时可以直接传原始技能关键词；这些关键词会在路由确认是既有岗位后，进入
`skill_extract.normalizer`：

```powershell
python -m job_update.cli process-one `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --frequency-output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.csv" `
  --job-id "manual_debug_001" `
  --month "2026-07" `
  --job-title "AI Infra工程师" `
  --skills "Kubernetes; RDMA" `
  --dry-run
```

如果已经有完整最终技能结构，也可以用 JSON 文件传入：

```powershell
$skillsFile = "$env:TEMP\job_update_skills.json"
@'
[
  {"normalized_skill":"Kubernetes","kg_display_skill":"云原生"},
  {"normalized_skill":"RDMA","kg_display_skill":"高性能网络"}
]
'@ | Set-Content -Encoding UTF8 $skillsFile

python -m job_update.cli process-one `
  --title-dictionary "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\standard_job_title_dictionary.csv" `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --frequency-output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.csv" `
  --job-id "manual_debug_001" `
  --month "2026-07" `
  --job-title "AI Infra工程师" `
  --skills-json-file $skillsFile `
  --dry-run
```

重建频率表：

```powershell
python -m job_update.cli rebuild-frequency `
  --event-stream "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_update_event_stream.csv" `
  --output "C:\Users\LeeJM\Desktop\揭榜挂帅\岗位数据集\job_skill_monthly_frequency.rebuilt.csv"
```

CLI 默认输出阶段日志到 stderr，最终 JSON 输出到 stdout。只需要最终 JSON 时可以加 `--quiet`。

## 代码结构

- `job_update/taxonomy.py`：岗位大族和标准岗位两阶段路由。
- `job_update/similarity.py`：text2vec 相似度后端。
- `job_update/skill_extraction.py`：调用 `dataset/skill_extract` 的 adapter。
- `job_update/skill_normalizer.py`：只校验并去重最终技能，不做归一化。
- `job_update/frequency_store.py`：事件流追加、月度频率和累计频率重建。
- `job_update/service.py`：串联路由、技能抽取、频率更新。
- `job_update/cli.py`：命令行入口。
