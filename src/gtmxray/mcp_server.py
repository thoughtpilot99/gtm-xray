"""GTM X-Ray as an MCP server, so any MCP client (Claude Code, Claude Desktop, Codex, Cursor,
Gemini CLI) can drive the collectors. Results come back as JSON with evidence ids.

Run: `xray mcp` (stdio). Runs folder: $GTM_XRAY_RUNS or ./runs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import cli, displacement, net, web_xray
from .ledger import Ledger, latest_runs

mcp = _Server("gtm-xray")


def _root() -> Path:
    return Path(os.environ.get("GTM_XRAY_RUNS", Path.cwd() / "runs"))


def _latest(domain: str) -> Path:
    d = net.normalize_domain(domain)
    runs = latest_runs(_root(), d, 1)
    if not runs:
        raise ValueError(f"No run for {d}. Call xray_collect first.")
    return runs[0]


@mcp.tool()
def xray_collect(domain: str, browser: bool = False) -> dict:
    """Run every public-data collector on a company domain (hiring feed, DNS stack, hidden sending
    domains, sitemap, page source, Wayback history, JS/funnel scan). Returns the run folder and headline facts."""
    rd = cli.collect(domain, _root(), set(), browser)
    f = json.loads((rd / "facts.json").read_text(encoding="utf-8"))
    return {"run_dir": str(rd), "open_roles": (f.get("hiring") or {}).get("open_roles"),
            "secondary_sending_domains": f["outbound_capacity"]["secondary_domains"],
            "leak_score": f["leak_score"]["score"], "motion_radar": f["motion_radar"], "errors": f["errors"]}


@mcp.tool()
def xray_facts(domain: str, section: str = "") -> dict:
    """Read collected facts. section: hiring | dns | outbound | sitemap | pagesource | wayback | web |
    motion_radar | leak_score | outbound_capacity. Empty = all."""
    f = json.loads((_latest(domain) / "facts.json").read_text(encoding="utf-8"))
    return f.get(section, {}) if section else f


@mcp.tool()
def xray_ledger(domain: str, module: str = "", kind: str = "") -> list[dict]:
    """Evidence rows (claim, source_url, method, SEEN/INFERRED, confidence). Filter by module or kind."""
    led = Ledger.read(_latest(domain) / "ledger.jsonl")
    return [r.__dict__ for r in led.rows if (not module or r.module == module) and (not kind or r.kind == kind)]


@mcp.tool()
def xray_displacement_queries(tool: str) -> list[str]:
    """Web-search queries that find job posts at OTHER companies naming the competitor's product."""
    return displacement.search_queries(tool)


@mcp.tool()
def xray_verify_jobs(competitor_domain: str, tool: str, urls: list[str]) -> dict:
    """Fetch candidate job-post URLs and keep only those whose text really names the tool."""
    rd = _latest(competitor_domain)
    led = Ledger.read(rd / "ledger.jsonl")
    rows = displacement.verify_job_urls(tool, urls, led, competitor_domain)
    raw = rd / "displacement_raw.json"
    prev = json.loads(raw.read_text(encoding="utf-8")) if raw.exists() else []
    raw.write_text(json.dumps(prev + rows, indent=2), encoding="utf-8")
    led.write(rd / "ledger.jsonl")
    return {"checked": len(urls), "confirmed": rows}


@mcp.tool()
def xray_hn_hiring(competitor_domain: str, tool: str) -> dict:
    """Hacker News 'Who is hiring' comments from the last 12 months that name the tool."""
    rd = _latest(competitor_domain)
    led = Ledger.read(rd / "ledger.jsonl")
    rows = displacement.hn_hiring(tool, led)
    raw = rd / "displacement_raw.json"
    prev = json.loads(raw.read_text(encoding="utf-8")) if raw.exists() else []
    raw.write_text(json.dumps(prev + rows, indent=2), encoding="utf-8")
    led.write(rd / "ledger.jsonl")
    return {"mentions": rows}


@mcp.tool()
def xray_accounts(domain: str, tool: str = "", titles: str = "Head of Growth;VP Sales;RevOps Lead") -> dict:
    """Merge all displacement evidence into ranked accounts + a Clay-ready CSV."""
    rd = cli.accounts(domain, _root(), tool or None, [t for t in titles.split(";") if t])
    acc = json.loads((rd / "accounts.json").read_text(encoding="utf-8"))
    return {"accounts": len(acc), "top": acc[:25], "csv": str(rd / "clay-import.csv")}


@mcp.tool()
def xray_render(domain: str, png: bool = False, audit: bool = False) -> dict:
    """Render report.html (and PNG social cards with png=True) from facts + analysis.json + ledger."""
    from . import render
    return {"report": str(render.render(domain, _root(), png=png, audit=audit))}


@mcp.tool()
def xray_diff(domain: str) -> dict:
    """What changed between the two latest runs (new roles, sending domains, prices, tools, pages)."""
    return cli.diff(domain, _root())


@mcp.tool()
def xray_fetch(url: str, max_chars: int = 12000) -> str:
    """Read any public page as text, including Internet Archive captures (web.archive.org)."""
    return cli.fetch_text(url)[:max_chars]


@mcp.tool()
def xray_har(domain: str, har_path: str) -> dict:
    """Analyze a HAR file the user recorded of their OWN session (events, flags, third parties, API paths)."""
    rd = _latest(domain)
    led = Ledger.read(rd / "ledger.jsonl")
    res = web_xray.har_scan(Path(har_path), domain, led)
    (rd / "har.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    led.write(rd / "ledger.jsonl")
    return res


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
