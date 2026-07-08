const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const YAML = require("yaml");
const { searchJobList, crawlJobDetail } = require("mcp-jobs");

const ROOT = path.resolve(__dirname, "..");
const QUERY_FILE = path.join(__dirname, "queries.yaml");
const RAW_DIR = path.join(ROOT, "data", "raw");
const OUT_FILE = path.join(RAW_DIR, "raw_jd_2026_mcp_jobs.jsonl");
const LOG_FILE = path.join(RAW_DIR, "collection_log.csv");

const PILOT = process.argv.includes("--pilot");
const FETCH_DETAIL = process.argv.includes("--fetch-detail");
const MAX_PAGES = Number(getArg("--max-pages") || (PILOT ? 1 : 3));
const DELAY_MS = Number(getArg("--delay-ms") || 5000);

function getArg(name) {
  const idx = process.argv.indexOf(name);
  if (idx === -1 || idx + 1 >= process.argv.length) return null;
  return process.argv[idx + 1];
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function sha1(value) {
  return crypto.createHash("sha1").update(String(value || "")).digest("hex");
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function ensureDirs() {
  fs.mkdirSync(RAW_DIR, { recursive: true });
  if (!fs.existsSync(LOG_FILE)) {
    fs.writeFileSync(LOG_FILE, "timestamp,group,keyword,city,page,count,status,message\n", "utf8");
  }
}

function loadQueries() {
  const text = fs.readFileSync(QUERY_FILE, "utf8");
  return YAML.parse(text);
}

function detectPlatform(job) {
  const url = job.jobDetail || job.url || "";
  if (job.content) return "liepin";
  if (/zhipin\.com/.test(url)) return "zhipin";
  if (/liepin\.com/.test(url)) return "liepin";
  if (/lagou\.com/.test(url)) return "lagou";
  if (/zhaopin\.com/.test(url)) return "zhaopin";
  if (/51job\.com/.test(url)) return "51job";
  return "unknown";
}

function parseContentFallback(content) {
  const text = String(content || "").replace(/\s+/g, " ").trim();
  const cityMatch = text.match(/【([^】]+)】/);
  const salaryMatch = text.match(/(\d+\s*-\s*\d+k(?:·\d+薪)?|薪资面议)/i);
  const expMatch = text.match(/(经验不限|\d+\s*-\s*\d+年|\d+年以上|\d+年以下)/);
  const eduMatch = text.match(/(统招本科|本科|大专|硕士|博士|学历不限)/);
  const title = text
    .split("【")[0]
    .replace(salaryMatch ? salaryMatch[0] : "", "")
    .trim();
  return {
    title,
    city: cityMatch ? cityMatch[1] : "",
    salary: salaryMatch ? salaryMatch[1] : "",
    experience: expMatch ? expMatch[1] : "",
    education: eduMatch ? eduMatch[1] : "",
    description: text
  };
}

function normalizeJob(job, context, detail) {
  const url = job.jobDetail || job.url || "";
  const fallback = parseContentFallback(job.content);
  const description =
    detail?.jobDescription ||
    detail?.description ||
    job.jobDescription ||
    fallback.description ||
    "";
  const tags = Array.isArray(job.tags) ? job.tags : [];
  return {
    source_tool: "mcp-jobs",
    platform: detectPlatform(job),
    query: context.keyword,
    query_group: context.group,
    city_query: context.city,
    title_raw: job.title || job.name || fallback.title || "",
    company: job.company || "",
    city: job.address || job.city || fallback.city || "",
    salary_raw: job.salary || fallback.salary || "",
    experience_raw: inferExperience(tags) || fallback.experience,
    education_raw: inferEducation(tags) || fallback.education,
    publish_date: job.publishDate || job.publish_date || "",
    crawl_date: today(),
    url,
    url_hash: sha1(url || job.content || JSON.stringify([job.title, job.company, job.address, job.salary])),
    job_description_raw: description,
    raw_payload: job
  };
}

function inferExperience(tags) {
  return tags.find(tag => /经验|年|不限/.test(tag)) || "";
}

function inferEducation(tags) {
  return tags.find(tag => /本科|大专|硕士|博士|学历|不限/.test(tag)) || "";
}

function appendJsonl(file, objects) {
  if (!objects.length) return;
  fs.appendFileSync(file, objects.map(obj => JSON.stringify(obj)).join("\n") + "\n", "utf8");
}

function log(context, count, status, message = "") {
  const row = [
    new Date().toISOString(),
    context.group,
    context.keyword,
    context.city,
    context.page,
    count,
    status,
    String(message).replace(/\r?\n/g, " ").replace(/,/g, " ")
  ].join(",");
  fs.appendFileSync(LOG_FILE, row + "\n", "utf8");
}

async function maybeFetchDetail(job) {
  const url = job.jobDetail || job.url || "";
  if (!FETCH_DETAIL || !url) return null;
  if (!/zhipin\.com|liepin\.com/.test(url)) return null;
  try {
    await sleep(Math.max(1000, Math.floor(DELAY_MS / 2)));
    return await crawlJobDetail(url);
  } catch (error) {
    return null;
  }
}

async function collectOne(context) {
  console.log(`[collect] ${context.group} | ${context.keyword} | ${context.city} | page ${context.page}`);
  try {
    const jobs = await searchJobList({
      keyword: context.keyword,
      city: context.city === "全国" ? "" : context.city,
      page: context.page
    });
    const records = [];
    for (const job of jobs || []) {
      const detail = await maybeFetchDetail(job);
      records.push(normalizeJob(job, context, detail));
    }
    appendJsonl(OUT_FILE, records);
    log(context, records.length, "ok");
    console.log(`[ok] wrote ${records.length} records`);
  } catch (error) {
    log(context, 0, "error", error.message || String(error));
    console.error(`[error] ${error.message || error}`);
  }
}

async function main() {
  ensureDirs();
  const plan = loadQueries();
  const tasks = [];
  for (const group of plan.groups || []) {
    for (const keyword of group.keywords || []) {
      const cities = PILOT ? ["全国"] : (group.cities || ["全国"]);
      for (const city of cities) {
        for (let page = 1; page <= MAX_PAGES; page += 1) {
          tasks.push({ group: group.group, keyword, city, page });
        }
      }
    }
  }
  console.log(`Step 1 collection started. tasks=${tasks.length}, pilot=${PILOT}, fetchDetail=${FETCH_DETAIL}`);
  for (let i = 0; i < tasks.length; i += 1) {
    await collectOne(tasks[i]);
    if (i < tasks.length - 1) await sleep(DELAY_MS);
  }
  console.log(`Done. Raw output: ${OUT_FILE}`);
  console.log(`Log output: ${LOG_FILE}`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
