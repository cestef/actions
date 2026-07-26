"""Render one badge and stage it for publication.

The renderer is shared with `coverage-report`, so every badge in a repo looks
the same and a fix to the drawing is a fix everywhere.

A badge is only staged when its bytes differ from what is already published,
so a value that has not moved costs no commit.
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from badge import Badge  # noqa: E402


def env(name, default=""):
    return (os.environ.get(f"INPUT_{name}") or default).strip()


def published(base, repo, token, branch, path):
    """The badge currently on the branch, or None when absent or unreadable."""
    if not (base and repo and token):
        return None
    req = urllib.request.Request(
        f"{base.rstrip('/')}/repos/{repo}/contents/{path}?ref={branch}"
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.raw")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except (urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError):
        return None


def main():
    label, value = env("LABEL"), env("VALUE")
    if not label or not value:
        print("::error::badge: both label and value are required")
        return 1

    # A badge may be a plain label/value pair, or carry a proportion that the
    # style can draw and the thresholds can colour.
    raw = env("PERCENT")
    try:
        percent = float(raw) if raw else 0.0
    except ValueError:
        print(f"::error::badge: percent {raw!r} is not a number")
        return 1
    color = env("COLOR") or Badge.color_for(percent, env("THRESHOLDS"))

    badge = Badge.of(
        env("STYLE", "meter") or "meter",
        label=label,
        value=value,
        percent=percent if raw else 100.0,
        color=color,
        label_color=env("LABEL_COLOR", "#24292f") or "#24292f",
    )
    svg = badge.render()

    prefix = env("PATH_PREFIX").strip("/")
    name = env("FILE") or "badge.svg"
    stored = f"{prefix}/{name}" if prefix else name
    branch = env("BRANCH", "badges") or "badges"

    current = published(env("SERVER_URL", "https://api.github.com"), env("REPO"),
                        env("TOKEN"), branch, stored)
    changed = current != svg

    stage = env("STAGE") or "/tmp/badge"
    target = os.path.join(stage, prefix) if prefix else stage
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, name), "w") as handle:
        handle.write(svg)

    raw_host = env("RAW_URL", "https://raw.githubusercontent.com").rstrip("/")
    url = f"{raw_host}/{env('REPO')}/{branch}/{stored}" if env("REPO") else ""
    print(f"badge: {label} = {value} ({'changed' if changed else 'unchanged'}) -> {stored}")

    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
            handle.write(f"url={url}\n")
            handle.write(f"stage={stage}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
