---
description: Map a whole market - find the top players in a category and X-ray them all
argument-hint: "<category, e.g. AI app builders>"
---
Map the market: $ARGUMENTS

1. Use WebSearch to find the 6-10 most relevant companies in this category (prefer funded, active, B2B-relevant).
   Show the list with one-line reasons and their domains.
2. Collect all of them in parallel (`uv run --project "${CLAUDE_PLUGIN_ROOT}" xray collect <domain>`), then `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray compare <all domains>`.
3. Rank them on: open GTM roles, enterprise push, outbound infrastructure, SEO footprint, comparison-page
   aggression, international build-out. Name the white space.
