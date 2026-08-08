# 公司岗位更新系统

本模块维护企业技术岗位的初始基线和后续单条 JD 动态更新。它使用公司标准岗位词典和公司技能词典，所有数据只写入本目录。

## 单条 JD 流程

```text
原始岗位名称、职责、要求
-> LLM 标题清洗
-> text2vec 岗位大族 / 标准岗位 Top-K
-> 中间分数时 LLM 二次裁决
-> 公司技能抽取与归一化
-> 自动入库或人工确认
-> 事件流、频率、技能池、生命周期、迁移、画像、SQLite 同步更新
```

默认阈值：岗位大族 `0.58`，标准岗位 `0.82`。分数未达到自动条件、多个候选接近，或使用 `--mode manual` 时，记录进入待审核队列而不写入正式事件流。

## 公司版本数据

公司正式运行数据位于 `data/versions/<selected_version>/`。当前默认版本由
`COMPANY_DATA_VERSION` 决定，系统运行时只读取选定版本：

| 文件 | 用途 |
| --- | --- |
| `standard_job_title_dictionary.csv` | 标准岗位与岗位大族 |
| `job_update_event_stream.csv` | 已入库的 JD 事件 |
| `job_skill_monthly_frequency.csv` | 当月趋势与累计稳定性频率 |
| `skill_pool.csv` | 技能首次出现、所属岗位、次数和来源 |
| `skill_lifecycle.csv` | 新兴、活跃、稳定、衰退、废弃等状态 |
| `skill_migration.csv` / `skill_job_monthly_spread.csv` | 技能在岗位之间的扩散路径 |
| `job_profile_snapshots.csv` / `job_profile_diff.csv` | 岗位画像版本和差异 |
| `job_current_profile_system.csv` | 当前岗位画像 |
| `job_update.db` | 上述正式状态和审核记录的 SQLite 数据库 |

`skill_extract/company_skill_dictionary.csv` 是公司技能抽取与归一化的唯一正式词典。`normalized_skill` 是频率统计节点，`kg_display_skill` 是知识图谱展示分类。

## 哪些文件可以人工修改

只人工维护以下两类文件：

- `data/versions/<selected_version>/standard_job_title_dictionary.csv`：新增、合并或调整公司标准岗位、岗位大族和匹配关键词。
- `skill_extract/company_skill_dictionary.csv`：新增技能、修改别名归一化结果或修改 `kg_display_skill` 分类。

不要手工编辑 `job_update_event_stream.csv`、`job_skill_monthly_frequency.csv`、`skill_pool.csv`、生命周期/迁移/画像 CSV 或 `job_update.db`。它们是派生状态：正常单条 JD 提交、人工确认或以下重建命令会自动更新它们。修改正式词典后，应重处理受影响 JD 或在受控场景下重建基线，而不是直接改统计结果。

## 提交一条 JD

在本目录运行。`job_id` 未传入时自动生成，基础路径均有默认值。

```powershell
cd "B:\揭榜挂帅\dataset\job_update\company_job_update"

python -m core.cli submit-one `
  --month "2026-08" `
  --job-title "大模型应用后端工程师（Agent 方向）" `
  --responsibility "负责智能应用后端服务、模型能力接入和线上稳定性建设。" `
  --requirement "熟悉 Python、FastAPI、MySQL、Redis、LangChain、Function Calling 和 Kubernetes。" `
  --dry-run
```

- 加上 `--dry-run`：完整计算和日志输出，但不改任何基础数据。
- 删除 `--dry-run`：满足既有岗位条件时写入正式 CSV 和 `job_update.db`。
- 加上 `--mode manual`：无论自动分数如何，均写入人工审核队列，等待 Web 或 CLI 确认。

职责和要求也可使用 `--responsibility-file`、`--requirement-file` 读取文本文件。

## 人工审核与维护

优先使用 Web 控制台进行人工确认。命令行也可查看和处理审核记录：

```powershell
python -m core.cli --help
```

对于已确认的新增岗位或词典更新，先完成正式词典维护，再重新处理对应 JD；不要将未经审核的新技能直接写进 `company_skill_dictionary.csv`。

## 数据库与重建命令

```powershell
python -m core.cli init-db
python -m core.cli export-csv
python -m core.cli rebuild-frequency --event-stream data/versions/<selected_version>/job_update_event_stream.csv --output data/versions/<selected_version>/job_skill_monthly_frequency.csv
python -m core.cli rebuild-lifecycle
python -m core.cli rebuild-migration
python -m core.cli rebuild-profile
python -m core.cli rebuild-current-profile
```

这些命令用于受控维护。日常单条 JD 入库会自动同步所有时序产物，无需手动逐项重建。

## 初始基线

公司初始事件流来自 [岗位数据流生成与评测系统](../../岗位数据流生成与评测系统/README.md)。它仅用于重新构建基线或验证，不应在每次用户提交 JD 时运行。

## 大流源数据

公司大流的源数据由岗位数据流生成与评测系统维护，位置为：

```text
dataset/岗位数据流生成与评测系统/outputs/company_large_v2/
```

它包含大流原始事件、答案表和用于审计的派生结果。重建公司大流版本时，
由 `promote_large_v2.py` 读取其中的原始事件流，重新生成：

```text
dataset/job_update/company_job_update/data/versions/company_large_v2/
```

正式系统和 Web 只读取 `data/versions/` 下选定的公司版本，不直接读取上游生成目录。
# Company data versions

The company update system keeps independent, complete data versions. The
active version is selected by the programmer or deployment configuration, not
by the Web user:

```powershell
$env:COMPANY_DATA_VERSION = "company_large_v2"
python -m company_job_update.core.cli submit-one --month "2026-08" --job-title "..."
```

Available versions are under `data/versions/`:

- `company_base_v1`: immutable copy of the previous company baseline.
- `company_large_v2`: the larger market-based generated baseline, with its own
  event stream, frequency tables, skill pool, lifecycle, migration, profiles,
  and `job_update.db`.

Every company CLI process and Web backend process reads only the selected
version. A single JD submission updates that version's CSV files and SQLite
database only. The Web UI does not expose a company-version selector.
