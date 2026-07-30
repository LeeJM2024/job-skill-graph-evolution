# 岗位技能更新系统 Web 控制台

本地 Web 应用，用于演示和审核 `dataset/job_update` 的既有岗位更新流程。

## 启动

在 `dataset` 目录运行：

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8787 --app-dir web_app
```

或：

```powershell
npm run web:job-update
```

然后打开：

```text
http://127.0.0.1:8787
```

## 当前能力

- 首页概览：汇总最新月份、标准岗位数、技能数、待审核数量、新增/下降技能数量和备份记录。
- 数据流测试：调用数据流生成系统或已有 run，再调用 `job_update.cli run-data-stream`。
- 结果展示：读取 comparison / analysis 输出，展示通过状态、岗位需求正确率、技能频率正确率、差异预览和图表。
- 时序分析：读取 base 分析结果，展示岗位技能趋势、生命周期、迁移路径、月度新增和衰退技能榜单。
- 单条 JD 更新：岗位名称、月份、岗位职责、岗位要求分框输入，并在页面右侧展示处理结果详情。
- 批量 CSV：逐条进入同一套岗位判断和审核流程。
- 人工审核：既有岗位可确认入库；疑似新岗位可人工补充标准岗位名、大族和匹配关键词后入库。
- 安全更新：入库前自动备份 `job_update.db` 和 4 个 base CSV。

## 页面结构

当前控制台按演示闭环组织为：

```text
首页概览
-> 单条 JD 更新
-> 时序分析
-> 数据流测试
-> 备份记录
```

### 首页概览

首页用于快速说明系统当前状态和动态更新链路：

- 展示最新月份、标准岗位数、技能数、待审核数量、迁移技能数、本月新增技能数、本月下降技能数。
- 展示“输入 JD -> 岗位匹配 -> 技能抽取 -> 确认入库 -> 时序刷新”的流程。
- 展示待审核队列的前几条记录，并可直接打开审核弹窗。

### 单条 JD 更新

单条 JD 页面采用左右结构：

```text
左侧：JD 输入表单
右侧：处理结果详情
```

提交 JD 后，右侧会展示：

- 原始岗位名、清洗后岗位名、匹配到的标准岗位和岗位大族。
- 岗位匹配状态与判断原因。
- 抽取出的归一化技能、KG 展示技能、技能类型和置信度。
- 更新影响预览，包括月度频率行、频率表总行、技能池行数和是否可入库。
- 对疑似新岗位，提供岗位族、标准岗位名和匹配关键词的人工补充输入。
- 支持“不更新”“打开审核弹窗”“确认入库”“查看该岗位趋势”。

确认入库后，页面会刷新待审核队列、备份记录和时序分析选项；点击“查看该岗位趋势”会自动切换到时序分析页，并选中对应标准岗位和月份。
确认入库成功后，右侧处理结果会切换为“已入库”状态，展示标准岗位、岗位族、写入技能数、基础表行数和备份编号，避免继续停留在审核页面。

## 时序分析页面

页面入口：

```text
时序分析
```

展示目标：

- 选择一个标准岗位后，查看该岗位 Top 技能的月度频率变化。
- 查看该岗位下技能生命周期状态分布和判断依据。
- 搜索或选择技能，查看技能从首现岗位到后续扩散岗位的迁移路径。
- 查看指定月份的新增/上升技能榜单和衰退/消失技能榜单。

数据来源：

```text
dataset/job_update/data/base/job_skill_monthly_frequency.csv
dataset/job_update/data/base/skill_lifecycle.csv
dataset/job_update/data/base/skill_migration.csv
dataset/job_update/data/base/skill_job_monthly_spread.csv
dataset/job_update/data/base/job_profile_diff.csv
```

相关接口：

```text
GET /api/analytics/jobs
GET /api/analytics/months
GET /api/analytics/overview
GET /api/analytics/job-trend
GET /api/analytics/lifecycle
GET /api/analytics/skill-migration
GET /api/analytics/monthly-rank
```

当前第一版使用原生 SVG 和 HTML 表格/榜单展示，不依赖额外前端构建流程。

## 单条 JD 处理逻辑

Web 单条 JD 判断已经对齐正式 `job_update` 主流程：

```text
岗位标题清洗
-> shibing624/text2vec 语义路由
-> 中间分数区间调用 LLM 二次裁决
-> 既有岗位调用 skill_extract 抽取归一化技能
-> dry-run 预览频率表和技能池变化
-> 人工确认后写入 base CSV 和 SQLite 数据库
```

人工确认新岗位时，系统会先把新标准岗位写入标准岗位词典和 SQLite，再调用正式 `skill_extract` 抽取技能，最后更新事件流、频率表、技能池和数据库。
