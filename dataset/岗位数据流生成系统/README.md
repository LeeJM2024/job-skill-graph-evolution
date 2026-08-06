# 岗位数据流生成系统

本工具为公司岗位系统生成可复现的初始招聘事件流。它以真实企业 JD、标准岗位词典和技能分类词典为输入，构造用于初始化和验证的月度公司岗位基线。

它不是在线用户提交 JD 的处理入口。基线生成完成后，日常单条 JD 应直接进入 `company_job_update` 或 Web 控制台，动态更新既有基础数据。

## 输入

```text
data/input/job_bigcompany_final.csv
data/input/standard_job_title_dictionary.csv
data/input/company_skill_dictionary_with_type.csv
config/generation_config.json
```

- 企业 JD 提供岗位标题、职责和要求的真实文本。
- 标准岗位词典决定公司岗位体系。
- 技能词典提供规范技能、KG 展示分类及传统/新兴技能标记。
- 配置文件定义时间范围、随机种子和生成参数。

## 人工维护与自动产物

以下文件由维护人员人工更新：

```text
data/input/job_bigcompany_final.csv
data/input/standard_job_title_dictionary.csv
data/input/company_skill_dictionary_with_type.csv
config/generation_config.json
```

`outputs/runs/<run_id>/` 下的所有文件都是命令自动生成的结果，不应人工修改。需要调整生成结果时，应修改输入数据、词典或配置后重新运行完整生成流程。

## 完整生成

从本目录执行以下五步：

```powershell
cd "B:\揭榜挂帅\dataset\岗位数据流生成系统"
python src\profile_inputs.py
python src\generate_job_demand_plan.py
python src\generate_skill_trend_plan.py
python src\generate_event_stream.py
python src\build_answer_tables.py
```

第一步会创建 `outputs/runs/<run_id>/` 并记录当前 `run_id`；后续步骤自动写入同一个 run。运行产物不提交 Git。

也可从 `dataset` 一键完成“生成 + 公司系统验证”：

```powershell
cd "B:\揭榜挂帅\dataset"
python run_full_pipeline.py
```

## 产物

| 文件 | 用途 |
| --- | --- |
| `job_update_event_stream_generated.csv` | 生成后的公司初始 JD 事件流 |
| `job_demand_trend_design.csv` | 岗位需求趋势设计 |
| `skill_trend_design.csv` | 技能趋势设计，仅用于生成与验证 |
| `job_demand_monthly_answer.csv` | 岗位月度需求答案表 |
| `job_skill_monthly_frequency_answer.csv` | 技能月度频率答案表 |
| `final_quality_report.json` | 生成质量报告 |

注意：`skill_trend_design.csv` 不是 `company_job_update` 日常处理单条 JD 所需的输入。日常系统使用自己的 `data/base/` 数据、词典和 SQLite。

## 与公司系统的关系

公司岗位的现有 `data/base/` 基线由本系统的生成结果初始化。对于一个新的 run，可以使用公司系统的验证命令检查事件流与答案表是否一致：

```powershell
cd "B:\揭榜挂帅\dataset\job_update\company_job_update"
python -m core.cli run-data-stream --run-dir "B:\揭榜挂帅\dataset\岗位数据流生成系统\outputs\runs\<run_id>"
```

该命令只生成分析和比对报告，不覆盖公司正式 CSV 或 SQLite。若确实需要整体替换公司基线，应先审查 run 的事件流和答案表，再由维护人员执行受控的数据初始化与 Git 提交。普通用户单条 JD 不执行上述命令。
