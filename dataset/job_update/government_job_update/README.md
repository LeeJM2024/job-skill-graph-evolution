# Government Job Update

This is an independent government technical-job domain. It owns government
dictionaries, event data, review data, and database files. It does not read or
write the big-company `company_job_update` base dataset. It reuses only the tested
underlying update algorithms.

## Build the real-time raw event stream

Run from `dataset`:

```powershell
python -m government_job_update.cli build-event-stream
```

The command preserves the source `publish_time` and creates no synthetic time
points. Its output is deliberately pre-routing: `standard_job` and `skills`
remain empty until the records pass the full government workflow.

## Build the Top-K route review table

```powershell
python -m government_job_update.cli clean-titles
python -m government_job_update.cli route-postings
```

`clean-titles` calls the configured LLM once per unique raw government title
and caches the JSON result. `route-postings` then uses only the LLM-cleaned
title with the real `shibing624/text2vec-base-chinese` model. Full JD text is
is reserved for LLM adjudication and human review. The route command creates
review candidates only; it never writes a route into the formal event stream.

## Process historical government postings

Run a controlled dry-run first. It uses the existing LLM-cleaned title rather
than sending the full JD into text2vec.

```powershell
python -m government_job_update.cli ingest-history --limit 10 --dry-run
```

After checking the output, run the full historical workflow:

```powershell
python -m government_job_update.cli ingest-history
```

For every record, the workflow is:

```text
raw government JD
-> LLM-cleaned title
-> title-only text2vec candidates
-> government LLM route adjudication when needed
-> government-dictionary skill extraction and normalization
-> formal event / frequency / skill pool
-> annual-cycle lifecycle / migration / job-profile outputs
-> independent government SQLite
```

`potential_new_job` and `new_family` records are written to the government
review queue and are not inserted into the formal event stream. Government
lifecycle rules use observed annual recruitment cycles, not missing calendar
months.

## Process one new government JD

```powershell
python -m government_job_update.cli submit-one `
  --month "2026-10" `
  --job-title "某部信息中心系统运维一级主任科员及以下" `
  --responsibility "负责政务信息系统运行维护。" `
  --requirement "计算机相关专业，熟悉系统运维和网络安全。" `
  --source government `
  --publish-time "2026-10-15" `
  --recruitment-year "2027" `
  --government-agency "某部信息中心" `
  --dry-run
```

Omit `--dry-run` only when the result should update the formal government base
CSV files and `government_job_update.db`. Use `--mode manual` to place the
posting into the independent review queue instead of automatically writing it.

## Database and exports

```powershell
python -m government_job_update.cli init-db
python -m government_job_update.cli export-csv
python -m government_job_update.cli rebuild-analytics
```

The government database also stores source name, real publication time, agency,
department, location, and source URL. `export-csv` preserves this provenance in
the government formal event stream.
