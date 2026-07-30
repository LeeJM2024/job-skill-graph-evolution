# 标准岗位简历生成控制台

这个前端用于按标准岗位生成单条候选人简历，并在页面中预览结构化字段、技能、工作经历和项目经历。

## 启动

```bash
cd B:\揭榜挂帅\dataset\resume_generator_app
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5188/
```

## 页面能力

- 从 `dataset/job_update/data/base/standard_job_title_dictionary.csv` 生成标准岗位列表。
- 从 `dataset/job_update/data/base/job_skill_monthly_frequency.csv` 和 `skill_pool.csv` 聚合岗位技能画像。
- 支持选择标准岗位、岗位大族、经验年限、学历、学校类型、专业和额外技能。
- 支持导出单条简历的 JSON、CSV、Markdown。
- CSV 字段对齐 `dataset/resume/synthetic_detailed_resumes_experience_30k.csv` 的主字段。

## 终端生成

```bash
npm run generate -- --role "前端开发工程师" --years 5 --format all --out outputs/frontend_demo
```

可选参数：

```text
--role            标准岗位名称
--years           工作经验年限
--education       学历
--degree          学位
--schoolCategory  学校类型
--major           专业
--skills          额外技能，支持分号、逗号或换行分隔
--count           生成数量，默认 1
--format          md、json、csv、all
--out             输出目录
```

## 更新岗位画像

当基础岗位词典或技能频率表更新后：

```bash
npm run sync:profiles
npm run build
```
