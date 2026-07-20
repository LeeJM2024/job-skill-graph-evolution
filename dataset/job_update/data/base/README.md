# job_update Base Dataset

This folder is the fixed initial dataset for the existing-job update workflow.
Do not overwrite it with the data-stream generator during normal demos.

Files:

- `standard_job_title_dictionary.csv`: standard job taxonomy used by title routing.
- `job_update_event_stream.csv`: initialized historical event stream.
- `job_skill_monthly_frequency.csv`: monthly and cumulative skill frequency table rebuilt from the initialized event stream.
- `skill_pool.csv`: initialized dynamic skill pool. It contains `normalized_skill` and `kg_display_skill`, and grows when users submit new postings.

Normal single-posting update command:

```powershell
python -m job_update.cli submit-one `
  --month "2026-07" `
  --job-title "AI Infra工程师" `
  --responsibility "..." `
  --requirement "..."
```

`submit-one` uses this folder by default and automatically generates `job_id`.
Use `--dry-run` to inspect the result without writing files.
