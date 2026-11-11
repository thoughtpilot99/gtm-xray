"""Evidence ledger.

Every fact the tool states is a row here: what was seen, where, how, and whether it was
SEEN (read straight off a public source) or INFERRED (a conclusion drawn from SEEN rows).
The report renderer refuses to show a claim that has no ledger row behind it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SEEN = "SEEN"
INFERRED = "INFERRED"


@dataclass
class Evidence:
    module: str
    claim: str
    source_url: str
    method: str
    kind: str = SEEN
    value: object = None
    confidence: float = 0.9
    collected_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    )
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            h = hashlib.sha1(f"{self.module}|{self.claim}|{self.source_url}".encode()).hexdigest()
            self.id = f"ev_{h[:10]}"


class Ledger:
    def __init__(self) -> None:
        self.rows: list[Evidence] = []

    def add(self, module: str, claim: str, source_url: str, method: str, **kw) -> Evidence:
        ev = Evidence(module=module, claim=claim, source_url=source_url, method=method, **kw)
        if not any(r.id == ev.id for r in self.rows):
            self.rows.append(ev)
        return ev

    def extend(self, other: "Ledger") -> None:
        for r in other.rows:
            if not any(x.id == r.id for x in self.rows):
                self.rows.append(r)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in self.rows:
                f.write(json.dumps(asdict(r), ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def read(path: Path) -> "Ledger":
        led = Ledger()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    led.rows.append(Evidence(**json.loads(line)))
        return led


def run_dir(root: Path, domain: str, date: str | None = None) -> Path:
    date = date or dt.date.today().isoformat()
    return root / domain / date


def latest_runs(root: Path, domain: str, n: int = 2) -> list[Path]:
    base = root / domain
    if not base.exists():
        return []
    dirs = sorted([p for p in base.iterdir() if p.is_dir()], reverse=True)
    return dirs[:n]
