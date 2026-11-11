# Contributing

Most useful PRs:
1. **Fingerprints** (`src/gtmxray/fingerprints.yaml`): DNS tokens, SPF includes, tracking CNAMEs, page-source
   patterns. Include one public site where you saw it.
2. **ATS adapters** (`src/gtmxray/ats.py`): more public job-board feeds.
3. **Agents** (`agents/*.md`): sharper investigation prompts. Keep the finding shape.
4. **Voice packs** (`voice-packs/`): generic styles only, no real people.

Run `uv run pytest -m "not live"` before opening a PR.
