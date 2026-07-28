import { useMemo, useState } from "react";
import {
  BriefcaseBusiness,
  CheckCircle2,
  ClipboardList,
  Download,
  FileJson,
  FileText,
  Layers3,
  Play,
  Search,
  Sparkles,
  Table,
  UserRound,
  WandSparkles,
} from "lucide-react";
import {
  generateBatchResumes,
  generateSingleResume,
  getDefaultRoles,
  resumesToCsv,
  resumeToMarkdown,
} from "./resumeEngine.js";

const STAGES = ["输入解析", "岗位画像", "技能匹配", "简历成稿", "质量检查"];

export default function App() {
  const defaultRoles = useMemo(() => getDefaultRoles(), []);
  const [mode, setMode] = useState("batch");
  const [singleRole, setSingleRole] = useState("算法工程师");
  const [seniority, setSeniority] = useState("校招/初级");
  const [batchCount, setBatchCount] = useState(8);
  const [roleSource, setRoleSource] = useState("default");
  const [customRoles, setCustomRoles] = useState("前端开发工程师\n后端开发工程师\n数据分析师\n产品经理");
  const [resumes, setResumes] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [lastRunMode, setLastRunMode] = useState("");

  const selectedResume = useMemo(
    () => resumes.find((resume) => resume.id === selectedId) ?? resumes[0] ?? null,
    [resumes, selectedId],
  );

  const stats = useMemo(() => {
    const families = new Set(resumes.map((resume) => resume.family));
    const avgFit = resumes.length
      ? Math.round(resumes.reduce((sum, resume) => sum + resume.quality.roleFit, 0) / resumes.length)
      : 0;
    const avgKeyword = resumes.length
      ? Math.round(resumes.reduce((sum, resume) => sum + resume.quality.keywordCoverage, 0) / resumes.length)
      : 0;
    return { count: resumes.length, families: families.size, avgFit, avgKeyword };
  }, [resumes]);

  function runGeneration() {
    if (mode === "single") {
      const resume = generateSingleResume({ roleName: singleRole, seniority, seed: Date.now() % 1000 });
      setResumes([resume]);
      setSelectedId(resume.id);
      setLastRunMode("单个生成");
      return;
    }

    const roles =
      roleSource === "custom"
        ? customRoles
            .split(/\r?\n|,|，/)
            .map((item) => item.trim())
            .filter(Boolean)
        : defaultRoles;
    const nextResumes = generateBatchResumes({ count: batchCount, roles, seniority });
    setResumes(nextResumes);
    setSelectedId(nextResumes[0]?.id ?? "");
    setLastRunMode("批量生成");
  }

  function downloadSelectedMarkdown() {
    if (!selectedResume) return;
    downloadText(`${selectedResume.name}_${selectedResume.targetRole}.md`, resumeToMarkdown(selectedResume), "text/markdown");
  }

  function downloadJson() {
    downloadText("generated_resumes.json", JSON.stringify(resumes, null, 2), "application/json");
  }

  function downloadCsv() {
    downloadText("generated_resumes.csv", resumesToCsv(resumes), "text/csv");
  }

  return (
    <main className="appShell">
      <aside className="controlPanel">
        <header className="brandBlock">
          <div className="brandMark">
            <Sparkles size={24} />
          </div>
          <div>
            <h1>简历生成工作台</h1>
            <p>两种生成模式的可运行框架</p>
          </div>
        </header>

        <section className="panel">
          <div className="sectionTitle">
            <Layers3 size={18} />
            <h2>生成模式</h2>
          </div>
          <div className="segmented">
            <button className={mode === "batch" ? "active" : ""} onClick={() => setMode("batch")}>
              <ClipboardList size={16} />
              批量简历
            </button>
            <button className={mode === "single" ? "active" : ""} onClick={() => setMode("single")}>
              <UserRound size={16} />
              单个简历
            </button>
          </div>
        </section>

        {mode === "batch" ? (
          <section className="panel">
            <div className="sectionTitle">
              <BriefcaseBusiness size={18} />
              <h2>批量参数</h2>
            </div>
            <label className="field">
              <span>职业来源</span>
              <select value={roleSource} onChange={(event) => setRoleSource(event.target.value)}>
                <option value="default">内置职业池</option>
                <option value="custom">自定义职业列表</option>
              </select>
            </label>
            {roleSource === "custom" && (
              <label className="field">
                <span>自定义职业，一行一个</span>
                <textarea value={customRoles} onChange={(event) => setCustomRoles(event.target.value)} rows={6} />
              </label>
            )}
            <label className="field">
              <span>生成数量：{batchCount}</span>
              <input
                type="range"
                min="1"
                max="30"
                value={batchCount}
                onChange={(event) => setBatchCount(Number(event.target.value))}
              />
            </label>
          </section>
        ) : (
          <section className="panel">
            <div className="sectionTitle">
              <Search size={18} />
              <h2>单个参数</h2>
            </div>
            <label className="field">
              <span>指定职业名称</span>
              <input value={singleRole} onChange={(event) => setSingleRole(event.target.value)} placeholder="例如：AI 产品经理" />
            </label>
          </section>
        )}

        <section className="panel">
          <div className="sectionTitle">
            <WandSparkles size={18} />
            <h2>通用设置</h2>
          </div>
          <label className="field">
            <span>经验层级</span>
            <select value={seniority} onChange={(event) => setSeniority(event.target.value)}>
              <option>校招/初级</option>
              <option>中级</option>
              <option>高级</option>
            </select>
          </label>
          <button className="primaryButton" onClick={runGeneration}>
            <Play size={18} />
            {mode === "batch" ? "一键生成批量简历" : "生成单个简历"}
          </button>
        </section>

        <section className="panel">
          <div className="sectionTitle">
            <Download size={18} />
            <h2>导出</h2>
          </div>
          <div className="exportGrid">
            <button onClick={downloadSelectedMarkdown} disabled={!selectedResume}>
              <FileText size={16} />
              当前简历
            </button>
            <button onClick={downloadJson} disabled={!resumes.length}>
              <FileJson size={16} />
              JSON
            </button>
            <button onClick={downloadCsv} disabled={!resumes.length}>
              <Table size={16} />
              CSV
            </button>
          </div>
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>{mode === "batch" ? "一键生成批量简历" : "指定职业生成单个简历"}</h2>
            <p>当前生成器为本地规则版，已预留模型接口替换位置。</p>
          </div>
          <div className="runBadge">
            <CheckCircle2 size={16} />
            {lastRunMode || "等待生成"}
          </div>
        </header>

        <section className="pipeline">
          {STAGES.map((stage, index) => (
            <div className={resumes.length ? "stage done" : "stage"} key={stage}>
              <span>{index + 1}</span>
              <strong>{stage}</strong>
            </div>
          ))}
        </section>

        <section className="statsGrid">
          <Metric label="简历数量" value={stats.count} />
          <Metric label="岗位大类" value={stats.families} />
          <Metric label="平均匹配度" value={stats.avgFit ? `${stats.avgFit}%` : "-"} />
          <Metric label="关键词覆盖" value={stats.avgKeyword ? `${stats.avgKeyword}%` : "-"} />
        </section>

        <section className="contentGrid">
          <div className="resultList">
            <div className="listHeader">
              <h3>生成结果</h3>
              <span>{resumes.length} 份</span>
            </div>
            {resumes.length ? (
              resumes.map((resume) => (
                <button
                  className={selectedResume?.id === resume.id ? "resumeItem selected" : "resumeItem"}
                  key={resume.id}
                  onClick={() => setSelectedId(resume.id)}
                >
                  <strong>{resume.name}</strong>
                  <span>{resume.targetRole}</span>
                  <small>{resume.family} / 匹配度 {resume.quality.roleFit}%</small>
                </button>
              ))
            ) : (
              <div className="emptyState">
                <WandSparkles size={32} />
                <p>选择模式并点击生成后，这里会展示简历列表。</p>
              </div>
            )}
          </div>

          <ResumePreview resume={selectedResume} />
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ResumePreview({ resume }) {
  if (!resume) {
    return (
      <article className="preview emptyPreview">
        <FileText size={42} />
        <p>暂无简历预览</p>
      </article>
    );
  }

  return (
    <article className="preview">
      <header className="resumeHeader">
        <div>
          <h3>{resume.name}</h3>
          <p>{resume.targetRole} / {resume.seniority}</p>
        </div>
        <div className="scorePill">匹配度 {resume.quality.roleFit}%</div>
      </header>

      <section>
        <h4>个人优势</h4>
        <p>{resume.summary}</p>
      </section>

      <section>
        <h4>核心技能</h4>
        <div className="tags">
          {resume.skills.map((skill) => (
            <span key={skill}>{skill}</span>
          ))}
        </div>
      </section>

      <section>
        <h4>教育背景</h4>
        <p>{resume.education.school} / {resume.education.major} / {resume.education.degree}</p>
        <small>{resume.education.period}</small>
      </section>

      <section>
        <h4>工作经历</h4>
        {resume.experiences.map((item) => (
          <div className="timelineItem" key={`${item.company}-${item.period}`}>
            <strong>{item.company} - {item.title}</strong>
            <small>{item.period}</small>
            <ul>
              {item.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section>
        <h4>项目经历</h4>
        {resume.projects.map((item) => (
          <div className="projectBox" key={item.name}>
            <strong>{item.name}</strong>
            <p>{item.description}</p>
            <div className="tags compact">
              {item.highlights.map((highlight) => (
                <span key={highlight}>{highlight}</span>
              ))}
            </div>
          </div>
        ))}
      </section>
    </article>
  );
}

function downloadText(fileName, content, type) {
  const blob = new Blob([content], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}
