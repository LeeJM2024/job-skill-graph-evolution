# Neo4j Job-Skill 建图与 UI 说明

## 所属阶段

该流程位于 JD 技能抽取之后、推荐结果解释之前。

```text
cleaned/all_jobs_23714_normalized.jsonl
        |
structured/job_skill_mentions.jsonl
        |
        v
graph/job_skill_graph.json
        |
        +--> ui/job_skill_graph.html
        |
        +--> Neo4j: (Job)-[:REQUIRES_SKILL|PREFERS_SKILL]->(Skill)
```

它不替换 BM25 和 embedding。BM25/embedding 负责召回和排序，Neo4j 图谱负责解释岗位需要哪些技能、后续做能力差距分析。

## 一键生成本地图谱数据

在 `dataset/` 目录执行：

```powershell
npm run graph:build
```

等价于：

```powershell
python scripts/build_neo4j_job_skill_graph.py
```

默认输入：

```text
cleaned/all_jobs_23714_normalized.jsonl
structured/job_skill_mentions.jsonl
```

默认输出：

```text
graph/job_skill_graph.json
graph/job_skill_graph_report.json
graph/neo4j_job_skill_constraints.cypher
```

`job_skill_graph.json` 给本地 UI 使用。默认只导出技能命中最多的 120 个岗位，避免浏览器节点太多卡顿。完整 Neo4j 导入不受这个限制。

如需调整 UI 预览规模：

```powershell
python scripts/build_neo4j_job_skill_graph.py --max-ui-jobs 300
```

如需导出全部 UI 节点：

```powershell
python scripts/build_neo4j_job_skill_graph.py --max-ui-jobs 0
```

## 导入 Neo4j

先安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

启动 Neo4j 后，配置连接信息：

```powershell
$env:NEO4J_URI="bolt://localhost:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="你的密码"
$env:NEO4J_DATABASE="neo4j"
```

导入：

```powershell
npm run graph:import
```

等价于：

```powershell
python scripts/build_neo4j_job_skill_graph.py --import-neo4j
```

导入后的图结构：

```text
(j:Job {job_id, job_title, source_type, source_name, company_name, location, source_url, tags})
(s:Skill {name, category})
(j)-[:REQUIRES_SKILL {raw_skill, evidence_sentence, span_text, span_start, span_end, confidence}]->(s)
(j)-[:PREFERS_SKILL {raw_skill, evidence_sentence, span_text, span_start, span_end, confidence}]->(s)
```

## Neo4j 查询例子

查看岗位技能：

```cypher
MATCH (j:Job)-[r]->(s:Skill)
WHERE j.job_title CONTAINS "AI"
RETURN j.job_title AS job, type(r) AS relation, s.name AS skill, r.evidence_sentence AS evidence
LIMIT 20;
```

查看热门技能：

```cypher
MATCH (:Job)-[r]->(s:Skill)
RETURN s.name AS skill, s.category AS category, count(r) AS jobs
ORDER BY jobs DESC
LIMIT 30;
```

能力差距分析的雏形：

```cypher
MATCH (j:Job)-[:REQUIRES_SKILL]->(s:Skill)
WHERE j.job_id = "job_6394c9a8372e3e23f95f"
  AND NOT s.name IN ["Python", "SQL"]
RETURN s.name AS missing_skill, s.category AS category;
```

这里的 `["Python", "SQL"]` 后续可以替换成简历技能抽取结果。

## 打开本地 UI

先生成图数据：

```powershell
npm run graph:build
```

再启动静态服务：

```powershell
npm run graph:ui
```

浏览器访问：

```text
http://localhost:8010/ui/job_skill_graph.html
```

UI 支持：

- 搜索岗位、公司、技能、证据句
- 按技能类别筛选
- 按 `REQUIRES_SKILL` / `PREFERS_SKILL` 筛选
- 点击岗位节点查看岗位信息
- 点击技能节点查看技能类别和关联岗位数
- 点击关系查看技能证据句和 span 位置

## 当前边界

当前第一版只建 `Job-Skill` 图，不做：

- 岗位归一
- 岗位更新检测
- 技能层级本体
- 简历节点导入
- BM25/embedding 排名结果入图

这些后续可以接在当前图结构之后做。现在这一步的目标是先让 JD 里的技能要求变成可解释、可查询、可展示的图谱边。
