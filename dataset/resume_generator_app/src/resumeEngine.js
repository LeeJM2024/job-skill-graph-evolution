import { STANDARD_JOB_PROFILES } from "./standardJobProfiles.js";

export const OUTPUT_COLUMNS = [
  "resume_id",
  "name",
  "gender",
  "age",
  "phone",
  "email",
  "split",
  "target_job_family",
  "education",
  "degree",
  "school_category",
  "major",
  "english_level",
  "years_experience",
  "experience",
  "projects",
  "skills_normalized",
  "skill_levels",
  "job_keywords_used",
  "profile_text",
  "original_target_job_family",
  "standard_job",
  "standard_job_title",
  "standard_category",
  "alignment_method",
  "job_profile_skills",
  "kg_display_skills",
  "resume_skill_overlap_count",
  "resume_skill_overlap_ratio",
  "job_skill_coverage_ratio",
];

const SURNAMES = ["陈", "李", "王", "赵", "周", "刘", "孙", "何", "林", "许", "张", "黄", "吴", "郑", "梁", "宋"];
const GIVEN_NAMES = ["悦然", "思远", "嘉禾", "明轩", "若琳", "子航", "芷晴", "宇辰", "书瑶", "亦凡", "景行", "知夏", "予安", "星河", "清越", "承泽"];
const UNIVERSITIES = ["南京大学", "武汉大学", "西安电子科技大学", "北京交通大学", "华东理工大学", "哈尔滨工业大学", "电子科技大学", "中山大学"];
const ENGLISH_LEVELS = ["英语四级", "英语六级", "CET-6", "雅思 6.5"];
const COMPANY_TYPES = ["大型科技企业", "企业数字化团队", "互联网平台业务线", "智能化产品团队", "产业技术服务公司"];

const CATEGORY_BASE_SKILLS = {
  AI算法: ["Python", "PyTorch", "机器学习", "深度学习", "模型训练", "模型评估"],
  AI应用: ["Python", "LangChain", "RAG", "Prompt", "API设计", "工程化落地"],
  AI基础设施: ["Python", "Linux", "Kubernetes", "Docker", "分布式系统", "GPU"],
  AI安全: ["Python", "安全测试", "风控策略", "漏洞分析", "模型评估", "攻防演练"],
  云计算: ["Linux", "Docker", "Kubernetes", "云原生", "微服务", "DevOps"],
  前端: ["JavaScript", "TypeScript", "React", "Vue.js", "CSS", "性能优化"],
  后端: ["Java", "Go", "Python", "MySQL", "Redis", "微服务"],
  数据: ["SQL", "Python", "数据建模", "ETL", "数据仓库", "指标体系"],
  测试质量: ["测试用例设计", "自动化测试", "接口测试", "性能测试", "缺陷管理", "CI/CD"],
  安全: ["网络安全", "渗透测试", "漏洞分析", "安全加固", "日志分析", "应急响应"],
  产品: ["需求分析", "原型设计", "用户研究", "数据分析", "项目推进", "PRD"],
};

const MAJOR_BY_CATEGORY = {
  AI算法: ["人工智能", "模式识别与智能系统", "计算机科学与技术"],
  AI应用: ["软件工程", "人工智能", "计算机科学与技术"],
  AI基础设施: ["计算机科学与技术", "软件工程", "电子信息工程"],
  前端: ["软件工程", "数字媒体技术", "计算机科学与技术"],
  后端: ["软件工程", "计算机科学与技术", "信息管理与信息系统"],
  数据: ["数据科学与大数据技术", "统计学", "计算机科学与技术"],
  测试质量: ["软件工程", "计算机科学与技术", "信息安全"],
  安全: ["信息安全", "网络空间安全", "计算机科学与技术"],
  产品: ["信息管理与信息系统", "计算机科学与技术", "工业工程"],
};

const PROJECT_TEMPLATES = [
  {
    name: "岗位技能画像与推荐系统",
    description: "负责候选人能力标签、岗位技能画像和推荐特征的构建，支持人岗匹配链路迭代。",
    outcome: "提升推荐结果可解释性，并支撑多类岗位复用。",
  },
  {
    name: "企业级数据治理与分析平台",
    description: "参与数据接入、质量校验、指标建模和可视化分析流程，沉淀可复用数据资产。",
    outcome: "缩短业务分析周期，提升关键指标追踪效率。",
  },
  {
    name: "智能业务中台能力建设",
    description: "围绕核心业务流程完成模块设计、开发、测试和上线复盘，推动工程规范落地。",
    outcome: "降低重复开发成本，提升系统稳定性。",
  },
];

export function getStandardJobProfiles() {
  return STANDARD_JOB_PROFILES;
}

export function getProfileByJobTitle(title) {
  return STANDARD_JOB_PROFILES.find((profile) => profile.standardJobTitle === title) ?? STANDARD_JOB_PROFILES[0];
}

export function getSuggestedMajor(profile) {
  const pool = MAJOR_BY_CATEGORY[profile?.standardCategory] ?? MAJOR_BY_CATEGORY[profile?.standardCategory?.slice(0, 2)] ?? ["计算机科学与技术", "软件工程"];
  return pool[0];
}

export function generateResumeByStandardJob({
  standardJobTitle,
  yearsExperience = 3,
  education = "本科",
  degree = "学士",
  schoolCategory = "普通高校",
  major,
  preferredSkills = [],
  seed = 1,
} = {}) {
  const profile = getProfileByJobTitle(standardJobTitle);
  const rng = createRng(seedFrom(`${standardJobTitle}-${yearsExperience}-${seed}`));
  const baseSkills = resolveProfileSkills(profile);
  const selectedSkills = unique([...parseSkills(preferredSkills), ...baseSkills]).slice(0, 24);
  const keySkills = selectedSkills.slice(0, 8);
  const displayMajor = major?.trim() || pick(MAJOR_BY_CATEGORY[profile.standardCategory] ?? ["计算机科学与技术", "软件工程"], rng);
  const name = `${pick(SURNAMES, rng)}${pick(GIVEN_NAMES, rng)}`;
  const gender = rng() > 0.5 ? "男" : "女";
  const years = clamp(Number(yearsExperience) || 0, 0, 20);
  const age = Math.max(22, Math.min(42, 22 + years + Math.floor(rng() * 4)));
  const resumeId = `resume_interactive_${Date.now().toString(36)}_${Math.floor(rng() * 10000).toString().padStart(4, "0")}`;
  const skillLevels = Object.fromEntries(selectedSkills.map((skill, index) => [skill, resolveSkillLevel(index, years, rng)]));
  const experiences = buildExperiences(profile, selectedSkills, years, rng);
  const projects = buildProjects(profile, selectedSkills, rng);
  const kgDisplaySkills = resolveKgDisplaySkills(profile, selectedSkills);
  const overlapCount = selectedSkills.filter((skill) => baseSkills.includes(skill)).length;
  const coverageRatio = baseSkills.length ? round(overlapCount / baseSkills.length) : 0;

  const resume = {
    resume_id: resumeId,
    name,
    gender,
    age,
    phone: generatePhone(rng),
    email: `${resumeId.replace("resume_", "")}@example.com`,
    split: "interactive",
    target_job_family: profile.standardJobTitle,
    education,
    degree,
    school_category: schoolCategory,
    major: displayMajor,
    english_level: pick(ENGLISH_LEVELS, rng),
    years_experience: years,
    experience: JSON.stringify(experiences, null, 0),
    projects: JSON.stringify(projects, null, 0),
    skills_normalized: JSON.stringify(selectedSkills, null, 0),
    skill_levels: JSON.stringify(skillLevels, null, 0),
    job_keywords_used: JSON.stringify(baseSkills, null, 0),
    profile_text: buildProfileText(profile, keySkills, years, education),
    original_target_job_family: profile.standardJobTitle,
    standard_job: profile.standardJobTitle,
    standard_job_title: profile.standardJobTitle,
    standard_category: profile.standardCategory,
    alignment_method: "interactive_standard_job_console",
    job_profile_skills: JSON.stringify(baseSkills, null, 0),
    kg_display_skills: JSON.stringify(kgDisplaySkills, null, 0),
    resume_skill_overlap_count: overlapCount,
    resume_skill_overlap_ratio: round(overlapCount / Math.max(selectedSkills.length, 1)),
    job_skill_coverage_ratio: coverageRatio,
  };

  return {
    ...resume,
    parsedExperience: experiences,
    parsedProjects: projects,
    parsedSkills: selectedSkills,
    parsedSkillLevels: skillLevels,
    parsedKgDisplaySkills: kgDisplaySkills,
    profile,
  };
}

export function resumesToCsv(resumes) {
  const rows = [OUTPUT_COLUMNS.join(",")];
  for (const resume of resumes) {
    rows.push(OUTPUT_COLUMNS.map((column) => csvEscape(resume[column] ?? "")).join(","));
  }
  return rows.join("\n");
}

export function resumeToMarkdown(resume) {
  const skills = resume.parsedSkills ?? safeJsonParse(resume.skills_normalized, []);
  const skillLevels = resume.parsedSkillLevels ?? safeJsonParse(resume.skill_levels, {});
  const experiences = resume.parsedExperience ?? safeJsonParse(resume.experience, []);
  const projects = resume.parsedProjects ?? safeJsonParse(resume.projects, []);

  return [
    `# ${resume.name} - ${resume.standard_job_title}`,
    "",
    `- 学历：${resume.education} / ${resume.degree} / ${resume.school_category}`,
    `- 专业：${resume.major}`,
    `- 工作经验：${resume.years_experience} 年`,
    `- 手机：${resume.phone}`,
    `- 邮箱：${resume.email}`,
    "",
    "## 个人概述",
    "",
    resume.profile_text,
    "",
    "## 技能",
    "",
    ...skills.map((skill) => `- ${skill}：${skillLevels[skill] ?? "熟练"}`),
    "",
    "## 工作经历",
    "",
    ...experiences.flatMap((item) => [
      `### ${item.company_type} / ${item.role} / ${item.duration_years} 年`,
      ...item.highlights.map((line) => `- ${line}`),
      "",
    ]),
    "## 项目经历",
    "",
    ...projects.flatMap((item) => [
      `### ${item.project_name}`,
      `- 角色：${item.role}`,
      `- 技术栈：${item.tech_stack.join("、")}`,
      `- 内容：${item.description}`,
      `- 结果：${item.outcome}`,
      "",
    ]),
  ].join("\n");
}

export function downloadText(fileName, content, type = "text/plain;charset=utf-8") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function resolveProfileSkills(profile) {
  const fromFrequency = (profile.topSkills ?? []).map((skill) => skill.name).filter(Boolean);
  const baseline = CATEGORY_BASE_SKILLS[profile.standardCategory] ?? CATEGORY_BASE_SKILLS[profile.standardCategory?.slice(0, 2)] ?? ["Python", "SQL", "项目协作", "问题分析", "系统设计"];
  return unique([...fromFrequency, ...baseline]).slice(0, 18);
}

function resolveKgDisplaySkills(profile, skills) {
  const known = new Map((profile.topSkills ?? []).map((skill) => [skill.name, skill.kgDisplaySkill || ""]));
  const result = {};
  for (const skill of skills) {
    result[skill] = known.get(skill) || guessKgDisplaySkill(skill, profile.standardCategory);
  }
  return result;
}

function guessKgDisplaySkill(skill, category) {
  if (/Python|Java|Go|C\+\+|TypeScript|JavaScript|SQL|PHP|Node/i.test(skill)) return "编程语言";
  if (/安全|漏洞|攻防|权限|风控/.test(skill)) return "安全";
  if (/模型|LLM|RAG|Agent|机器学习|深度学习|PyTorch|TensorFlow/.test(skill)) return "AI";
  if (/Docker|Kubernetes|Linux|云|DevOps|CI/.test(skill)) return "系统与运维";
  if (/数据|ETL|指标|仓库|Spark|Hadoop/.test(skill)) return "数据工程";
  return category || "综合能力";
}

function buildExperiences(profile, skills, years, rng) {
  const firstDuration = Math.max(1, Math.ceil(years * 0.55));
  const secondDuration = Math.max(0, years - firstDuration);
  const blocks = [
    makeExperienceBlock(profile, skills, firstDuration || 1, rng, years >= 5),
  ];
  if (secondDuration > 0) {
    blocks.push(makeExperienceBlock(profile, rotate(skills, 4), secondDuration, rng, years >= 8));
  }
  return blocks;
}

function makeExperienceBlock(profile, skills, duration, rng, senior) {
  const focus = skills.slice(0, 6);
  const secondary = skills.slice(6, 10);
  return {
    company_type: pick(COMPANY_TYPES, rng),
    role: profile.standardJobTitle,
    duration_years: duration,
    keywords: focus.concat(secondary).slice(0, 10),
    highlights: [
      `围绕${profile.standardCategory || "技术"}方向，负责需求拆解、方案设计、开发落地和效果复盘。`,
      `主要使用${focus.slice(0, 4).join("、")}等技术，支撑线上业务迭代。`,
      "与产品、研发、测试和运维团队协作，沉淀文档、规范和可复用组件。",
      senior ? "承担模块负责人职责，参与排期评估、风险识别和新人代码评审。" : "参与核心模块开发和联调，能独立定位并解决常见线上问题。",
      `围绕${profile.standardJobTitle}岗位画像补充${focus.slice(0, 4).join("、")}等核心能力。`,
    ],
  };
}

function buildProjects(profile, skills, rng) {
  return [0, 1].map((offset) => {
    const template = PROJECT_TEMPLATES[(Math.floor(rng() * PROJECT_TEMPLATES.length) + offset) % PROJECT_TEMPLATES.length];
    return {
      project_name: categoryProjectName(profile, template.name, offset),
      project_scale: offset === 0 ? "medium" : "small",
      role: offset === 0 ? "主要负责人" : "核心成员",
      tech_stack: rotate(skills, offset * 5).slice(0, 12),
      description: template.description,
      outcome: template.outcome,
    };
  });
}

function categoryProjectName(profile, defaultName, offset) {
  if (profile.standardCategory?.includes("AI")) return offset === 0 ? "智能应用能力构建项目" : "模型效果评估与优化项目";
  if (profile.standardCategory?.includes("前端")) return offset === 0 ? "多端业务前端工程化项目" : "交互体验与性能优化项目";
  if (profile.standardCategory?.includes("后端")) return offset === 0 ? "高并发业务服务治理项目" : "接口平台与数据联调项目";
  if (profile.standardCategory?.includes("数据")) return offset === 0 ? "业务指标体系与数据平台项目" : "数据质量治理项目";
  if (profile.standardCategory?.includes("安全")) return offset === 0 ? "安全监测与风险处置项目" : "系统加固与漏洞治理项目";
  return defaultName;
}

function buildProfileText(profile, keySkills, years, education) {
  const yearText = years > 0 ? `${years} 年` : "校招/实习";
  return `求职意向：${profile.standardJobTitle}。${education}背景，具备${yearText}相关项目或工作经验，熟悉${keySkills.join("、")}等能力，能够围绕岗位画像完成方案设计、工程实现、效果评估和跨团队协作。`;
}

function resolveSkillLevel(index, years, rng) {
  if (years <= 1 && index > 8) return "了解";
  if (index < 3 && years >= 5) return rng() > 0.45 ? "精通" : "熟练";
  if (index < 8) return "熟练";
  return rng() > 0.35 ? "掌握" : "了解";
}

function parseSkills(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value ?? "")
    .split(/\r?\n|;|；|,|，/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function generatePhone(rng) {
  const prefixes = ["136", "138", "150", "156", "182", "186", "188"];
  return `${pick(prefixes, rng)}${Math.floor(10000000 + rng() * 90000000)}`;
}

function pick(values, rng) {
  return values[Math.floor(rng() * values.length) % values.length];
}

function rotate(values, offset) {
  if (!values.length) return [];
  return values.map((_, index) => values[(index + offset) % values.length]);
}

function unique(values) {
  return [...new Set(values.map((item) => String(item).trim()).filter(Boolean))];
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function round(value) {
  return Math.round(value * 10000) / 10000;
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function safeJsonParse(value, defaultValue) {
  try {
    return JSON.parse(value);
  } catch {
    return defaultValue;
  }
}

function seedFrom(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function createRng(seed) {
  let state = seed || 1;
  return () => {
    state = Math.imul(1664525, state) + 1013904223;
    return ((state >>> 0) / 4294967296);
  };
}
