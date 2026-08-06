from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOB_UPDATE_ROOT = PROJECT_ROOT.parent
COMPANY_ROOT = JOB_UPDATE_ROOT / "company_job_update"
for path in (JOB_UPDATE_ROOT, COMPANY_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
