# 岗位技能更新系统 Web 控制台

本地 Web 应用，用于调用岗位流自动测试、展示比对统计结果，并支持单条/批量岗位判断和人工审核入库。

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

- 自动测试：调用 `run_full_pipeline.py` 或选择已有 run 调用 `job_update.cli run-data-stream`。
- 结果统计：展示通过状态、岗位需求正确率、技能频率正确率、差异行数、行数对比、图表和 diff 预览。
- 手动输入：岗位名称、月份、岗位职责、岗位要求分框输入。
- 批量 CSV：逐条判断、逐条进入审核队列。
- 人工审核：已有岗位可确认入库；疑似新岗位可录入新族或现有族新职业。
- 安全更新：入库前自动备份 `job_update.db` 和 4 个 base CSV。

## 说明

自动测试链路不调用 DeepSeek 技能分析。单条岗位判断当前使用本地相似度和技能池/历史频率做无 API 判定，便于稳定演示；后续可以增加模型判定开关。
