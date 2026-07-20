# job_update Base Dataset

This folder is the fixed initial dataset for the existing-job update workflow.
Do not overwrite it with the data-stream generator during normal demos.

Files:

- `standard_job_title_dictionary.csv`: standard job taxonomy used by routing.
- `job_update_event_stream.csv`: initialized historical event stream.
- `job_skill_monthly_frequency.csv`: frequency table rebuilt from the initialized event stream.
- `skill_pool.csv`: initialized dynamic skill pool rebuilt from the latest generated event stream and `skill_pool_by_job.csv`. It already contains `normalized_skill + kg_display_skill` and continues to grow through `process-one`.

Normal single-posting update command:

```powershell
python -m job_update.cli process-one `
  --title-dictionary "B:\揭榜挂帅\dataset\job_update\data\base\standard_job_title_dictionary.csv" `
  --event-stream "B:\揭榜挂帅\dataset\job_update\data\base\job_update_event_stream.csv" `
  --frequency-output "B:\揭榜挂帅\dataset\job_update\data\base\job_skill_monthly_frequency.csv" `
  --skill-pool "B:\揭榜挂帅\dataset\job_update\data\base\skill_pool.csv" `
  --job-id "manual_001" `
  --month "2026-07" `
  --job-title "AI Infra工程师" `
  --requirement "..." 
```
