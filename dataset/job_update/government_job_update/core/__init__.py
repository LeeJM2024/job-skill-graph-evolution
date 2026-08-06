"""Government technical-job update domain.

This package owns government-only data, dictionaries, and policy. It imports
only low-level helpers from dataset/job_update/shared and never reads company base data.
"""

from __future__ import annotations

import sys
from pathlib import Path


JOB_UPDATE_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = JOB_UPDATE_ROOT.parent
if str(JOB_UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(JOB_UPDATE_ROOT))

# Reuse the tested update algorithms while keeping all government inputs and
# outputs under government_job_update/data/base.
COMPANY_CORE_ROOT = JOB_UPDATE_ROOT / "company_job_update"
if str(COMPANY_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPANY_CORE_ROOT))
