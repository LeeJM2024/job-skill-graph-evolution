# job_update Base Dataset

This folder is the fixed initial dataset for the existing-job update workflow.
Do not overwrite it with the data-stream generator during normal demos.

Files:

- `standard_job_title_dictionary.csv`: standard job taxonomy used by title routing.
- `job_update_event_stream.csv`: initialized historical event stream.
- `job_skill_monthly_frequency.csv`: monthly and cumulative skill frequency table rebuilt from the initialized event stream.
- `skill_pool.csv`: initialized dynamic skill pool. It contains `normalized_skill` and `kg_display_skill`, and grows when users submit new postings.
- `skill_lifecycle.csv`: current lifecycle status for each `standard_job + skill` pair.
- `skill_migration.csv`: one-row-per-skill migration summary, including first seen jobs and later spread jobs.
- `skill_job_monthly_spread.csv`: monthly `skill + standard_job` spread details, including frequency changes and coverage counts.
- `job_update.db`: SQLite copy of the base CSV state used by the workflow and exports.

Normal single-posting update command:

```powershell
python -m core.cli submit-one `
  --month "2026-07" `
  --job-title "AI Infra Engineer" `
  --responsibility "..." `
  --requirement "..."
```

`submit-one` uses this folder by default and automatically generates `job_id`.
Use `--dry-run` to inspect the result without writing files.

Maintenance commands:

```powershell
python -m core.cli rebuild-skill-pool --skill-universe "B:\揭榜挂帅\dataset\岗位数据流生成与评测系统\outputs\skill_trend_design.csv"
python -m core.cli rebuild-frequency --event-stream data\base\job_update_event_stream.csv --output data\base\job_skill_monthly_frequency.csv
python -m core.cli rebuild-lifecycle
python -m core.cli rebuild-migration
python -m core.cli init-db
python -m core.cli export-csv
```
