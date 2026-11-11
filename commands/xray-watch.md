---
description: Re-run a GTM X-Ray and report what changed since the last run
argument-hint: <domain>
---
Watch: $ARGUMENTS

1. `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray collect $ARGUMENTS` then `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray diff $ARGUMENTS`.
2. Explain each change in one line and what it means (new SDR roles = outbound push; new sending domain = new
   campaign; price change = window for their customers; new comparison page = new rival).
3. If SLACK_WEBHOOK_URL is set, `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray notify $ARGUMENTS`.
For a weekly schedule, use the GitHub Action in .github/workflows/xray-watch.yml.
