import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  generateBatchResumes,
  generateSingleResume,
  getDefaultRoles,
  resumesToCsv,
  resumeToMarkdown,
} from "../src/resumeEngine.js";

const args = parseArgs(process.argv.slice(2));

if (args.help || args.h) {
  printHelp();
  process.exit(0);
}

const mode = args.mode || "single";
const seniority = args.seniority || "校招/初级";
const format = args.format || "all";
const outputDir = path.resolve(args.out || path.join("outputs", `resumes_${timestamp()}`));

if (!["single", "batch"].includes(mode)) {
  fail(`不支持的模式：${mode}。可选值：single、batch`);
}

if (!["md", "json", "csv", "all"].includes(format)) {
  fail(`不支持的格式：${format}。可选值：md、json、csv、all`);
}

await mkdir(outputDir, { recursive: true });

const resumes =
  mode === "single"
    ? [generateSingleResume({ roleName: args.role || "算法工程师", seniority, seed: Number(args.seed || 0) })]
    : generateBatchResumes({
        count: clamp(Number(args.count || 8), 1, 200),
        roles: await resolveRoles(args),
        seniority,
      });

const shouldWrite = (targetFormat) => format === "all" || format === targetFormat;

if (shouldWrite("md")) {
  await Promise.all(
    resumes.map((resume, index) => {
      const fileName = `${String(index + 1).padStart(3, "0")}_${safeName(resume.name)}_${safeName(resume.targetRole)}.md`;
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
console.log(`输出目录：${outputDir}`);
console.log(`模式：${mode === "single" ? "指定职业单个生成" : "一键批量生成"}`);
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

async function resolveRoles(parsedArgs) {
  if (parsedArgs.rolesFile) {
    const content = await readFile(path.resolve(parsedArgs.rolesFile), "utf8");
    return splitRoles(content);
  }

  if (parsedArgs.roles) {
    return splitRoles(parsedArgs.roles);
  }

  return getDefaultRoles();
}

function splitRoles(value) {
  return value
    .split(/\r?\n|,|，/)
    .map((item) => item.trim())
    .filter(Boolean);
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
  if (Number.isNaN(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function fail(message) {
  console.error(message);
  console.error("运行 npm run generate -- --help 查看用法。");
  process.exit(1);
}

function printHelp() {
  console.log(`
简历生成命令行工具

用法：
  npm run generate -- --mode single --role "算法工程师"
  npm run generate -- --mode batch --count 10

参数：
  --mode single|batch       生成模式，默认 single
  --role <职业名称>          单个生成时使用，默认 算法工程师
  --count <数量>             批量生成数量，默认 8，最大 200
  --roles <职业列表>         批量职业列表，逗号或换行分隔
  --rolesFile <文件路径>     从文件读取批量职业列表
  --seniority <层级>         校招/初级、中级、高级，默认 校招/初级
  --format md|json|csv|all   输出格式，默认 all
  --out <输出目录>           输出目录，默认 outputs/resumes_时间戳

示例：
  npm run generate:single -- --role "AI 产品经理" --format md --out outputs/single_demo
  npm run generate:batch -- --count 20 --roles "前端开发工程师,后端开发工程师,数据分析师" --format all
`);
}
