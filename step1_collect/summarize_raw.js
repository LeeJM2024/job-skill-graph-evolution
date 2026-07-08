const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const RAW_FILE = path.join(ROOT, "data", "raw", "raw_jd_2026_mcp_jobs.jsonl");

function readJsonl(file) {
  if (!fs.existsSync(file)) return [];
  return fs.readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map(line => JSON.parse(line));
}

function countBy(rows, key) {
  const counts = {};
  for (const row of rows) {
    const value = row[key] || "EMPTY";
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

function main() {
  const rows = readJsonl(RAW_FILE);
  const uniqueUrls = new Set(rows.map(row => row.url_hash).filter(Boolean));
  const withDesc = rows.filter(row => row.job_description_raw).length;
  const summary = {
    total_records: rows.length,
    unique_url_hashes: uniqueUrls.size,
    duplicate_by_url_hash: rows.length - uniqueUrls.size,
    records_with_description: withDesc,
    by_query_group: countBy(rows, "query_group"),
    by_platform: countBy(rows, "platform"),
    by_query: countBy(rows, "query")
  };
  console.log(JSON.stringify(summary, null, 2));
}

main();
