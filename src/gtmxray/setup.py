"""One-command setup: register the GTM X-Ray MCP server with your coding agents.

  uvx --from git+https://github.com/thoughtpilot99/gtm-xray xray setup --agents claude,codex,cursor,gemini

Shows every change first, backs up each config file, and asks before writing.
For Claude Code the full plugin (commands, agents, skill) installs with:
  /plugin marketplace add thoughtpilot99/gtm-xray
  /plugin install gtm-xray@gtm-xray
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

SOURCE = "git+https://github.com/thoughtpilot99/gtm-xray"
CMD = ["uvx", "--from", SOURCE, "xray", "mcp"]
HOME = Path.home()


def _backup(p: Path) -> None:
    if p.exists():
        b = p.with_suffix(p.suffix + f".bak-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(p, b)
        print(f"  backup: {b}")


def _json_merge(p: Path, key: str) -> None:
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data.setdefault(key, {})["gtm-xray"] = {"command": CMD[0], "args": CMD[1:]}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def plan(agent: str) -> tuple[str, callable]:
    if agent == "claude":
        cmd = ["claude", "mcp", "add", "--scope", "user", "gtm-xray", "--", *CMD]
        return f"run: {' '.join(cmd)}", lambda: subprocess.run(cmd, check=False)
    if agent == "cursor":
        p = HOME / ".cursor" / "mcp.json"
        return f"add mcpServers.gtm-xray to {p}", lambda: (_backup(p), _json_merge(p, "mcpServers"))
    if agent == "gemini":
        p = HOME / ".gemini" / "settings.json"
        return f"add mcpServers.gtm-xray to {p}", lambda: (_backup(p), _json_merge(p, "mcpServers"))
    if agent == "codex":
        p = HOME / ".codex" / "config.toml"
        block = f'\n[mcp_servers.gtm-xray]\ncommand = "{CMD[0]}"\nargs = {json.dumps(CMD[1:])}\n'

        def do():
            _backup(p)
            p.parent.mkdir(parents=True, exist_ok=True)
            txt = p.read_text(encoding="utf-8") if p.exists() else ""
            if "[mcp_servers.gtm-xray]" not in txt:
                p.write_text(txt + block, encoding="utf-8")
        return f"append [mcp_servers.gtm-xray] to {p}", do
    raise SystemExit(f"Unknown agent '{agent}'. Use claude, codex, cursor, gemini.")


def run(agents: list[str], assume_yes: bool = False) -> None:
    steps = [(a, *plan(a)) for a in agents]
    print("GTM X-Ray setup will:")
    for a, desc, _ in steps:
        print(f"  [{a}] {desc}")
    if not assume_yes and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Nothing changed.")
        return
    for a, _, fn in steps:
        fn()
        print(f"  [{a}] done")
    print("Restart your agent(s). Then ask: \"X-ray competitor.com and build me an attack plan\".")
