# 岗位技能演化系统

本项目面向技术岗位招聘信息，完成从单条 JD 输入、岗位归类、技能抽取与归一化，到岗位技能频率、生命周期、迁移路径和岗位画像的动态更新。

系统维护两个彼此隔离的数据域：

| 数据域 | 面向数据 | 维护内容 |
| --- | --- | --- |
| 公司岗位 | 企业技术岗位 JD | 月度技能频率、技能池、生命周期、迁移分析、岗位画像 |
| 政府技术岗位 | 已筛选的政府计算机相关岗位 | 保留真实发布时间的年度招聘流，独立维护词典、技能池、分析结果和数据库 |

两套系统共享文本处理、`text2vec` 相似度和 LLM 调用能力，但绝不共用标准岗位词典、技能词典、基础 CSV、SQLite 数据库或待审核队列。

## 处理闭环

```text
用户输入一条 JD
-> LLM 清洗岗位名称
-> text2vec 与标准岗位词典计算候选
-> 需要时由 LLM 对 Top-K 二次裁决
-> 技能抽取与归一化
-> 自动入库或人工确认
-> 更新事件流、频率、技能池、生命周期、迁移和岗位画像
-> 同步写入所属数据域的 SQLite
```

人工确认模式允许用户选择 Top-K 标准岗位、删除或修改抽取技能、补充规范技能，确认后才写入正式基础数据。疑似新岗位和新技能先进入待维护队列，不自动污染正式词典。

## 目录

```text
dataset/
  job_update/
    company_job_update/       公司岗位更新系统与基础数据
    government_job_update/    政府技术岗位更新系统与基础数据
    shared/                   两个数据域共用的 LLM、相似度、文本工具
  岗位数据流生成系统/          公司岗位初始基线事件流生成工具
  web_app/                    双数据源 Web 控制台
```

详细使用说明：

- [岗位更新总览](dataset/job_update/README.md)
- [公司岗位系统](dataset/job_update/company_job_update/README.md)
- [政府岗位系统](dataset/job_update/government_job_update/README.md)
- [岗位数据流生成系统](dataset/岗位数据流生成系统/README.md)
- [Web 控制台](dataset/web_app/README.md)

## 环境准备

在 Windows PowerShell 中执行：

```powershell
cd "B:\揭榜挂帅\dataset"
python -m pip install -r requirements.txt
npm install
```

首次运行会下载 `shibing624/text2vec-base-chinese` 模型。岗位名称清洗、技能抽取和中间分数岗位裁决使用配置的 LLM；在 `B:\揭榜挂帅\dataset\.env` 中配置相应 API Key，例如：

```text
DEEPSEEK_API_KEY=你的密钥
```

## 最常用命令

启动 Web 控制台：

```powershell
cd "B:\揭榜挂帅\dataset"
npm run web:job-update
```

打开 `http://127.0.0.1:8787`，在顶部选择“公司岗位”或“政府技术岗位”。

运行全部岗位更新测试：

```powershell
cd "B:\揭榜挂帅\dataset"
npm run test:job-update
```

## 基础数据与版本管理

- 人工维护的源数据和词典：公司 `standard_job_title_dictionary.csv`、`company_skill_dictionary.csv`、政府源数据 `government_jobs_2024_2026_tech_final.csv`、政府标准岗位词典、`government_skill_dictionary.csv`，以及政府初始岗位映射审核结果。
- 命令或 Web 自动维护的数据：两个数据域的正式事件流、技能频率、技能池、生命周期、迁移、岗位画像、待审核记录和 `*.db`。不要直接编辑这些派生 CSV 或 SQLite；应通过单条 JD 入库、人工确认、重建命令或正式初始化流程更新。
- `outputs/`、LLM 缓存、浏览器运行产物属于本地过程文件，已由 `.gitignore` 排除。
- 公司岗位的初始事件流由“岗位数据流生成系统”构造；政府岗位使用原始数据自带的真实时间流。
