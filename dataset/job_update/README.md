# 岗位更新系统

`job_update` 是项目的动态更新层。它接收单条招聘 JD，将其归入标准岗位、提取并归一化技能，然后维护时序分析数据和 SQLite 数据库。

## 数据域边界

```text
job_update/
  company_job_update/       公司岗位：月度企业招聘数据
  government_job_update/    政府技术岗位：真实发布时间、年度招聘周期
  shared/                   公共算法工具，不保存任何业务数据
```

公司岗位与政府岗位完全独立：各自拥有标准岗位词典、技能词典、事件流、技能频率表、技能池、生命周期、迁移、岗位画像、待审核队列和 SQLite 数据库。不要把一个数据域的 CSV 传给另一个数据域。

## 共同处理逻辑

1. LLM 清理原始岗位名称中的业务线、职级、项目名等噪声。
2. 只使用清洗后的岗位名称调用 `shibing624/text2vec-base-chinese`，获得岗位大族和标准岗位候选。
3. 分数处于中间区间或候选接近时，向 LLM 发送 Top-K 进行二次裁决。
4. 对确认的既有岗位调用该数据域自己的技能抽取与归一化词典。
5. 更新事件流、月度和累计技能频率、技能池、生命周期、迁移路径、岗位画像以及 SQLite。

自动模式直接采用满足阈值的系统结论；人工确认模式将岗位 Top-K 和技能结果写入待审核队列，由用户确认后入库。

## 入口

| 场景 | 说明 |
| --- | --- |
| [公司岗位系统](company_job_update/README.md) | 企业 JD 的初始基线与后续月度更新 |
| [政府岗位系统](government_job_update/README.md) | 政府技术岗位的真实年度事件流与更新 |
| [Web 控制台](../web_app/README.md) | 两个数据域共用的可视化、人工确认和画像编辑入口 |

## 验证

从 `dataset` 目录执行：

```powershell
python -m pytest .\job_update\company_job_update\tests .\job_update\government_job_update\tests -q
```

## SQLite 说明

每个数据域都将当前正式状态持久化在自己的 SQLite 文件中，并保留 CSV 作为可读、可审计和可提交的数据快照：

```text
company_job_update/data/base/job_update.db
government_job_update/data/base/government_job_update.db
```

Web 中的“岗位画像人工优化”写入相应数据库的人工覆盖层。它会立即影响当前画像展示，但不会回写或篡改历史 JD、事件流和月度快照。

## 数据维护规则

| 类别 | 人工修改 | 自动修改 |
| --- | --- | --- |
| 标准岗位体系 | 两个数据域各自的 `standard_job_title_dictionary.csv` | 不自动增加正式标准岗位 |
| 技能体系 | 公司 `company_skill_dictionary.csv`、政府 `government_skill_dictionary.csv` | 不自动写入正式技能词典 |
| 源数据 | 公司基线输入、政府原始技术岗数据、政府初始映射审核结果 | 不自动改写原始源数据 |
| 运行状态 | 不应直接编辑 | 事件流、频率、技能池、生命周期、迁移、岗位画像、审核队列和 SQLite 由系统更新 |

当人工确认了新岗位或新技能时，系统只记录待维护建议。审核人员先更新词典，再对相关 JD 重新处理；不要直接在频率表或技能池中补行。
