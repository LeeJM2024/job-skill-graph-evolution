import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const datasetRoot = path.resolve(__dirname, "..");
const configPath = path.join(datasetRoot, "config", "seed_queries.json");
const rawDir = path.join(datasetRoot, "raw", "chinese_jobs");

const supportedSources = new Set(["all", "tencent", "huawei"]);

const sourceNames = {
  tencent: "腾讯招聘",
  huawei: "华为招聘"
};

const tencentCityIds = {
  北京: "1",
  上海: "2",
  广州: "3",
  深圳: "4",
  成都: "8",
  合肥: "",
  全国: ""
};

const overseasWords = [
  "东京",
  "日本",
  "首尔",
  "韩国",
  "新加坡",
  "美国",
  "硅谷",
  "欧洲",
  "伦敦",
  "德国",
  "法国",
  "加拿大",
  "澳大利亚",
  "Dubai",
  "Japan",
  "Korea",
  "Singapore",
  "United States",
  "USA",
  "Europe"
];

function timestamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function parseCliArgs(argv) {
  const args = {
    source: "all",
    config: configPath,
    output: "",
    target: null
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") args.help = true;
    else if (arg === "--source") args.source = argv[++index];
    else if (arg === "--config") args.config = path.resolve(argv[++index]);
    else if (arg === "--output") args.output = path.resolve(argv[++index]);
    else if (arg === "--target") args.target = Number(argv[++index]);
  }

  return args;
}

function printHelp() {
  console.log(`Usage:
  npm run collect
  npm run collect:tencent
  npm run collect:huawei
  node scripts/collect_public_jobs.mjs --source all --target 3000

说明：
  当前在线采集源：腾讯招聘、华为招聘。
  政府/公务员职位表请使用 scripts/import_government_jobs.py 导入本地 xlsx/csv。
  输出 raw JSON 到 dataset/raw/chinese_jobs/*_public_jobs.json。`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: {
      accept: "application/json, text/plain, */*",
      "user-agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
  });
  const text = await response.text();
  let parsed = null;
  try {
    parsed = JSON.parse(text);
  } catch {
    // Keep raw text for diagnostics when an endpoint returns HTML or an error page.
  }

  return {
    ok: response.ok,
    status: response.status,
    content_type: response.headers.get("content-type") || "",
    text,
    parsed
  };
}

function sourceOrder(config, requestedSource) {
  if (requestedSource !== "all") return [requestedSource];
  const configured = Array.isArray(config.sources) && config.sources.length ? config.sources : ["tencent", "huawei"];
  return configured.filter((source) => source !== "all" && supportedSources.has(source));
}

function isDomesticLocationText(text) {
  if (!text) return true;
  const value = String(text);
  return !overseasWords.some((word) => value.includes(word));
}

function isDomesticTencentPost(post) {
  if (post.CountryName && post.CountryName !== "中国") return false;
  return isDomesticLocationText(post.LocationName) && isDomesticLocationText(post.CountryName);
}

function isDomesticHuaweiPost(post) {
  const area = post.jobArea || "";
  const address = post.jobAddress || "";
  if (area && !area.includes("中国") && !area.includes("China")) return false;
  if (address && !address.startsWith("China") && !address.includes("\\China")) return false;
  return isDomesticLocationText(area) && isDomesticLocationText(address);
}

function buildTencentQueryUrl({ keyword, city, pageIndex, pageSize }) {
  const params = new URLSearchParams({
    timestamp: String(Date.now()),
    countryId: "",
    cityId: tencentCityIds[city] || "",
    bgIds: "",
    productId: "",
    categoryId: "",
    parentCategoryId: "",
    attrId: "",
    keyword,
    pageIndex: String(pageIndex),
    pageSize: String(pageSize),
    language: "zh-cn",
    area: "cn"
  });
  return `https://careers.tencent.com/tencentcareer/api/post/Query?${params.toString()}`;
}

function buildHuaweiQueryUrl({ keyword, pageIndex, pageSize }) {
  const params = new URLSearchParams({
    curPage: String(pageIndex),
    pageSize: String(pageSize),
    keywords: keyword,
    searchType: "1",
    jobType: "1",
    orderBy: "P_COUNT_DESC"
  });
  return `https://career.huawei.com/reccampportal/services/portal/portalpub/getJob/newHr/page/${pageSize}/${pageIndex}?${params.toString()}`;
}

function normalizeTencentPost(post, queryContext) {
  const postId = post.PostId || post.RecruitPostId || "";
  return {
    source: "tencent_careers",
    source_name: sourceNames.tencent,
    keyword: queryContext.queryLabel,
    city: queryContext.city,
    crawl_time: new Date().toISOString(),
    job_title: post.RecruitPostName || "",
    company_name: post.ComName || "腾讯",
    salary_text: "",
    location: post.LocationName || queryContext.city || "",
    tags: [post.BGName, post.ProductName, post.CategoryName, post.RequireWorkYearsName].filter(Boolean),
    job_description: post.Responsibility || "",
    source_url: post.PostURL || `https://careers.tencent.com/jobdesc.html?postId=${postId}`,
    publish_time: post.LastUpdateTime || "",
    raw: post
  };
}

function normalizeHuaweiPost(post, queryContext) {
  const duties = [post.mainBusiness, post.jobRequire]
    .filter((item) => item && String(item).trim())
    .map((item, index) => `${index === 0 ? "岗位职责" : "任职要求"}：\n${String(item).trim()}`)
    .join("\n\n");
  const jobId = post.jobId || post.advertisementsIntegrationId || "";
  return {
    source: "huawei_careers",
    source_name: sourceNames.huawei,
    keyword: queryContext.queryLabel,
    city: queryContext.city,
    crawl_time: new Date().toISOString(),
    job_title: post.jobname || post.nameCn || post.jobName || "",
    company_name: "华为",
    salary_text: post.bonus || "",
    location: post.jobArea || post.jobAddress || queryContext.city || "",
    tags: [post.jobType, post.jobFamilyName, post.deptName, post.workYear ? `${post.workYear}年经验` : "", post.degree ? `学历代码${post.degree}` : ""].filter(Boolean),
    job_description: duties,
    source_url: `https://career.huawei.com/reccampportal/portal5/social-recruitment-detail.html?jobId=${jobId}`,
    publish_time: post.releaseDate || post.lastUpdateDate || "",
    raw: post
  };
}

function getJobKey(source, post, normalized) {
  if (source === "tencent") return `tencent:${post.PostId || post.RecruitPostId || normalized.source_url}`;
  if (source === "huawei") return `huawei:${post.jobId || post.advertisementsIntegrationId || normalized.source_url}`;
  return `${normalized.source}:${normalized.source_url || normalized.job_title}`;
}

function createQueryResult(source, query, city, defaults) {
  const queryLabel = query.label || query.keyword || "全量岗位";
  return {
    source: source === "tencent" ? "tencent_careers" : "huawei_careers",
    search_args: {
      keyword: queryLabel,
      raw_keyword: query.keyword || "",
      city,
      pageSize: defaults.pageSize,
      maxPages: defaults.maxPages,
      domesticOnly: defaults.domesticOnly !== false
    },
    searched_at: new Date().toISOString(),
    pages: [],
    jobs: []
  };
}

async function collectTencentQuery(query, city, defaults, state) {
  const queryResult = createQueryResult("tencent", query, city, defaults);
  const startPage = defaults.page || 1;
  const domesticOnly = defaults.domesticOnly !== false;

  for (let pageIndex = startPage; pageIndex < startPage + defaults.maxPages; pageIndex += 1) {
    if (state.records >= state.targetRecords) break;
    const url = buildTencentQueryUrl({
      keyword: query.keyword || "",
      city,
      pageIndex,
      pageSize: defaults.pageSize
    });

    console.log(`Tencent Careers: ${query.label || query.keyword || "全量岗位"} / ${city} / page ${pageIndex}`);
    const response = await fetchJson(url);
    const posts = response.parsed?.Data?.Posts || [];

    queryResult.pages.push({
      pageIndex,
      url,
      ok: response.ok,
      status: response.status,
      total_count: response.parsed?.Data?.Count ?? null,
      returned_count: posts.length,
      error: response.parsed?.Code && response.parsed.Code !== 200 ? response.parsed : null
    });

    let skippedByRegion = 0;
    for (const post of posts) {
      if (state.records >= state.targetRecords) break;
      if (domesticOnly && !isDomesticTencentPost(post)) {
        skippedByRegion += 1;
        continue;
      }
      const listItem = normalizeTencentPost(post, {
        queryLabel: query.label || query.keyword || "全量岗位",
        city
      });
      const key = getJobKey("tencent", post, listItem);
      if (state.seen.has(key)) continue;
      state.seen.add(key);
      state.records += 1;
      queryResult.jobs.push({
        index: queryResult.jobs.length,
        source_url: listItem.source_url,
        list_item: listItem,
        detail: null
      });
    }

    queryResult.pages[queryResult.pages.length - 1].skipped_by_region = skippedByRegion;
    if (posts.length === 0 || posts.length < defaults.pageSize) break;
    await sleep(defaults.requestDelayMs);
  }

  queryResult.parsed_job_count = queryResult.jobs.length;
  return queryResult;
}

async function collectHuaweiQuery(query, city, defaults, state) {
  const queryResult = createQueryResult("huawei", query, city, defaults);
  const startPage = defaults.page || 1;
  const domesticOnly = defaults.domesticOnly !== false;

  for (let pageIndex = startPage; pageIndex < startPage + defaults.maxPages; pageIndex += 1) {
    if (state.records >= state.targetRecords) break;
    const url = buildHuaweiQueryUrl({
      keyword: query.keyword || "",
      pageIndex,
      pageSize: defaults.pageSize
    });

    console.log(`Huawei Careers: ${query.label || query.keyword || "全量岗位"} / ${city} / page ${pageIndex}`);
    const response = await fetchJson(url);
    const posts = response.parsed?.result || [];

    queryResult.pages.push({
      pageIndex,
      url,
      ok: response.ok,
      status: response.status,
      total_count: response.parsed?.pageVO?.totalRows ?? null,
      returned_count: posts.length,
      error: response.ok ? null : response.text.slice(0, 500)
    });

    let skippedByRegion = 0;
    for (const post of posts) {
      if (state.records >= state.targetRecords) break;
      if (domesticOnly && !isDomesticHuaweiPost(post)) {
        skippedByRegion += 1;
        continue;
      }
      const listItem = normalizeHuaweiPost(post, {
        queryLabel: query.label || query.keyword || "全量岗位",
        city
      });
      const key = getJobKey("huawei", post, listItem);
      if (state.seen.has(key)) continue;
      state.seen.add(key);
      state.records += 1;
      queryResult.jobs.push({
        index: queryResult.jobs.length,
        source_url: listItem.source_url,
        list_item: listItem,
        detail: null
      });
    }

    queryResult.pages[queryResult.pages.length - 1].skipped_by_region = skippedByRegion;
    if (posts.length === 0 || posts.length < defaults.pageSize) break;
    await sleep(defaults.requestDelayMs);
  }

  queryResult.parsed_job_count = queryResult.jobs.length;
  return queryResult;
}

async function collectSource(source, config, state) {
  const defaults = {
    page: 1,
    pageSize: 100,
    maxPages: 40,
    requestDelayMs: 250,
    domesticOnly: true,
    ...(config.defaults || {})
  };
  const queries = [];

  for (const query of config.queries || []) {
    for (const city of query.cities || ["全国"]) {
      if (state.records >= state.targetRecords) break;
      const queryResult =
        source === "tencent"
          ? await collectTencentQuery(query, city, defaults, state)
          : await collectHuaweiQuery(query, city, defaults, state);
      queries.push(queryResult);
    }
    if (state.records >= state.targetRecords) break;
  }

  return queries;
}

async function main() {
  const args = parseCliArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  if (!supportedSources.has(args.source)) {
    throw new Error(`Unsupported source: ${args.source}. Supported sources: ${Array.from(supportedSources).join(", ")}`);
  }

  const config = JSON.parse(await fs.readFile(args.config, "utf8"));
  const targetRecords = args.target || config.defaults?.targetRecords || 3000;
  const outputPath = args.output || path.join(rawDir, `${timestamp()}_${args.source}_public_jobs.json`);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });

  const output = {
    schema_version: 3,
    collector: "public-enterprise-careers",
    source: args.source,
    target_records: targetRecords,
    started_at: new Date().toISOString(),
    finished_at: null,
    collected_job_count: 0,
    config,
    queries: []
  };

  const state = {
    seen: new Set(),
    records: 0,
    targetRecords
  };

  try {
    for (const source of sourceOrder(config, args.source)) {
      if (state.records >= state.targetRecords) break;
      const sourceQueries = await collectSource(source, config, state);
      output.queries.push(...sourceQueries);
    }
  } finally {
    output.finished_at = new Date().toISOString();
    output.collected_job_count = state.records;
    await fs.writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
    console.log(`Saved public jobs output: ${outputPath}`);
    console.log(`Collected jobs: ${state.records}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
