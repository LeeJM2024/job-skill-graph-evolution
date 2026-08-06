from __future__ import annotations

import hashlib
import re
from typing import Any


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def stable_identifier(prefix: str, *parts: Any) -> str:
    payload = "|".join(clean_text(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"
