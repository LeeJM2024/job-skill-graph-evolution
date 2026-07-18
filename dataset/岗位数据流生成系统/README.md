# 岗位数据流生成系统

本项目用于根据真实招聘数据半合成生成月度岗位招聘事件流，并同步输出可用于系统比对的标准答案表。

## 数据口径

- 时间范围：2024-12 至 2026-07。
- 标准岗位：使用 `data/input/standard_job_title_dictionary.csv` 中的全部 71 个标准岗位。
- 岗位与技能来源：以 `data/input/job_bigcompany_final.csv` 为准。
- 技能阶段辅助：`data/input/new_skills_current_dictionary.csv` 可用于辅助识别新兴技能。
- 最终事件流不输出 `traditional_skills` 与 `new_skills` 字段。

## 目录结构

```text
config/
  generation_config.json        生成参数与随机种子配置
data/
  input/                        输入数据
  intermediate/                 中间文件
docs/
  岗位数据流生成系统设计.md
  完整使用说明.md
outputs/                        运行结果根目录
  runs/<run_id>/                每次执行生成的独立结果文件夹
src/
  generate_event_stream.py      后续生成脚本入口
```

完整运行方式、输入输出说明和校验口径见：

```text
docs/完整使用说明.md
```

## 预期输出

- `outputs/runs/<run_id>/job_update_event_stream_generated.csv`
- `outputs/runs/<run_id>/job_demand_trend_design.csv`
- `outputs/runs/<run_id>/skill_trend_design.csv`
- `outputs/runs/<run_id>/job_skill_monthly_frequency_answer.csv`

## 当前进度

### 第 1 步：输入解析与数据画像

运行命令：

```bash
python src/profile_inputs.py
```

输出文件：

- `outputs/runs/<run_id>/input_profile.csv`：每个标准岗位的真实 JD 样本数、岗位名称数、技能池规模和质量备注。
- `outputs/runs/<run_id>/skill_pool_by_job.csv`：每个标准岗位对应的技能池，以及技能属于传统、新兴、两者重复或未归类。
- `outputs/runs/<run_id>/input_quality_report.json`：输入数据总体质量摘要。

### 第 2 步：岗位需求趋势生成

运行命令：

```bash
python src/generate_job_demand_plan.py
```

输出文件：

- `outputs/runs/<run_id>/job_demand_monthly_plan.csv`：每个标准岗位在每个月的计划 JD 数。
- `outputs/runs/<run_id>/job_demand_trend_design.csv`：每个标准岗位被分配到的岗位需求趋势及活跃月份摘要。
- `outputs/runs/<run_id>/job_demand_quality_report.json`：岗位需求计划的总量、趋势分布和零值月份质量摘要。

注意：如果标准岗位没有真实 JD 样本和技能池，则保留在标准岗位集合与趋势设计表中，但全周期计划 JD 数为 0。

### 第 3 步：技能趋势与技能概率计划生成

运行命令：

```bash
python src/generate_skill_trend_plan.py
```

输出文件：

- `outputs/runs/<run_id>/skill_trend_design.csv`：每个岗位下被选入生成计划的技能及其技能趋势。
- `outputs/runs/<run_id>/skill_monthly_probability_plan.csv`：每个岗位、技能、月份的出现概率计划。
- `outputs/runs/<run_id>/skill_trend_quality_report.json`：技能计划规模、趋势分布和岗位覆盖情况摘要。

注意：第三步只生成技能概率计划，不生成具体 JD。最终事件流仍不会输出 `traditional_skills` 和 `new_skills` 字段。

### 第 4 步：JD 事件流生成

运行命令：

```bash
python src/generate_event_stream.py
```

输出文件：

- `outputs/runs/<run_id>/job_update_event_stream_generated.csv`：最终生成的岗位招聘事件流。
- `outputs/runs/<run_id>/event_stream_quality_report.json`：事件流行数、技能数量分布、字段排除情况和质量检查摘要。

注意：事件流字段严格使用配置中的 `event_stream_fields`，不会输出 `traditional_skills` 与 `new_skills`。

### 第 5 步：答案表生成与最终校验

运行命令：

```bash
python src/build_answer_tables.py
```

输出文件：

- `outputs/runs/<run_id>/job_demand_monthly_answer.csv`：岗位需求月度答案表。
- `outputs/runs/<run_id>/job_skill_monthly_frequency_answer.csv`：技能频率月度答案表。
- `outputs/runs/<run_id>/final_quality_report.json`：最终质量报告。
- `outputs/runs/<run_id>/run_summary.txt`：简要运行摘要。

答案表从最终事件流重新计算得到，用于和业务系统输出结果进行比对。

第 1 步会创建新的 `outputs/runs/<run_id>/` 文件夹，并写入 `outputs/current_run_id.txt`。第 2-5 步会自动读取这个 run id，将同一次执行的所有输出放入同一个文件夹。
