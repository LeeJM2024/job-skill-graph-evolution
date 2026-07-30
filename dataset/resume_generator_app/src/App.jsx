import { useEffect, useMemo, useState } from "react";
import {
  BriefcaseBusiness,
  CheckCircle2,
  ClipboardList,
  Download,
  FileJson,
  FileText,
  GraduationCap,
  RefreshCw,
  Search,
  Table,
  UserRound,
} from "lucide-react";
import {
  OUTPUT_COLUMNS,
  downloadText,
  generateResumeByStandardJob,
  getProfileByJobTitle,
  getStandardJobProfiles,
  getSuggestedMajor,
  resumesToCsv,
  resumeToMarkdown,
} from "./resumeEngine.js";
import { STANDARD_CATEGORIES } from "./standardJobProfiles.js";

const YEAR_OPTIONS = [0, 1, 2, 3, 5, 8, 10];
const EDUCATION_OPTIONS = ["本科", "硕士", "博士", "大专"];
const DEGREE_BY_EDUCATION = {
  大专: "无",
  本科: "学士",
  硕士: "硕士",
  博士: "博士",
};
const SCHOOL_CATEGORIES = ["普通高校", "双一流", "985/211", "海外院校", "职业院校"];

export default function App() {
  const profiles = useMemo(() => getStandardJobProfiles(), []);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("全部");
  const [standardJobTitle, setStandardJobTitle] = useState(profiles[0]?.standardJobTitle ?? "");
  const [yearsExperience, setYearsExperience] = useState(3);
  const [education, setEducation] = useState("本科");
  const [schoolCategory, setSchoolCategory] = useState("普通高校");
  const [major, setMajor] = useState(() => getSuggestedMajor(profiles[0]));
  const [preferredSkills, setPreferredSkills] = useState("");
  const [seed, setSeed] = useState(7);
  const [resume, setResume] = useState(() =>
    generateResumeByStandardJob({
      standardJobTitle: profiles[0]?.standardJobTitle,
      yearsExperience: 3,
      education: "本科",
      degree: "学士",
      schoolCategory: "普通高校",
      major: getSuggestedMajor(profiles[0]),
      seed: 7,
    }),
  );

  const selectedProfile = useMemo(() => getProfileByJobTitle(standardJobTitle), [standardJobTitle]);
  const filteredProfiles = useMemo(() => {
    const text = query.trim().toLowerCase();
    return profiles.filter((profile) => {
      const categoryMatched = category === "全部" || profile.standardCategory === category;
      const textMatched =
        !text ||
        profile.standardJobTitle.toLowerCase().includes(text) ||
        profile.standardCategory.toLowerCase().includes(text);
      return categoryMatched && textMatched;
    });
  }, [category, profiles, query]);

  useEffect(() => {
    if (!filteredProfiles.length) return;
    if (filteredProfiles.some((profile) => profile.standardJobTitle === standardJobTitle)) return;
    selectJob(filteredProfiles[0].standardJobTitle);
  }, [filteredProfiles, standardJobTitle]);

  function selectJob(title) {
    const profile = getProfileByJobTitle(title);
    setStandardJobTitle(title);
    setMajor(getSuggestedMajor(profile));
  }

  function generate() {
    const nextSeed = seed + 1;
    const next = generateResumeByStandardJob({
      standardJobTitle,
      yearsExperience,
      education,
      degree: DEGREE_BY_EDUCATION[education] ?? "学士",
      schoolCategory,
      major,
      preferredSkills,
      seed: nextSeed,
    });
    setSeed(nextSeed);
    setResume(next);
  }

  function exportJson() {
    downloadText(
      `${resume.standard_job_title}_${resume.name}.json`,
      JSON.stringify(toDatasetRecord(resume), null, 2),
      "application/json;charset=utf-8",
    );
  }

  function exportCsv() {
    downloadText(`${resume.standard_job_title}_${resume.name}.csv`, `\ufeff${resumesToCsv([resume])}`, "text/csv;charset=utf-8");
  }

  function exportMarkdown() {
    downloadText(`${resume.standard_job_title}_${resume.name}.md`, resumeToMarkdown(resume), "text/markdown;charset=utf-8");
  }

  return (
    <main className="appShell">
      <aside className="controlPanel">
        <section className="brandBlock">
          <div className="brandMark">
            <UserRound size={24} />
          </div>
          <div>
            <h1>简历生成控制台</h1>
            <p>标准岗位单条生成 / 预览</p>
          </div>
        </section>

        <section className="fieldGroup">
          <label htmlFor="jobSearch">标准岗位</label>
          <div className="searchBox">
            <Search size={16} />
            <input
              id="jobSearch"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索岗位或大族"
            />
          </div>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="全部">全部岗位大族</option>
            {STANDARD_CATEGORIES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select value={standardJobTitle} onChange={(event) => selectJob(event.target.value)}>
            {!filteredProfiles.length && <option value={standardJobTitle}>没有匹配岗位</option>}
            {filteredProfiles.map((profile) => (
              <option key={profile.standardJobTitle} value={profile.standardJobTitle}>
                {profile.standardJobTitle}
              </option>
            ))}
          </select>
        </section>

        <section className="fieldGroup">
          <label>工作经验</label>
          <div className="yearGrid">
            {YEAR_OPTIONS.map((year) => (
              <button
                className={yearsExperience === year ? "selected" : ""}
                key={year}
                onClick={() => setYearsExperience(year)}
                type="button"
              >
                {year}年
              </button>
            ))}
          </div>
          <input
            min="0"
            max="20"
            type="number"
            value={yearsExperience}
            onChange={(event) => setYearsExperience(Number(event.target.value))}
          />
        </section>

        <section className="fieldGroup">
          <label>学历背景</label>
          <div className="inlineGrid">
            <select value={education} onChange={(event) => setEducation(event.target.value)}>
              {EDUCATION_OPTIONS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <select value={schoolCategory} onChange={(event) => setSchoolCategory(event.target.value)}>
              {SCHOOL_CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="majorRow">
            <GraduationCap size={16} />
            <input value={major} onChange={(event) => setMajor(event.target.value)} />
          </div>
        </section>

        <section className="fieldGroup">
          <label htmlFor="preferredSkills">额外技能</label>
          <textarea
            id="preferredSkills"
            value={preferredSkills}
            onChange={(event) => setPreferredSkills(event.target.value)}
            placeholder="可输入技能，用分号、逗号或换行分隔"
            rows={4}
          />
        </section>

        <button className="primaryAction" onClick={generate} type="button">
          <RefreshCw size={18} />
          生成简历
        </button>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>{resume.standard_job_title}</h2>
            <p>{resume.standard_category} / {resume.years_experience} 年经验 / {resume.education}</p>
          </div>
          <div className="exportActions">
            <button onClick={exportJson} title="导出 JSON" type="button">
              <FileJson size={18} />
            </button>
            <button onClick={exportCsv} title="导出 CSV" type="button">
              <Table size={18} />
            </button>
            <button onClick={exportMarkdown} title="导出 Markdown" type="button">
              <Download size={18} />
            </button>
          </div>
        </header>

        <section className="summaryStrip">
          <Metric icon={<BriefcaseBusiness size={18} />} label="标准岗位" value={resume.standard_job_title} />
          <Metric icon={<ClipboardList size={18} />} label="岗位技能覆盖" value={`${Math.round(resume.job_skill_coverage_ratio * 100)}%`} />
          <Metric icon={<CheckCircle2 size={18} />} label="重合技能数" value={resume.resume_skill_overlap_count} />
        </section>

        <section className="contentGrid">
          <article className="previewPanel">
            <div className="panelHeader">
              <div>
                <h3>{resume.name}</h3>
                <p>{resume.phone} / {resume.email}</p>
              </div>
              <span>{resume.school_category}</span>
            </div>

            <div className="resumeSection">
              <h4>个人概述</h4>
              <p>{resume.profile_text}</p>
            </div>

            <div className="resumeSection">
              <h4>技能</h4>
              <div className="skillCloud">
                {resume.parsedSkills.map((skill) => (
                  <span key={skill}>
                    {skill}
                    <small>{resume.parsedSkillLevels[skill]}</small>
                  </span>
                ))}
              </div>
            </div>

            <div className="resumeSection">
              <h4>工作经历</h4>
              {resume.parsedExperience.map((item, index) => (
                <div className="timelineItem" key={`${item.company_type}-${index}`}>
                  <strong>{item.company_type} / {item.role} / {item.duration_years} 年</strong>
                  <ul>
                    {item.highlights.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <div className="resumeSection">
              <h4>项目经历</h4>
              {resume.parsedProjects.map((item) => (
                <div className="projectItem" key={item.project_name}>
                  <strong>{item.project_name}</strong>
                  <p>{item.description}</p>
                  <p className="mutedText">{item.tech_stack.join("、")}</p>
                </div>
              ))}
            </div>
          </article>

          <aside className="profilePanel">
            <h3>岗位画像</h3>
            <p>{selectedProfile.standardCategory}</p>
            <div className="profileSkillList">
              {(selectedProfile.topSkills ?? []).slice(0, 14).map((skill) => (
                <div key={skill.name}>
                  <span>{skill.name}</span>
                  <strong>{Math.round(skill.cumulativeFrequency * 100)}%</strong>
                </div>
              ))}
            </div>
            <div className="jsonPreview">
              <div className="jsonTitle">
                <FileText size={16} />
                结构化字段
              </div>
              <pre>{JSON.stringify(toDatasetRecord(resume), null, 2)}</pre>
            </div>
          </aside>
        </section>
      </section>
    </main>
  );
}

function Metric({ icon, label, value }) {
  return (
    <div className="metric">
      {icon}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function toDatasetRecord(resume) {
  return Object.fromEntries(OUTPUT_COLUMNS.map((column) => [column, resume[column]]));
}
