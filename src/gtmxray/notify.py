"""Send a watch diff to Slack (SLACK_WEBHOOK_URL) or print it as Markdown."""

from __future__ import annotations

import os

from . import net


def to_markdown(diff: dict) -> str:
    lines = [f"*GTM X-Ray watch: {diff['domain']}* ({diff.get('from', '?')} -> {diff.get('to', '?')})"]
    if not diff.get("changes"):
        lines.append(diff.get("note", "No changes."))
    for c in diff.get("changes", []):
        after = c["after"]
        if isinstance(after, list):
            after = ", ".join(map(str, after[:10])) + (" ..." if len(after) > 10 else "")
        lines.append(f"- *{c['what']}*: {c['before']} -> {after}")
    return "\n".join(lines)


def send(diff: dict) -> None:
    text = to_markdown(diff)
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if not hook:
        print(text)
        return
    with net.client() as c:
        r = c.post(hook, json={"text": text})
    print(f"slack: {r.status_code}")
