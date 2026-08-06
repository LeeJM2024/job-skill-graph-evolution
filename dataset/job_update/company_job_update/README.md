# 岗位技能更新系统

本系统用于读取岗位招聘事件流，分析岗位月度需求和岗位-技能月度频率，并可与“岗位数据流生成系统”产出的标准答案表进行自动比对。

当前支持两种工作模式：

- 数据流工作模式：读取“岗位数据流生成系统”的某一次 `run` 结果，输出命名与数据流系统的 `run_id` 保持一致。
- 手动工作模式：人工把 CSV 放入指定输入工作区，系统读取后分析，输出命名为 `manual_YYYYMMDD_HHMM`，时间戳精确到分钟。

## 单条招聘启事更新流程

面向真实用户输入时，推荐使用 `submit-one`。用户只需要提供岗位名称、月份、岗位职责和岗位要求；`job_id` 会自动生成，基础数据文件默认读取 `data/base/`。

系统默认流程：

```text
1. 调用大模型清洗岗位名称
2. 使用 shibing624/text2vec 计算标准岗位相似度
3. 高置信命中既有岗位时直接路由
4. 中间分数样本调用大模型进行二次裁决
5. 若大模型无法明确裁决但 Top1 相似度足够高，则取 Top1 作为既有岗位
6. 调用 skill_extract 获取归一化后的技能和技能大族
7. 更新事件流、岗位技能月度频率表和技能池
```

默认路由参数：

```text
category_threshold = 0.58
job_threshold = 0.82
tie_delta = 0.03
llm_job_floor = 0.58
llm_top_jobs = 20
llm_accept_rank_limit = 1
llm_selected_job_floor = 0.75
llm_min_confidence = 0.80
llm_uncertain_take_top1_threshold = 0.82
```

示例：

```powershell
python -m core.cli submit-one `
  --month "2026-07" `
  --job-title "《无畏契约手游》-前端开发工程师" `
  --responsibility $resp `
  --requirement $req `
  --dry-run
```

## SQLite 数据库

系统默认数据库文件：

```text
data/base/job_update.db
```

初始化数据库：

```powershell
python -m core.cli init-db
```

该命令会从当前 4 个 base CSV 导入：

```text
data/base/standard_job_title_dictionary.csv
data/base/job_update_event_stream.csv
data/base/job_skill_monthly_frequency.csv
data/base/skill_pool.csv
```

`submit-one` 和 `process-one` 默认会在成功写入 CSV 后同步写入 SQLite；如果结果不是 `existing_job`，系统也会把本次岗位输入和路由结果写入数据库日志。

从数据库导出回 CSV：

```powershell
python -m core.cli export-csv
```

当前版本保留 CSV 作为可读、可提交的数据文件，SQLite 作为本地数据库层。后续切换 PostgreSQL 时，可以沿用同一组表结构和命令语义。

## 目录结构

```text
core/
core/       Python 包源码
  tests/                         测试
  outputs/
    analysis_runs/<run_id>/      数据流模式分析结果
    comparison_runs/<run_id>/    数据流模式比对结果
    manual_runs/manual_*/        手动模式结果
  README.md
```·

## 输入输出概览

### 主要输入

事件流 CSV：

```text
job_id
month
standard_job
job_title
job_responsibility
job_requirement
skills
```

标准岗位词表 CSV：

```text
standard_job_title
standard_category
match_keywords
```

技能全集 CSV，可选但强烈建议提供：

```text
standard_job
skill
```

说明：如果不提供技能全集，系统只能统计事件流中实际出现过的技能；如果答案表中包含“计划中存在但最终一次也没抽中”的全 0 技能行，则必须提供技能全集才能对齐。

### 主要输出

分析结果：

```text
job_demand_monthly_analysis.csv
job_skill_monthly_frequency_analysis.csv
analysis_quality_report.json
```

比对结果：

```text
job_demand_diff.csv
skill_frequency_diff.csv
comparison_report.json
```

当 `comparison_report.json` 中满足以下条件时，说明验证通过：

```text
passed = true
job_demand_match_rate > pass_threshold
skill_frequency_match_rate > pass_threshold
pass_threshold = 0.9
```

默认规则是：岗位频率表和技能频率表分别有超过 90% 的数据行匹配，即可判定测试通过。差异行仍会写入 `job_demand_diff.csv` 和 `skill_frequency_diff.csv`，用于继续定位问题。

## 完整一键运行

如果要从“生成数据流”一直跑到“岗位更新系统验证”，推荐使用 `dataset` 根目录下的 Python 测试脚本：

```powershell
cd dataset
python run_full_pipeline.py
```

脚本会自动执行：

```text
1. 检查数据流输入
2. 生成岗位需求计划
3. 生成技能趋势计划
4. 生成事件流
5. 生成标准答案表
6. 调用岗位更新系统分析并比对
```

运行结束后会打印 `passed`、`job_demand_match_rate`、`skill_frequency_match_rate` 和报告路径。退出码含义：

```text
0  流水线运行成功，且验证通过
1  流水线执行失败
2  流水线执行完成，但验证未通过
```

可选参数示例：

```powershell
python run_full_pipeline.py --pass-threshold 0.95
python run_full_pipeline.py --month-start 2024-12 --month-end 2026-07
```

## 模式一：数据流工作模式

该模式用于直接接收“岗位数据流生成系统”生成的数据。

假设数据流系统已有某次运行目录：

```text
..\岗位数据流生成系统\outputs\runs\<run_id>
```

直接运行：

```powershell
# 当前目录应为 dataset
cd job_update\company_job_update

python -m core.cli run-data-stream `
  --run-dir "..\岗位数据流生成系统\outputs\runs\<run_id>" `
  --pass-threshold 0.9
```

系统会自动读取：

```text
<run_id>\job_update_event_stream_generated.csv
<run_id>\skill_trend_design.csv
<run_id>\job_demand_monthly_answer.csv
<run_id>\job_skill_monthly_frequency_answer.csv
```

并自动推断标准岗位词表：

```text
..\岗位数据流生成系统\data\input\standard_job_title_dictionary.csv
```

如果标准岗位词表放在其他位置，可以显式指定：

```powershell
python -m core.cli run-data-stream `
  --run-dir "...\outputs\runs\<run_id>" `
  --title-dictionary "...\standard_job_title_dictionary.csv"
```

### 数据流模式输出

分析结果保存到：

```text
outputs\analysis_runs\<run_id>\
```

比对结果保存到：

```text
outputs\comparison_runs\<run_id>\
```

当前 run 标记：

```text
outputs\current_analysis_run_id.txt
outputs\current_comparison_run_id.txt
```

### 数据流模式验证

查看比对报告：

```powershell
Get-Content -Encoding UTF8 "outputs\comparison_runs\<run_id>\comparison_report.json"
```

重点检查：

```text
passed
pass_threshold
job_demand_match_rate
skill_frequency_match_rate
job_demand_mismatch_count
skill_frequency_mismatch_count
job_demand_missing_actual_rows
skill_frequency_missing_actual_rows
```

如果要恢复为完全匹配才通过，可以把阈值改为 `--pass-threshold 0.999999`，并同时要求两个 diff 文件没有数据行；日常验证建议使用默认的 `0.9`。

如果要只分析、不比对：

```powershell
python -m core.cli run-data-stream `
  --run-dir "...\outputs\runs\<run_id>" `
  --skip-compare
```

## 模式二：手动工作模式

该模式用于人工投放数据文件。

### 1. 创建手动输入工作区

```powershell
cd job_update\company_job_update

python -m core.cli init-manual-workspace `
  --workspace "manual_input_workspace"
```

系统会创建：

```text
manual_input_workspace/
  event_stream/                  放事件流 CSV，必需
  title_dictionary/              放标准岗位词表 CSV，必需
  skill_universe/                放技能全集 CSV，可选
  answers/
    job_demand/                  放岗位需求答案表，可选
    skill_frequency/             放技能频率答案表，可选
```

每个文件夹内最多放一个 CSV。若某个必需文件夹没有 CSV，系统会报错；若一个文件夹内有多个 CSV，系统也会报错，避免读错文件。

### 2. 人工放入文件

必需：

```text
event_stream/*.csv
title_dictionary/*.csv
```

建议：

```text
skill_universe/*.csv
```

如果需要自动验证，还需要：

```text
answers/job_demand/*.csv
answers/skill_frequency/*.csv
```

### 3. 运行手动模式

```powershell
python -m core.cli run-manual `
  --workspace "manual_input_workspace" `
  --month-start 2024-12 `
  --month-end 2026-07 `
  --pass-threshold 0.9
```

如果不传 `--month-start` 和 `--month-end`，系统会根据事件流中出现的月份自动推断范围。

### 手动模式输出

输出保存到：

```text
outputs\manual_runs\manual_YYYYMMDD_HHMM\
```

示例：

```text
outputs\manual_runs\manual_20260717_2154\
```

目录内容：

```text
manual_YYYYMMDD_HHMM/
  analysis/
    job_demand_monthly_analysis.csv
    job_skill_monthly_frequency_analysis.csv
    analysis_quality_report.json
  comparison/
    job_demand_diff.csv
    skill_frequency_diff.csv
    comparison_report.json
  run_manifest.json
```

当前手动 run 标记：

```text
outputs\current_manual_run_id.txt
```

### 手动模式验证

查看当前手动 run：

```powershell
$manualRun = Get-Content -Encoding UTF8 outputs\current_manual_run_id.txt
```

查看比对结果：

```powershell
Get-Content -Encoding UTF8 "outputs\manual_runs\$manualRun\comparison\comparison_report.json"
```

如果没有提供答案表，系统只生成 `analysis/`，不会生成比对报告。

## 底层命令

除两种工作模式外，系统仍保留底层命令，适合调试或单独使用。

### 分析事件流

```powershell
python -m core.cli analyze-event-stream `
  --event-stream "...\job_update_event_stream_generated.csv" `
  --title-dictionary "...\standard_job_title_dictionary.csv" `
  --skill-universe "...\skill_trend_design.csv" `
  --month-start 2024-12 `
  --month-end 2026-07
```

如果不传 `--output-dir`，默认保存到：

```text
outputs\analysis_runs\<run_id>\
```

### 比对答案

```powershell
python -m core.cli compare-answer `
  --actual-job-demand "...\job_demand_monthly_analysis.csv" `
  --expected-job-demand "...\job_demand_monthly_answer.csv" `
  --actual-skill-frequency "...\job_skill_monthly_frequency_analysis.csv" `
  --expected-skill-frequency "...\job_skill_monthly_frequency_answer.csv" `
  --pass-threshold 0.9
```

如果不传 `--output-dir`，默认保存到：

```text
outputs\comparison_runs\<run_id>\
```

### 仅重建技能频率表

```powershell
python -m core.cli rebuild-frequency `
  --event-stream "...\job_update_event_stream.csv" `
  --output "...\job_skill_monthly_frequency.csv"
```

该命令只保留旧版技能频率重建能力，不会生成岗位需求表，也不会做答案比对。

## 输出表字段

### job_demand_monthly_analysis.csv

```text
standard_job
standard_category
month
month_index
monthly_jd_count
cumulative_jd_count
is_active_month
```

### job_skill_monthly_frequency_analysis.csv

```text
month
month_index
standard_job
standard_category
skill
monthly_jd_count
monthly_skill_count
monthly_skill_frequency
cumulative_jd_count
cumulative_skill_count
cumulative_skill_frequency
```

频率统一保留 4 位小数，例如：

```text
0.0000
0.5000
1.0000
```

## 验证结果解释

`comparison_report.json` 字段含义：

```text
passed                         是否通过
pass_threshold                 通过阈值，默认 0.9
job_demand_actual_rows          实际岗位需求分析表行数
job_demand_expected_rows        岗位需求答案表行数
job_demand_matched_rows         岗位需求匹配行数
job_demand_total_compared_rows  岗位需求参与比较的总行数
job_demand_match_rate           岗位需求匹配率
job_demand_mismatch_count       岗位需求差异行数
skill_frequency_actual_rows     实际技能频率分析表行数
skill_frequency_expected_rows   技能频率答案表行数
skill_frequency_matched_rows    技能频率匹配行数
skill_frequency_total_compared_rows 技能频率参与比较的总行数
skill_frequency_match_rate      技能频率匹配率
skill_frequency_mismatch_count  技能频率差异行数
frequency_tolerance             频率比较容差，默认 0.0001
```

差异明细：

```text
job_demand_diff.csv
skill_frequency_diff.csv
```

如果这两个 diff 文件只有表头、没有数据行，说明没有差异。

## 当前已验证结果

已使用数据流系统 run：

```text
run_20260717_202109_seed_20260716
```

验证通过：

```text
job_demand_actual_rows = 1420
job_demand_expected_rows = 1420
job_demand_mismatch_count = 0
job_demand_match_rate = 1.0
skill_frequency_actual_rows = 91380
skill_frequency_expected_rows = 91380
skill_frequency_mismatch_count = 0
skill_frequency_match_rate = 1.0
pass_threshold = 0.9
passed = true
```

也已用手动工作区模拟人工投放同一批文件，输出到：

```text
outputs\manual_runs\manual_20260717_2154\
```

验证同样通过。

## 注意事项

- 数据流模式优先使用 `run-data-stream`，不要手动拼各个路径。
- 手动模式下，每个输入文件夹只放一个 CSV，避免误读。
- 若要和标准答案完全对齐，建议提供 `skill_universe`。数据流系统中可直接使用 `skill_trend_design.csv`。
- 如果没有答案表，系统仍可分析，但不会自动判断 `passed`。
- `traditional_skills` 和 `new_skills` 不应出现在最终事件流中，它们只属于生成系统内部辅助字段。
