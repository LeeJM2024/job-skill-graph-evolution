from __future__ import annotations

from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split())


def split_semicolon(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]
