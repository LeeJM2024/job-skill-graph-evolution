import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const datasetRoot = path.resolve(__dirname, "..");
const rawDir = path.join(datasetRoot, "raw", "chinese_jobs");
const cleanedDir = path.join(datasetRoot, "cleaned");
const jsonlPath = path.join(cleanedDir, "chinese_jobs_normalized.jsonl");
const csvPath = path.join(cleanedDir, "chinese_jobs_normalized.csv");

const outputFields = [
  "source",
  "source_name",
  "keyword",
  "city",
  "crawl_time",
  "job_title",
  "company_name",
  "salary_text",
  "location",
  "tags",
  "job_description",
  "source_url",
  "publish_time",
  "raw"
];

function parseCliArgs(argv) {
  const args = {
    input: "",
    jsonl: jsonlPath,
    csv: csvPath
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--input") args.input = path.resolve(argv[++index]);
    else if (arg === "--jsonl") args.jsonl = path.resolve(argv[++index]);
    else if (arg === "--csv") args.csv = path.resolve(argv[++index]);
  }

  return args;
}

async function findLatestRawFile() {
  const files = await fs.readdir(rawDir).catch(() => []);
  const jsonFiles = files
    .filter((file) => file.endsWith(".json"))
    .map((file) => path.join(rawDir, file));

  if (jsonFiles.length === 0) {
    throw new Error(`No raw JSON files found in ${rawDir}`);
  }

  const stats = await Promise.all(jsonFiles.map(async (file) => ({ file, stat: await fs.stat(file) })));
  stats.sort((a, b) => b.stat.mtimeMs - a.stat.mtimeMs);
  return stats[0].file;
}

function getFirst(value, keys) {
  for (const key of keys) {
    const current = value?.[key];
    if (current == null) continue;
    if (Array.isArray(current)) {
      const first = current.find((item) => item != null && String(item).trim());
      if (first != null) return first;
    }
    if (typeof current === "object") {
      if (current.name) return current.name;
      if (current.text) return current.text;
      if (current.value) return current.value;
      if (current.title) return current.title;
      continue;
    }
    const text = String(current).trim();
    if (text) return text;
  }
  return "";
}

function pickUrl(value) {
  return getFirst(value, [
    "source_url",
    "sourceUrl",
    "detailUrl",
    "detail_url",
    "jobUrl",
    "job_url",
    "url",
    "link",
    "href"
  ]);
}

function flattenText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) return value.map(flattenText).filter(Boolean).join("\n");
  if (typeof value === "object") {
    const text = getFirst(value, ["job_description", "description", "desc", "content", "text", "detail", "requirement"]);
    if (text) return String(text).trim();
    return Object.values(value).map(flattenText).filter(Boolean).join("\n");
  }
  return String(value).trim();
}

function normalizeTags(value) {
  const raw = value?.tags || value?.labels || value?.skills || value?.skillTags || value?.jobLabels;
  if (Array.isArray(raw)) return raw.map((item) => String(item).trim()).filter(Boolean);
  if (typeof raw === "string") {
    return raw
      .split(/[;,，、\s]+/u)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function parseDetail(detail) {
  if (!detail?.ok) return {};
  if (detail.parsed && typeof detail.parsed === "object") return detail.parsed;
  if (detail.text) return { text: detail.text };
  return {};
}

function normalizeRecord(query, job) {
  const listItem = job.list_item || {};
  const detail = parseDetail(job.detail);
  const merged = { ...listItem, ...detail };
  const sourceUrl = job.source_url || pickUrl(merged);
  const jobDescription = flattenText(
    detail.job_description ||
      detail.description ||
      detail.content ||
      detail.text ||
      merged.job_description ||
      merged.description ||
      merged.content
  );

  return {
    source: getFirst(merged, ["source", "platform", "site"]) || "mcp-jobs",
    source_name: getFirst(merged, ["source_name", "sourceName", "platform_name", "site_name"]),
    keyword: query.search_args?.keyword || "",
    city: query.search_args?.city || "",
    crawl_time: query.searched_at || "",
    job_title: getFirst(merged, ["job_title", "jobTitle", "title", "name", "positionName", "position"]),
    company_name: getFirst(merged, ["company_name", "companyName", "company", "brandName"]),
    salary_text: getFirst(merged, ["salary_text", "salaryText", "salary", "pay", "wage"]),
    location: getFirst(merged, ["location", "address", "city", "area", "workCity", "district"]),
    tags: normalizeTags(merged),
    job_description: jobDescription,
    source_url: sourceUrl,
    publish_time: getFirst(merged, ["publish_time", "publishTime", "releaseDate", "lastUpdateDate", "LastUpdateTime"]),
    raw: {
      list_item: listItem,
      detail,
      detail_error: job.detail?.ok === false ? job.detail.error : null
    }
  };
}

function hasUsableJobContent(record) {
  return Boolean(
    record.job_title ||
      record.company_name ||
      record.salary_text ||
      record.source_url ||
      record.job_description ||
      (Array.isArray(record.tags) && record.tags.length > 0)
  );
}

function csvEscape(value) {
  let text;
  if (Array.isArray(value)) text = value.join(";");
  else if (typeof value === "object" && value !== null) text = JSON.stringify(value);
  else text = value == null ? "" : String(value);
  text = text.replace(/\r?\n/g, "\n");
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

async function main() {
  const args = parseCliArgs(process.argv.slice(2));
  const inputPath = args.input || (await findLatestRawFile());
  const raw = JSON.parse(await fs.readFile(inputPath, "utf8"));
  const records = [];

  for (const query of raw.queries || []) {
    for (const job of query.jobs || []) {
      const record = normalizeRecord(query, job);
      if (hasUsableJobContent(record)) records.push(record);
    }
  }

  await fs.mkdir(path.dirname(args.jsonl), { recursive: true });
  await fs.mkdir(path.dirname(args.csv), { recursive: true });

  const jsonl = records.map((record) => JSON.stringify(record)).join("\n");
  await fs.writeFile(args.jsonl, jsonl ? `${jsonl}\n` : "", "utf8");

  const csvHeader = outputFields.join(",");
  const csvRows = records.map((record) => outputFields.map((field) => csvEscape(record[field])).join(","));
  await fs.writeFile(args.csv, `\uFEFF${[csvHeader, ...csvRows].join("\n")}\n`, "utf8");

  console.log(`Input: ${inputPath}`);
  console.log(`Records: ${records.length}`);
  console.log(`Wrote JSONL: ${args.jsonl}`);
  console.log(`Wrote CSV: ${args.csv}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
