const ROLE_PROFILES = [
  {
    role: "前端开发工程师",
    family: "技术研发",
    skills: ["React", "Vue", "TypeScript", "Vite", "前端工程化", "性能优化", "组件化设计"],
    projects: ["低代码页面搭建平台", "多端统一组件库", "招聘数据可视化看板"],
    impact: ["首屏加载时间降低 38%", "组件复用率提升至 72%", "页面缺陷回归周期缩短 45%"],
  },
  {
    role: "后端开发工程师",
    family: "技术研发",
    skills: ["Java", "Spring Boot", "MySQL", "Redis", "消息队列", "接口设计", "服务治理"],
    projects: ["岗位数据清洗服务", "简历解析任务调度平台", "企业招聘数据 API"],
    impact: ["接口 P95 响应时间控制在 180ms 内", "批处理吞吐提升 3.2 倍", "服务可用性达到 99.9%"],
  },
  {
    role: "算法工程师",
    family: "人工智能",
    skills: ["Python", "机器学习", "NLP", "向量检索", "特征工程", "模型评估", "PyTorch"],
    projects: ["岗位技能抽取模型", "简历岗位匹配模型", "职业能力图谱补全"],
    impact: ["技能抽取 F1 提升至 0.86", "匹配 Top3 命中率提升 21%", "人工标注成本降低 30%"],
  },
  {
    role: "数据分析师",
    family: "数据",
    skills: ["SQL", "Python", "Excel", "Tableau", "指标体系", "A/B 测试", "数据建模"],
    projects: ["招聘转化漏斗分析", "岗位需求趋势监测", "候选人画像分析"],
    impact: ["定位 5 个核心流失节点", "周报自动化覆盖 12 条业务线", "辅助投放成本降低 18%"],
  },
  {
    role: "产品经理",
    family: "产品",
    skills: ["需求分析", "原型设计", "用户研究", "PRD", "数据分析", "项目推进", "竞品分析"],
    projects: ["AI 简历生成工作台", "岗位匹配推荐流程", "招聘管理后台"],
    impact: ["核心流程转化率提升 16%", "需求交付周期缩短 25%", "用户满意度提升至 4.6/5"],
  },
  {
    role: "运营专员",
    family: "运营",
    skills: ["用户运营", "活动策划", "内容运营", "社群运营", "数据复盘", "增长实验", "渠道协同"],
    projects: ["毕业生求职训练营", "岗位订阅增长活动", "简历优化内容矩阵"],
    impact: ["活动报名转化率提升 24%", "社群留存提升 19%", "内容点击率提升 31%"],
  },
  {
    role: "测试工程师",
    family: "质量保障",
    skills: ["测试用例设计", "自动化测试", "接口测试", "Playwright", "缺陷管理", "性能测试", "CI"],
    projects: ["简历生成回归测试体系", "招聘平台接口自动化", "前端视觉巡检流程"],
    impact: ["核心链路自动化覆盖率达到 80%", "线上缺陷率下降 36%", "回归时间缩短 50%"],
  },
  {
    role: "UI/UX 设计师",
    family: "设计",
    skills: ["Figma", "用户体验", "交互设计", "设计系统", "可用性测试", "信息架构", "视觉规范"],
    projects: ["简历工作台界面改版", "企业端招聘控制台", "岗位图谱可视化设计"],
    impact: ["关键任务完成率提升 22%", "设计交付返工率降低 28%", "界面一致性问题减少 40%"],
  },
];

const NAMES = ["陈一诺", "李思远", "王嘉禾", "赵明轩", "周若琳", "刘子航", "孙芷晴", "何宇辰", "林书瑶", "许亦凡"];
const UNIVERSITIES = ["华东理工大学", "南京大学", "武汉大学", "西安电子科技大学", "北京交通大学", "中南财经政法大学"];
const MAJORS = ["计算机科学与技术", "软件工程", "数据科学与大数据技术", "信息管理与信息系统", "人工智能", "数字媒体技术"];

export function getDefaultRoles() {
  return ROLE_PROFILES.map((item) => item.role);
}

export function generateBatchResumes({ count = 8, roles = [], seniority = "校招/初级" }) {
  const selectedRoles = roles.length ? roles : getDefaultRoles();
  return Array.from({ length: count }, (_, index) => {
    const role = selectedRoles[index % selectedRoles.length];
    return generateSingleResume({ roleName: role, seniority, seed: index });
  });
}

export function generateSingleResume({ roleName, seniority = "校招/初级", seed = 0 }) {
  const profile = resolveRoleProfile(roleName);
  const name = pick(NAMES, seed);
  const university = pick(UNIVERSITIES, seed + 2);
  const major = pick(MAJORS, seed + 4);
  const years = seniority.includes("中级") ? "3 年" : seniority.includes("高级") ? "6 年" : "1 年";
  const skills = rotate(profile.skills, seed).slice(0, 6);
  const projectA = pick(profile.projects, seed);
  const projectB = pick(profile.projects, seed + 1);
  const impactA = pick(profile.impact, seed);
  const impactB = pick(profile.impact, seed + 1);

  return {
    id: `${Date.now()}-${seed}-${Math.random().toString(16).slice(2, 8)}`,
    name,
    targetRole: profile.role,
    requestedRole: roleName,
    family: profile.family,
    seniority,
    summary: `${years}${profile.role}相关经验，熟悉${skills.slice(0, 3).join("、")}，能够围绕业务目标完成需求拆解、方案设计与结果复盘。`,
    education: {
      school: university,
      major,
      degree: "本科",
      period: "2022.09 - 2026.06",
    },
    skills,
    experiences: [
      {
        company: "共创智能科技实验室",
        title: `${profile.role}实习生`,
        period: "2025.03 - 2025.09",
        bullets: [
          `参与${projectA}，负责需求分析、模块实现与数据口径校验。`,
          `围绕${skills[0]}与${skills[1]}搭建核心功能，${impactA}。`,
          "沉淀复用模板、异常记录和交付文档，提升团队后续迭代效率。",
        ],
      },
      {
        company: "校园数字化创新项目组",
        title: "项目成员",
        period: "2024.10 - 2025.02",
        bullets: [
          `完成${projectB}的原型验证与可行性评估。`,
          `结合${skills[2]}、${skills[3]}优化关键流程，${impactB}。`,
        ],
      },
    ],
    projects: [
      {
        name: projectA,
        description: `面向${profile.family}场景，构建从输入解析、能力匹配到结果生成的闭环流程。`,
        highlights: [`使用${skills[0]}完成核心模块`, `建立结果质量检查清单`, impactA],
      },
      {
        name: projectB,
        description: "聚焦真实业务数据，完成指标拆解、功能迭代和演示交付。",
        highlights: [`融合${skills[1]}和${skills[4]}提升生成质量`, impactB],
      },
    ],
    certificates: buildCertificates(profile.family, seed),
    quality: {
      completeness: score(seed, 88, 98),
      roleFit: score(seed + 3, 82, 96),
      keywordCoverage: score(seed + 5, 78, 94),
    },
    generatedAt: new Date().toISOString(),
  };
}

export function resumeToMarkdown(resume) {
  return [
    `# ${resume.name} - ${resume.targetRole}`,
    "",
    `目标岗位：${resume.targetRole}`,
    `经验层级：${resume.seniority}`,
    `岗位大类：${resume.family}`,
    "",
    "## 个人优势",
    resume.summary,
    "",
    "## 教育背景",
    `${resume.education.school} / ${resume.education.major} / ${resume.education.degree} / ${resume.education.period}`,
    "",
    "## 核心技能",
    resume.skills.map((item) => `- ${item}`).join("\n"),
    "",
    "## 工作经历",
    ...resume.experiences.flatMap((item) => [
      `### ${item.company} - ${item.title}`,
      item.period,
      ...item.bullets.map((bullet) => `- ${bullet}`),
      "",
    ]),
    "## 项目经历",
    ...resume.projects.flatMap((item) => [
      `### ${item.name}`,
      item.description,
      ...item.highlights.map((highlight) => `- ${highlight}`),
      "",
    ]),
    "## 证书与补充",
    resume.certificates.map((item) => `- ${item}`).join("\n"),
  ].join("\n");
}

export function resumesToCsv(resumes) {
  const header = ["姓名", "目标岗位", "岗位大类", "经验层级", "技能", "完整度", "岗位匹配度", "关键词覆盖率"];
  const rows = resumes.map((resume) => [
    resume.name,
    resume.targetRole,
    resume.family,
    resume.seniority,
    resume.skills.join(" / "),
    resume.quality.completeness,
    resume.quality.roleFit,
    resume.quality.keywordCoverage,
  ]);
  return [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
    .join("\n");
}

function resolveRoleProfile(roleName) {
  const normalized = roleName.trim();
  const exact = ROLE_PROFILES.find((item) => item.role === normalized);
  if (exact) return exact;

  const keywordRules = [
    ["前端", "前端开发工程师"],
    ["后端", "后端开发工程师"],
    ["Java", "后端开发工程师"],
    ["算法", "算法工程师"],
    ["机器学习", "算法工程师"],
    ["数据", "数据分析师"],
    ["产品", "产品经理"],
    ["运营", "运营专员"],
    ["测试", "测试工程师"],
    ["设计", "UI/UX 设计师"],
    ["交互", "UI/UX 设计师"],
  ];
  const matched = keywordRules.find(([keyword]) => normalized.toLowerCase().includes(keyword.toLowerCase()));
  if (matched) {
    const base = ROLE_PROFILES.find((item) => item.role === matched[1]);
    return { ...base, role: normalized || base.role };
  }

  return {
    role: normalized || "通用岗位",
    family: "综合岗位",
    skills: ["需求理解", "问题拆解", "跨团队沟通", "数据意识", "文档撰写", "项目推进", "复盘优化"],
    projects: ["岗位能力画像构建", "业务流程优化项目", "求职材料智能生成"],
    impact: ["交付周期缩短 20%", "流程错误率下降 25%", "方案复用率提升 30%"],
  };
}

function buildCertificates(family, seed) {
  const pools = {
    技术研发: ["全国计算机等级考试二级", "软件设计师备考", "GitHub 项目实践"],
    人工智能: ["机器学习课程证书", "数据挖掘竞赛经历", "Python 数据分析证书"],
    数据: ["统计分析课程证书", "Tableau 可视化训练", "SQL 能力认证"],
    产品: ["产品经理方法论训练", "Axure/Figma 原型实践", "用户研究项目经历"],
    运营: ["新媒体运营训练", "增长实验复盘报告", "活动策划项目经历"],
    质量保障: ["软件测试基础证书", "接口自动化测试实践", "缺陷管理流程训练"],
    设计: ["Figma 设计系统实践", "用户体验设计课程", "可用性测试项目经历"],
  };
  const list = pools[family] ?? ["项目管理课程训练", "数据分析基础训练", "职业能力提升计划"];
  return rotate(list, seed).slice(0, 3);
}

function pick(items, index) {
  return items[Math.abs(index) % items.length];
}

function rotate(items, offset) {
  return items.map((_, index) => items[(index + offset) % items.length]);
}

function score(seed, min, max) {
  const value = min + ((seed * 7 + 11) % (max - min + 1));
  return Math.min(max, Math.max(min, value));
}
