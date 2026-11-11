# AGENTS.md

Instructions for any coding agent (Claude Code, Codex, Cursor, Gemini CLI) working with GTM X-Ray.

## Using the tool
- Collectors: `uv run xray collect <domain>` writes `runs/<domain>/<date>/{facts.json, roles.json, ledger.jsonl}`.
- MCP: `uv run xray mcp` exposes `xray_collect`, `xray_facts`, `xray_ledger`, `xray_displacement_queries`,
  `xray_verify_jobs`, `xray_hn_hiring`, `xray_accounts`, `xray_render`, `xray_diff`, `xray_har`.
- The method, finding shape and `analysis.json` contract live in `skills/gtm-xray/SKILL.md`. Agent prompts in
  `agents/` work as plain instructions in any agent that lacks subagents: run them one after another.

## Rules
- Public data only. No logins, no form submissions, no private APIs. HAR files only from the user's own sessions.
- Every number traces to `ledger.jsonl` or a cited URL. Estimates are labelled ESTIMATE with their math.
- Never invent customers, people, quotes or numbers.

## Developing
- `uv sync --extra render`, `uv run pytest -m "not live"` (offline), `uv run pytest -m live` (network).
- New fingerprints go in `src/gtmxray/fingerprints.yaml` with a real site you saw them on in the PR.
