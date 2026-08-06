"""Convenience package entry point for commands run from dataset root."""

from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parent
__path__.append(str(PACKAGE_ROOT / "core"))
JOB_UPDATE_ROOT = PACKAGE_ROOT.parent
if str(JOB_UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(JOB_UPDATE_ROOT))
COMPANY_CORE_ROOT = JOB_UPDATE_ROOT / "company_job_update"
if str(COMPANY_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPANY_CORE_ROOT))
