# v1_job_holdout 数据集切分说明

本目录由 `scripts/rebuild_v1_job_holdout_split.py` 从当前 `data/base/` 重新生成。

切分目标：

1. `existing_job`：base 已保留岗位的未来增量 JD。
2. `potential_new_job`：隐藏具体标准岗位，但保留岗位大族。
3. `new_family`：隐藏整个岗位大族。

## 当前规模

| 数据项 | 数量 |
|---|---:|
| 源标准岗位 | 73 |
| 源事件流 JD | 2335 |
| base 标准岗位 | 56 |
| base 事件流 JD | 1522 |
| known_job_increment | 352 |
| potential_new_job | 356 |
| new_family | 105 |
| 评估集总计 | 813 |

## 隐藏标准岗位

`potential_new_job` 隐藏：

- AIGC算法工程师
- DevOps工程师
- Go开发工程师
- Python开发工程师
- 多模态算法工程师
- 大模型应用工程师
- 大模型测试工程师
- 搜索算法工程师
- 数据挖掘算法工程师
- 数据治理工程师
- 热设计工程师
- 芯片验证工程师

`new_family` 隐藏大族：

- 多媒体
- 机器人
- 自动驾驶

`new_family` 对应标准岗位：

- 图形图像工程师
- 机器人算法工程师
- 机器人软件工程师
- 自动驾驶算法工程师
- 音视频工程师

## 重新生成命令

```powershell
cd B:\揭榜挂帅\dataset\job_update\company_job_update
python scripts\rebuild_v1_job_holdout_split.py
```
