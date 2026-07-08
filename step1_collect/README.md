# Step 1: Collect Current JD Data

Goal: collect current job postings and save them as reproducible raw JSONL. Do not clean, deduplicate, extract skills, or infer trends in this step.

## Tool

Main tool: `mcp-jobs`

```powershell
npx -y mcp-jobs
```

Debug mode:

```powershell
$env:CRAWLER_HEADLESS='false'
$env:CRAWLER_DEBUG='true'
npx -y mcp-jobs
```

## Fixed Query Plan

Use `queries.yaml`. Keep query terms fixed so collection can be reproduced and explained in the project report.

## Raw Output Schema

Every posting should be normalized into one JSON object per line:

```json
{
  "source_tool": "mcp-jobs",
  "platform": "boss|liepin|zhilian|51job|unknown",
  "query": "AI Agent工程师",
  "query_group": "emerging_agent",
  "city_query": "全国",
  "title_raw": "",
  "company": "",
  "city": "",
  "salary_raw": "",
  "experience_raw": "",
  "education_raw": "",
  "publish_date": "",
  "crawl_date": "YYYY-MM-DD",
  "url": "",
  "url_hash": "",
  "job_description_raw": "",
  "raw_payload": {}
}
```

## Output Files

```text
data/raw/raw_jd_2026_mcp_jobs.jsonl
data/raw/collection_log.csv
```

## Acceptance Criteria

```text
raw JD >= 3000
platform count >= 3
Agent-related raw JD >= 500
Java-related raw JD >= 800
each record has source_tool / platform / query / crawl_date / url_hash
```

## Compliance Note

Use low frequency collection, cache every result, avoid duplicate requests, and follow platform terms. Do not describe the system as bypassing anti-crawling restrictions.

## Actual Commands

Install dependencies:

```powershell
cd B:\揭榜挂帅\step1_collect
npm install
npx playwright install chromium
```

Run a small pilot:

```powershell
npm run collect:pilot -- --delay-ms 2000
npm run summarize
```

Run a larger collection:

```powershell
npm run collect -- --max-pages 3 --delay-ms 5000
npm run summarize
```

Optional: fetch detail pages when available. This is slower and currently only useful for supported detail URLs.

```powershell
npm run collect -- --max-pages 2 --delay-ms 7000 --fetch-detail
```

## Current Tool Reality Check

In local tests on 2026-06-08, `mcp-jobs@1.4.0` successfully returned Liepin list data. Zhipin returned no parsed list items because its page selectors appear stale, and Lagou/Zhaopin/51job have search URLs in the package but no matching crawler configs. Treat Step 1 as "MCP Jobs current JD collection", with Liepin as the first stable source, then add other sources only after a separate adapter is verified.
