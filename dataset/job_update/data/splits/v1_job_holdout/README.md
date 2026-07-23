# v1_job_holdout 数据库切分说明

本目录是在不修改原始 `data/base/` 数据库的前提下，从当前已有岗位数据中切分出的实验数据集。切分目标是模拟“没有真实新岗位数据集”时的新岗位识别场景。

原始数据库仍保留在：

```text
data/base/
```

本次切分结果保存在：

```text
data/splits/v1_job_holdout/
```

## 一、切分目的

当前系统需要验证三类能力：

```text
1. existing_job
   已有岗位的新 JD 能否继续被识别为已有标准岗位。

2. potential_new_job
   岗位大类仍然存在，但具体标准岗位从 base 库中移除后，系统能否识别为“潜在新岗位”。

3. new_family
   整个岗位大类从 base 库中移除后，系统能否识别为“新岗位族”。
```

因此，本次没有按 JD 随机切分，而是按“标准岗位”和“岗位大类”切分。这样可以避免同一个岗位同时出现在 base 库和新岗位数据集中，降低数据泄漏风险。

## 二、原始数据规模

原始 `data/base/` 中包含：

| 数据项 | 数量 |
|---|---:|
| 标准岗位 | 71 |
| 原始事件流 JD | 2335 |
| 原始技能池条目 | 261 |
| 原始岗位-技能频率表行数 | 35432 |

## 三、总体切分结果

| 切分类别 | 含义 | 期望路由标签 | JD 数 |
|---|---|---|---:|
| `base` | 系统可见的基础库 | 不作为评估样本 | 1471 |
| `known_job_increment` | base 已保留岗位的未来增量 JD | `existing_job` | 394 |
| `potential_new_job` | 隐藏具体标准岗位，但保留其岗位大类 | `potential_new_job` | 379 |
| `new_family` | 隐藏整个岗位大类 | `new_family` | 91 |
| 评估集总计 | 上面三类评估样本合集 | 混合标签 | 864 |
| 新岗位训练集 | `potential_new_job + new_family` | 新岗位相关标签 | 470 |

切分后 base 库规模：

| base 文件 | 数量 |
|---|---:|
| base 标准岗位 | 54 |
| base 事件流 JD | 1471 |
| base 重建岗位-技能频率表 | 22103 行 |
| base 重建技能池 | 256 条 |

## 四、切分标准

### 1. base 基础库

`base` 是系统可见的旧岗位库。它由原始数据中未被隐藏、且未被抽作未来增量的 JD 组成。

base 中保留的岗位必须满足：

```text
1. 不属于被整体隐藏的岗位大类；
2. 不属于被隐藏的具体标准岗位；
3. 没有被抽入 known_job_increment。
```

base 库用于模拟系统上线时已经掌握的历史岗位知识。

### 2. known_job_increment

`known_job_increment` 用于测试“已有岗位新增 JD”的更新能力。

划分规则：

```text
1. 只从 base 中保留的标准岗位里抽取；
2. 每个保留岗位按 month、job_id 排序；
3. 样本数不少于 10 的岗位，抽取最后 20% JD；
4. 抽出的 JD 标记为 known_job_increment；
5. 期望路由结果为 existing_job。
```

这样做的含义是：base 中已经有该岗位的历史样本，后续月份的新 JD 应该还能被识别为同一个标准岗位。

### 3. potential_new_job

`potential_new_job` 用于模拟“岗位大类存在，但具体岗位是新岗位”的情况。

划分规则：

```text
1. 从标准岗位词典中移除指定标准岗位；
2. 保留这些岗位所属的大类；
3. 被移除岗位对应的全部 JD 放入 potential_new_job；
4. 期望路由结果为 potential_new_job。
```

这些样本不应被强行归入 base 中的其他已有岗位。它们最适合用来评估系统是否会误把新岗位塞进旧岗位。

本次隐藏的具体标准岗位如下：

| 岗位大类 | 隐藏标准岗位 | JD 数 |
|---|---|---:|
| AI应用 | 大模型应用工程师 | 62 |
| AI算法 | AIGC算法工程师 | 39 |
| AI算法 | 多模态算法工程师 | 45 |
| 基础设施 | DevOps工程师 | 24 |
| 数据 | 数据治理工程师 | 13 |
| 测试质量 | 大模型测试工程师 | 46 |
| 硬件 | 热设计工程师 | 21 |
| 算法 | 搜索算法工程师 | 37 |
| 算法 | 数据挖掘算法工程师 | 15 |
| 芯片 | 芯片验证工程师 | 25 |
| 软件研发 | Go开发工程师 | 31 |
| 软件研发 | Python开发工程师 | 21 |
| 合计 | 12 个隐藏岗位 | 379 |

### 4. new_family

`new_family` 用于模拟“整个岗位大类都是新方向”的情况。

划分规则：

```text
1. 从 base 标准岗位词典中移除整个岗位大类；
2. 该大类下全部标准岗位同步移除；
3. 该大类下全部 JD 放入 new_family；
4. 期望路由结果为 new_family。
```

本次整体隐藏的岗位大类如下：

| 隐藏岗位大类 | 隐藏标准岗位 | JD 数 |
|---|---|---:|
| 多媒体 | 图形图像工程师 | 27 |
| 多媒体 | 音视频工程师 | 17 |
| 机器人 | 机器人算法工程师 | 12 |
| 机器人 | 机器人软件工程师 | 17 |
| 自动驾驶 | 自动驾驶算法工程师 | 18 |
| 合计 | 5 个隐藏岗位 | 91 |

## 五、输出文件说明

### base 文件

```text
base/standard_job_title_dictionary.base_v1.csv
```

切分后的 base 标准岗位词典。已删除：

```text
1. potential_new_job 中隐藏的 12 个标准岗位；
2. new_family 中隐藏的 3 个岗位大类及其 5 个标准岗位。
```

```text
base/job_update_event_stream.base_v1.csv
```

切分后的 base 事件流，只包含 `split = base` 的 1471 条 JD。

```text
base/job_skill_monthly_frequency.base_v1_rebuilt.csv
```

由切分后的 base 事件流重新生成的岗位-技能月度/累计频率表。不是从原始全量频率表简单过滤得到。

```text
base/skill_pool.base_v1_rebuilt.csv
```

由切分后的 base 事件流重建的技能池。`standard_jobs`、`source_job_ids`、`first_seen_job_id`、`last_seen_job_id` 等字段均只基于 base 事件重算。

### datasets 文件

```text
datasets/known_job_increment.labeled.csv
```

已有岗位增量测试集，394 条。期望系统识别为 `existing_job`。

```text
datasets/potential_new_job.labeled.csv
```

同岗位大类下的伪新岗位数据集，379 条。期望系统识别为 `potential_new_job`。

```text
datasets/new_family.labeled.csv
```

全新岗位大类数据集，91 条。期望系统识别为 `new_family`。

```text
datasets/new_position_training_set.labeled.csv
```

新岗位训练集合集，470 条，包含：

```text
potential_new_job：379 条
new_family：91 条
```

```text
datasets/all_evaluation_samples.labeled.csv
```

所有评估样本合集，864 条，包含：

```text
known_job_increment：394 条
potential_new_job：379 条
new_family：91 条
```

### eval 文件

```text
eval/route_expected_labels.csv
```

逐条 JD 的路由期望标签表，适合后续做路由评估。

```text
eval/all_source_events_split_assignment.csv
```

原始 2335 条事件流的完整切分归属表。可以追溯每条 JD 被分到了哪一类。

```text
eval/split_summary_by_job.csv
```

按 `split + 岗位大类 + 标准岗位` 汇总的样本数、月份覆盖、起止月份。

```text
eval/split_summary_by_category.csv
```

按 `split + 岗位大类` 汇总的标准岗位数和 JD 数。

```text
eval/base_analysis_check/
```

对切分后的 base 事件流运行 `analyze-event-stream` 得到的检查输出。

## 六、标注字段说明

所有 `datasets/*.labeled.csv` 文件都包含以下标注字段：

| 字段 | 含义 |
|---|---|
| `split` | 当前样本所属切分类别 |
| `expected_route_status` | 期望路由结果 |
| `split_reason` | 样本被划入该 split 的原因 |
| `original_standard_category` | 原始数据库中的岗位大类 |
| `original_standard_job` | 原始数据库中的标准岗位 |
| `job_id` | 原始 JD 编号 |
| `month` | JD 所属月份 |
| `job_title` | 原始岗位标题 |
| `job_responsibility` | 岗位职责 |
| `job_requirement` | 岗位要求 |
| `skills` | 原始事件流中的技能列表 |

## 七、防数据泄漏处理

本次切分做了以下处理，避免新岗位信息提前进入 base：

```text
1. 隐藏岗位不会出现在 base 标准岗位词典中；
2. 隐藏岗位对应 JD 不会出现在 base 事件流中；
3. base 技能频率表由 base 事件流重建，不沿用原始全量频率表；
4. base 技能池由 base 事件流重建，来源 job_id 只来自 base；
5. base 和评估集之间没有 job_id 交叉；
6. 评估集中没有重复 job_id。
```

校验结果：

| 校验项 | 结果 |
|---|---:|
| 隐藏岗位出现在 base 标准岗位词典 | 0 |
| 隐藏岗位出现在 base 事件流 | 0 |
| 隐藏岗位出现在 base 频率表 | 0 |
| 隐藏岗位出现在 base 技能池 `standard_jobs` | 0 |
| base 事件流重复 `job_id` | 0 |
| 评估集重复 `job_id` | 0 |
| base 与评估集 `job_id` 交叉 | 0 |

此外，切分后的 base 已通过现有分析命令检查：

```text
event_stream_rows: 1471
valid_event_rows: 1471
standard_job_count: 54
unknown_standard_jobs: []
```

## 八、建议使用方式

### 1. 作为新岗位训练集

如果只训练或调试“新岗位发现”能力，建议使用：

```text
datasets/new_position_training_set.labeled.csv
```

它只包含：

```text
potential_new_job：379 条
new_family：91 条
```

### 2. 作为完整路由评估集

如果要同时评估已有岗位、新岗位、新岗位族三类识别能力，建议使用：

```text
datasets/all_evaluation_samples.labeled.csv
```

### 3. 作为系统 base 库

如果要让当前 `job_update` 系统基于切分后的 base 运行，使用：

```text
--title-dictionary data/splits/v1_job_holdout/base/standard_job_title_dictionary.base_v1.csv
--event-stream data/splits/v1_job_holdout/base/job_update_event_stream.base_v1.csv
--frequency-output data/splits/v1_job_holdout/base/job_skill_monthly_frequency.base_v1_rebuilt.csv
--skill-pool data/splits/v1_job_holdout/base/skill_pool.base_v1_rebuilt.csv
```

## 九、注意事项

本数据集是“伪新岗位”构造集，不等同于真实外部新岗位数据。它适合用于方法验证、阈值调参和论文实验说明，但最终如果要证明系统对真实新岗位有效，仍建议补充外部时间切片数据或人工采集的新岗位样本。
