---
description: Turn a GTM X-Ray run into an X post, thread, article, LinkedIn post and carousel
argument-hint: <domain> [voice-pack path]
---
Turn the latest X-Ray of $ARGUMENTS into content.

Use the content-writer agent with the run folder and the voice pack (default voice-packs/generic.md, or the path
given). If no analysis.json exists yet, run /xray first. Render social cards with `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray render <domain> --png`
and reference them in the drafts.
