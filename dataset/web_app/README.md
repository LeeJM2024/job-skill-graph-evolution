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

- 数据流测试：调用数据流生成系统或已有 run，再调用 `job_update.cli run-data-stream`。
- 结果展示：读取 comparison / analysis 输出，展示通过状态、岗位需求正确率、技能频率正确率、差异预览和图表。
- 单条 JD 录入：岗位名称、月份、岗位职责、岗位要求分框输入。
- 批量 CSV：逐条进入同一套岗位判断和审核流程。
- 人工审核：既有岗位可确认入库；疑似新岗位可人工补充标准岗位名、大族和匹配关键词后入库。
- 安全更新：入库前自动备份 `job_update.db` 和 4 个 base CSV。

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
