import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  generateResumeByStandardJob,
  getStandardJobProfiles,
  resumesToCsv,
  resumeToMarkdown,
} from "../src/resumeEngine.js";

const args = parseArgs(process.argv.slice(2));

if (args.help || args.h) {
  printHelp();
  process.exit(0);
}

const profiles = getStandardJobProfiles();
const role = args.role || profiles[0]?.standardJobTitle;
const count = clamp(Number(args.count || 1), 1, 200);
const format = args.format || "all";
const outputDir = path.resolve(args.out || path.join("outputs", `resume_${timestamp()}`));

if (!profiles.some((profile) => profile.standardJobTitle === role)) {
  fail(`标准岗位不存在：${role}`);
}

if (!["md", "json", "csv", "all"].includes(format)) {
  fail(`不支持的格式：${format}。可选值：md、json、csv、all`);
}

await mkdir(outputDir, { recursive: true });

const resumes = Array.from({ length: count }, (_, index) =>
  generateResumeByStandardJob({
    standardJobTitle: role,
    yearsExperience: Number(args.years ?? 3),
    education: args.education || "本科",
    degree: args.degree || "学士",
    schoolCategory: args.schoolCategory || "普通高校",
    major: args.major || "",
    preferredSkills: args.skills || "",
    seed: Number(args.seed || 1) + index,
  }),
);

const shouldWrite = (targetFormat) => format === "all" || format === targetFormat;

if (shouldWrite("md")) {
  await Promise.all(
    resumes.map((resume, index) => {
      const fileName = `${String(index + 1).padStart(3, "0")}_${safeName(resume.name)}_${safeName(resume.standard_job_title)}.md`;
      return writeFile(path.join(outputDir, fileName), resumeToMarkdown(resume), "utf8");
    }),
  );
}

if (shouldWrite("json")) {
  await writeFile(path.join(outputDir, "resumes.json"), JSON.stringify(resumes, null, 2), "utf8");
}

if (shouldWrite("csv")) {
  await writeFile(path.join(outputDir, "resumes.csv"), `\ufeff${resumesToCsv(resumes)}`, "utf8");
}

console.log(`生成完成：${resumes.length} 份简历`);
console.log(`标准岗位：${role}`);
console.log(`输出目录：${outputDir}`);
console.log(`格式：${format}`);

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}

function safeName(value) {
  return String(value)
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 60);
}

function timestamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    "_",
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds()),
  ].join("");
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

function printHelp() {
  console.log(`标准岗位单条简历生成

用法：
  npm run generate -- --role "前端开发工程师" --years 5 --format all

参数：
  --role            标准岗位名称，必须来自岗位词典
  --years           工作经验年限，默认 3
  --education       学历，默认 本科
  --degree          学位，默认 学士
  --schoolCategory  学校类型，默认 普通高校
  --major           专业
  --skills          额外技能，支持分号、逗号或换行分隔
  --count           生成数量，默认 1
  --format          md、json、csv、all，默认 all
  --out             输出目录
`);
}
