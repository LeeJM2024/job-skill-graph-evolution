# JD 大样本测试数据流说明

本目录是测试专用 run：`large_test_20260807_19_23_per_job_month`。

这份数据属于上游大流生成结果，用于审计和重建公司大流版本，不应直接覆盖 `dataset/job_update/company_job_update/data/versions` 下的正式运行版本。

## 生成目标

- 时间范围：2024-12 至 2026-07，共 20 个月。
- 标准岗位：73 个，来自生成系统输入词典和公司版本词典。
- 每个岗位每个月 JD 数：19 至 23 条。
- 最终事件流：30720 条 JD。

## 主要文件

- `job_update_event_stream_large_test_19_23_per_job_month.csv`：带有明确测试标识的大样本 JD 数据流。
- `job_skill_monthly_frequency_answer.csv`：由事件流重新计算出的技能月度频率答案表。
- `job_demand_monthly_answer.csv`：由事件流重新计算出的岗位月度需求答案表。
- `large_test_generation_note.json`：生成参数和测试标记。
- `derived/`：为 Web 前端直接展示准备的生命周期、迁移、岗位画像快照、画像差异和当前画像派生表。

## 基础库检查

生成前已检查：生成器使用的标准岗位词典与公司正式版本词典一致。

- 生成器输入：`dataset/岗位数据流生成与评测系统/data/input/standard_job_title_dictionary.csv`
- 公司版本词典：`dataset/job_update/company_job_update/data/versions/company_large_v2/standard_job_title_dictionary.csv`
- 二者 SHA256 前 16 位均为：`1E1633C05591A6F7`

## 测试补齐说明

原始生成输入中，`大数据开发工程师` 和 `FPGA工程师` 对生成器支撑不足，无法直接满足“每个岗位每个月都有 19 至 23 条 JD”的要求。因此本 run 在测试 source 文件中补充了少量兜底模板，并在技能池中补齐了对应岗位技能。

这部分补齐只存在于本测试 run，不影响正式公司版本文件。

## 校验结果

- 事件流行数：30720
- 覆盖岗位数：73
- 覆盖月份数：20
- 岗位-月份组合数：1460
- 每个岗位-月份 JD 数最小值：19
- 每个岗位-月份 JD 数最大值：23
- 缺失 source 岗位数：0
- 缺失技能计划岗位-月份数：0
- 非法岗位-技能组合数：0

说明：事件流 CSV 的职责和要求字段中包含换行文本，不能用普通文本行数统计 JD 数；应使用 CSV 解析后的记录数或 `manifest.json` 中的 `event_stream_rows`。
