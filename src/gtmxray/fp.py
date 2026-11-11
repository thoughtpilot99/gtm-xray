"""Load fingerprints.yaml once."""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("fingerprints.yaml")


@functools.cache
def load() -> dict:
    return yaml.safe_load(_PATH.read_text(encoding="utf-8"))


def match_substr(text: str, table: dict) -> list[tuple[str, object]]:
    """Return (pattern, value) for every pattern found in text (case-insensitive)."""
    low = text.lower()
    return [(pat, val) for pat, val in table.items() if pat.lower() in low]


_GENERIC_VERIF = re.compile(r"^([a-z0-9][a-z0-9-]{1,40}?)[-_](?:site|domain)?-?verification", re.I)


def generic_txt_vendor(record: str) -> str | None:
    """'figma-domain-verification=abc' -> 'figma'. Catches vendors not in the table."""
    m = _GENERIC_VERIF.match(record.strip().strip('"'))
    if not m or m.group(1).lower() in {"domain", "site", "google", "ms"}:
        return None
    return m.group(1).lower()
