import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const datasetRoot = path.resolve(appRoot, "..");
const dictionaryPath = path.join(datasetRoot, "job_update/data/base/standard_job_title_dictionary.csv");
const frequencyPath = path.join(datasetRoot, "job_update/data/base/job_skill_monthly_frequency.csv");
const skillPoolPath = path.join(datasetRoot, "job_update/data/base/skill_pool.csv");
const outputPath = path.join(appRoot, "src/standardJobProfiles.js");

const dictionaryRows = parseCsv(await readFile(dictionaryPath, "utf8"));
const frequencyRows = parseCsv(await readFile(frequencyPath, "utf8"));
const skillPoolRows = parseCsv(await readFile(skillPoolPath, "utf8"));

const profiles = dictionaryRows
  .map((row) => ({
    standardJobTitle: row.standard_job_title?.trim(),
    standardCategory: row.standard_category?.trim() ?? "",
    matchKeywords: row.match_keywords?.trim() ?? "",
    topSkills: [],
  }))
  .filter((profile) => profile.standardJobTitle);

const profileByJob = new Map(profiles.map((profile) => [profile.standardJobTitle, profile]));
const kgBySkill = new Map();
const mentionByJobSkill = new Map();

for (const row of skillPoolRows) {
  const skill = row.normalized_skill?.trim();
  if (!skill) continue;
  kgBySkill.set(skill, row.kg_display_skill?.trim() ?? "");
  const mentionCount = Number(row.mention_count || 0);
  for (const job of String(row.standard_jobs ?? "").split(";").map((item) => item.trim()).filter(Boolean)) {
    const key = `${job}\u0000${skill}`;
    mentionByJobSkill.set(key, Math.max(mentionByJobSkill.get(key) ?? 0, mentionCount));
  }
}

const latestByJobSkill = new Map();
for (const row of frequencyRows) {
  const job = row.standard_job?.trim();
  const skill = row.skill?.trim();
  if (!job || !skill || !profileByJob.has(job)) continue;
  const key = `${job}\u0000${skill}`;
  const previous = latestByJobSkill.get(key);
  if (!previous || String(row.month ?? "") >= previous.month) {
    latestByJobSkill.set(key, {
      name: skill,
      kgDisplaySkill: kgBySkill.get(skill) ?? "",
      month: row.month ?? "",
      monthlyFrequency: round(Number(row.monthly_skill_frequency || 0)),
      cumulativeFrequency: round(Number(row.cumulative_skill_frequency || 0)),
      cumulativeCount: Number(row.cumulative_skill_count || 0),
      mentionCount: mentionByJobSkill.get(key) ?? 0,
    });
  }
}

for (const profile of profiles) {
  profile.topSkills = [...latestByJobSkill.entries()]
    .filter(([key]) => key.startsWith(`${profile.standardJobTitle}\u0000`))
    .map(([, value]) => value)
    .sort((left, right) =>
      right.cumulativeFrequency - left.cumulativeFrequency ||
      right.cumulativeCount - left.cumulativeCount ||
      right.mentionCount - left.mentionCount ||
      right.name.localeCompare(left.name, "zh-Hans-CN"),
    )
    .slice(0, 18);
}

const categories = [...new Set(profiles.map((profile) => profile.standardCategory).filter(Boolean))].sort((a, b) =>
  a.localeCompare(b, "zh-Hans-CN"),
);

const content = [
  "// Generated from dataset/job_update/data/base CSV files.",
  "// Regenerate when the standard job dictionary or base skill frequencies change.",
  "",
  `export const STANDARD_JOB_PROFILES = ${JSON.stringify(profiles, null, 2)};`,
  "",
  `export const STANDARD_CATEGORIES = ${JSON.stringify(categories, null, 2)};`,
  "",
].join("\n");

await writeFile(outputPath, content, "utf8");
console.log(`同步完成：${profiles.length} 个标准岗位，${categories.length} 个岗位大族`);
console.log(`输出文件：${outputPath}`);

function parseCsv(text) {
  const cleanText = text.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < cleanText.length; index += 1) {
    const char = cleanText[index];
    const next = cleanText[index + 1];
    if (inQuotes) {
      if (char === '"' && next === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }

  const headers = rows.shift() ?? [];
  return rows
    .filter((item) => item.some((value) => value !== ""))
    .map((item) => Object.fromEntries(headers.map((header, index) => [header, item[index] ?? ""])));
}

function round(value) {
  return Math.round(value * 1000000) / 1000000;
}
