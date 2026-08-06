# 政府技术岗位更新系统

本模块服务已筛选的政府计算机相关岗位。它不使用公司岗位的标准岗位词典、技能词典或数据库；政府招聘数据保留原始发布时间，并按真实年度招聘周期分析。

## 数据与时间口径

政府岗位源数据位于：

```text
government_jobs_2024_2026_tech_final.csv
```

初始状态已由人工审核过的岗位映射和政府专属技能词典构建。政府数据不使用公司岗位数据流生成系统，不为历史岗位虚构月度时间点。

`data/base/` 的主要文件：

| 文件 | 用途 |
| --- | --- |
| `standard_job_title_dictionary.csv` | 政府标准岗位与岗位大族 |
| `government_job_event_stream.csv` | 正式政府岗位事件流，带来源和真实时间 |
| `government_job_skill_monthly_frequency.csv` | 政府岗位技能频率 |
| `government_skill_pool.csv` | 政府技能池 |
| `government_skill_lifecycle.csv` | 按年度招聘周期判断的技能状态 |
| `government_skill_migration.csv` | 政府岗位间技能扩散 |
| `government_job_current_profile_system.csv` | 当前政府岗位画像 |
| `government_job_update.db` | 独立 SQLite 数据库和审核记录 |

## 哪些文件可以人工修改

政府域允许人工维护的文件只有：

- `government_jobs_2024_2026_tech_final.csv`：已筛选的政府技术岗位源数据。
- `data/base/standard_job_title_dictionary.csv`：政府标准岗位、岗位大族和匹配关键词。
- `skill_extract/government_skill_dictionary.csv`：政府技能抽取和归一化规则。
- `data/base/government_initial_job_assignment.csv`：初始历史岗位映射的人工审核结果。

不要手工编辑正式事件流、技能频率、技能池、生命周期、迁移、画像 CSV 或 `government_job_update.db`。这些均由 `bootstrap-initial-state`、`submit-one`、人工审核确认或 `rebuild-analytics` 自动维护。源数据或映射审核结果变更后，应按“初始状态重建”流程重建，而不是直接篡改派生统计表。

## 单条政府 JD 流程

```text
原始政府岗位 JD
-> 政府场景 LLM 标题清洗
-> 仅用清洗后的标题做 text2vec Top-K 匹配
-> 分数中间区间时政府场景 LLM 二次裁决
-> 政府技能抽取与归一化
-> 自动入库或人工确认
-> 更新政府事件流、频率、技能池、年度生命周期、迁移、画像、SQLite
```

系统保留 `source_name`、`publish_time`、`recruitment_year`、机构、部门、地点和来源 URL 等溯源字段。

## 提交一条政府 JD

从 `dataset/job_update` 目录运行：

```powershell
cd "B:\揭榜挂帅\dataset\job_update"

python -m government_job_update.core.cli submit-one `
  --month "2026-10" `
  --job-title "某市数据资源管理局信息系统运维一级主任科员及以下" `
  --responsibility "负责政务信息系统建设、运行维护和数据治理工作。" `
  --requirement "计算机相关专业，掌握信息系统建设与运维、网络与信息安全基础。" `
  --source-name "2026 年政府公开招录" `
  --publish-time "2026-10-15" `
  --recruitment-year "2027" `
  --government-agency "某市数据资源管理局" `
  --location "某市" `
  --dry-run
```

- `--dry-run` 只预览流程和候选，不写入正式数据。
- 删除 `--dry-run` 后，自动模式仅在系统确认既有岗位时写入政府正式数据。
- 使用 `--mode manual` 时，JD 和技能候选进入政府专属审核队列，由用户确认后入库。

## 初始状态重建

仅在更换政府源数据、完成映射审核或更新政府技能词典后执行。日常使用不需要重新构建。

```powershell
cd "B:\揭榜挂帅\dataset\job_update"
python -m government_job_update.core.cli build-event-stream
python -m government_job_update.core.cli build-initial-assignment
python -m government_job_update.core.cli export-initial-assignment-review
python -m government_job_update.core.cli bootstrap-initial-state
```

先审核 `government_initial_job_assignment.csv` 和导出的低置信度审计结果，再执行 `bootstrap-initial-state`。该操作会重建政府基线，应在版本控制中明确记录。

## 数据库与审核

```powershell
python -m government_job_update.core.cli init-db
python -m government_job_update.core.cli export-csv
python -m government_job_update.core.cli rebuild-analytics
python -m government_job_update.core.cli list-reviews
```

Web 控制台提供更完整的岗位 Top-K 选择和技能编辑界面。公司与政府审核队列相互独立。
