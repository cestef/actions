"""Turn a coverage report into a badge, a job summary and a pull-request comment.

Every view (badge, summary, comment, ratchet) is derived from one parse, so they
can never disagree about a number. State -- the previous run's per-file coverage
-- lives in a JSON file on an orphan branch of the repo itself, so this needs no
bucket and no credentials beyond the workflow's own token.

Nothing here is specific to a language, a coverage tool, or a repository: the
report format, the badge style, the file names, the hosts and every surface are
inputs. Adding a format is one class plus one line in `SOURCES`; adding a badge
style is one class plus one line in `STYLES`.
"""

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# The badge renderer is shared with the `badge` action, so both draw the same
# thing and a fix to one is a fix to both.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from badge import Badge  # noqa: E402

SCHEMA = 2


def env(name, default=""):
    """An action input, which arrives as INPUT_<NAME> and may be present-but-empty."""
    return (os.environ.get(f"INPUT_{name}") or default).strip()


def flag(name, default="false"):
    return env(name, default).lower() in ("1", "true", "yes", "on")


# --- report formats --------------------------------------------------------
#
# Each source turns a file into {path: (covered, statements)}. Register one line
# in SOURCES and it becomes a valid `format:` value.


class Cobertura:
    """Cobertura XML, as emitted by tarpaulin, coverage.py, JaCoCo's converter."""

    EXTENSIONS = (".xml",)

    @staticmethod
    def parse(path):
        files = {}
        for cls in ET.parse(path).getroot().iter("class"):
            name = cls.get("filename")
            if not name:
                continue
            covered, total = files.get(name, (0, 0))
            for line in cls.iter("line"):
                total += 1
                covered += int(line.get("hits", "0")) > 0
            files[name] = (covered, total)
        return files


class Lcov:
    """LCOV tracefiles, as emitted by llvm-cov, grcov, nyc, gcovr."""

    EXTENSIONS = (".info", ".lcov")

    @staticmethod
    def parse(path):
        files, name, covered, total = {}, None, 0, 0
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("SF:"):
                    name, covered, total = line[3:], 0, 0
                elif line.startswith("DA:") and name:
                    _, _, rest = line.partition(":")
                    hits = rest.split(",")[1] if "," in rest else "0"
                    total += 1
                    covered += int(float(hits)) > 0
                elif line in ("end_of_record", "end_of_record;") and name:
                    was_c, was_t = files.get(name, (0, 0))
                    files[name] = (was_c + covered, was_t + total)
                    name = None
        return files


SOURCES = {"cobertura": Cobertura, "lcov": Lcov}


class Coverage:
    """Per-file and total line coverage, independent of where it was parsed from."""

    def __init__(self, files):
        self.files = files

    @classmethod
    def read(cls, path, fmt="auto"):
        if fmt in ("", "auto"):
            suffix = os.path.splitext(path)[1].lower()
            source = next(
                (s for s in SOURCES.values() if suffix in s.EXTENSIONS), Cobertura
            )
        elif fmt in SOURCES:
            source = SOURCES[fmt]
        else:
            raise SystemExit(
                f"::error::unknown format {fmt!r}; expected auto or one of "
                + ", ".join(sorted(SOURCES))
            )
        return cls(source.parse(path))

    covered = property(lambda self: sum(c for c, _ in self.files.values()))
    total = property(lambda self: sum(t for _, t in self.files.values()))

    @property
    def percent(self):
        return 100.0 * self.covered / self.total if self.total else 0.0

    def pct(self, path):
        covered, total = self.files.get(path, (0, 0))
        return 100.0 * covered / total if total else None

    # Fields that describe *when* a measurement happened rather than *what* it
    # was. They change on every run, so they are excluded when deciding whether
    # anything is worth publishing.
    VOLATILE = ("commit", "updated")

    def state(self, commit, badge_key):
        return {
            "schema": SCHEMA,
            "percent": round(self.percent, 2),
            "covered": self.covered,
            "total": self.total,
            # A digest of the rendered SVG. Keying on the *output* rather than
            # on the inputs that produce it means a change to the renderer
            # itself republishes too: keying on style/label/colour once left a
            # badge with 1px text pinned in place, because none of those had
            # moved and the fix therefore looked like a no-op.
            "badge": badge_key,
            "commit": commit,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": {k: list(v) for k, v in sorted(self.files.items())},
        }

    @classmethod
    def differs(cls, new, old):
        """Whether `new` state is worth publishing over `old`.

        Compared on substance only: without this, the timestamp alone lands a
        commit on the badge branch for every push, forever.
        """
        if not old:
            return True
        strip = lambda d: {k: v for k, v in d.items() if k not in cls.VOLATILE}
        return strip(new) != strip(old)


# --- the forge -------------------------------------------------------------


class Api:
    """The REST calls this needs. Falsy without a token, and every call degrades."""

    def __init__(self, base, repo, token):
        self.base, self.repo, self.token = base.rstrip("/"), repo, token

    def __bool__(self):
        return bool(self.base and self.repo and self.token)

    def request(self, method, path, payload=None, raw=False):
        req = urllib.request.Request(f"{self.base}{path}", method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header(
            "Accept",
            "application/vnd.github.raw" if raw else "application/vnd.github+json",
        )
        if payload is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(payload).encode()
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
        return body if raw else json.loads(body or b"null")

    def baseline(self, branch, path):
        """The stored state, or None when the branch, the file or access is absent."""
        try:
            body = self.request(
                "GET", f"/repos/{self.repo}/contents/{path}?ref={branch}", raw=True
            )
            return json.loads(body)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
            return None

    def upsert_comment(self, pr, marker, body):
        base = f"/repos/{self.repo}/issues"
        try:
            existing = self.request("GET", f"{base}/{pr}/comments?per_page=100")
            mine = next((c for c in existing if marker in (c.get("body") or "")), None)
            if mine:
                self.request("PATCH", f"{base}/comments/{mine['id']}", {"body": body})
                return "updated"
            self.request("POST", f"{base}/{pr}/comments", {"body": body})
            return "posted"
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            # A fork PR gets a read-only token: worth a line, never worth failing.
            return f"skipped ({e})"


# --- the human-facing report ----------------------------------------------


class Report:
    """The summary and comment bodies, rendered from a coverage delta."""

    def __init__(self, cov, baseline, label, top):
        self.cov, self.label, self.top = cov, label, top
        self.base = baseline or {}
        self.prev = {k: tuple(v) for k, v in (self.base.get("files") or {}).items()}

    @property
    def delta(self):
        was = self.base.get("percent")
        return None if was is None else self.cov.percent - was

    def moved(self, epsilon=0.05):
        """Files whose coverage changed, worst regression first."""
        rows = []
        for path in sorted(set(self.cov.files) | set(self.prev)):
            now = self.cov.pct(path)
            covered, total = self.prev.get(path, (0, 0))
            before = 100.0 * covered / total if total else None
            if now is None:
                rows.append((path, before, None, -100.0))
            elif before is None:
                rows.append((path, None, now, 0.0))
            elif abs(now - before) >= epsilon:
                rows.append((path, before, now, now - before))
        rows.sort(key=lambda row: (row[3], row[0]))
        return rows

    @staticmethod
    def _cell(value):
        return "--" if value is None else f"{value:.1f}%"

    def _table(self, rows):
        out = ["| File | Before | After | Change |", "|---|---:|---:|---:|"]
        for path, before, after, diff in rows:
            if before is None:
                change = "new"
            elif after is None:
                change = "removed"
            else:
                change = f"{diff:+.1f}"
            out.append(
                f"| `{path}` | {self._cell(before)} | {self._cell(after)} | {change} |"
            )
        return "\n".join(out)

    def body(self, badge_url, note):
        cov = self.cov
        head = f"## {self.label} — **{cov.percent:.2f}%**"
        if self.delta is not None:
            against = (self.base.get("commit") or "")[:7] or "baseline"
            head += f" ({self.delta:+.2f} vs `{against}`)"
        lines = [head, "", f"`{cov.covered:,}` of `{cov.total:,}` lines covered."]
        if badge_url:
            lines += ["", f"![{self.label}]({badge_url})"]

        # Without a baseline every file would read as "new", which is noise: the
        # per-file table only means anything as a comparison.
        rows = self.moved() if self.base else []
        if rows:
            shown, rest = rows[: self.top], rows[self.top :]
            lines += ["", f"### {len(rows)} file(s) moved", "", self._table(shown)]
            if rest:
                lines += [
                    "",
                    f"<details><summary>{len(rest)} more</summary>",
                    "",
                    self._table(rest),
                    "",
                    "</details>",
                ]
        elif self.base:
            lines += ["", "_No per-file coverage changed._"]
        if note:
            lines += ["", note]
        return "\n".join(lines) + "\n"


def main():
    path = env("FILE") or "cobertura.xml"
    if not os.path.exists(path):
        print(f"::error::coverage report not found: {path}")
        return 1
    cov = Coverage.read(path, env("FORMAT", "auto"))
    if not cov.total:
        print(f"::error::{path} reported no measurable lines")
        return 1

    label = env("BADGE_LABEL", "coverage") or "coverage"
    marker = env("MARKER") or "<!-- coverage-report -->"
    branch = env("BRANCH", "badges") or "badges"
    prefix = env("PATH_PREFIX").strip("/")
    badge_file = env("BADGE_FILE", "coverage.svg") or "coverage.svg"
    state_file = env("STATE_FILE", "coverage.json") or "coverage.json"
    stored = lambda name: f"{prefix}/{name}" if prefix else name

    api = Api(env("SERVER_URL", "https://api.github.com"), env("REPO"), env("TOKEN"))
    baseline = api.baseline(branch, stored(state_file)) if api else None
    report = Report(cov, baseline, label, int(env("TOP", "10") or 10))

    delta = f"{report.delta:+.2f}" if report.delta is not None else "n/a"
    was = baseline.get("percent") if baseline else None
    print(f"coverage={cov.percent:.2f}% baseline={was if was is not None else 'none'} delta={delta}")

    # The badge and the state file are staged; publishing them is the caller's
    # step, so a run that only reports touches no branch.
    stage = env("STAGE") or "/tmp/coverage-report"
    target = os.path.join(stage, prefix) if prefix else stage
    os.makedirs(target, exist_ok=True)
    style = env("BADGE_STYLE", "meter") or "meter"
    label_color = env("BADGE_LABEL_COLOR", "#24292f") or "#24292f"
    color = Badge.color_for(cov.percent, env("BADGE_THRESHOLDS"))
    badge = Badge.of(
        style,
        label=label,
        value=f"{cov.percent:.1f}%",
        percent=cov.percent,
        color=color,
        label_color=label_color,
    )
    svg = badge.render()
    with open(os.path.join(target, badge_file), "w") as handle:
        handle.write(svg)
    state = cov.state(env("COMMIT"), hashlib.sha1(svg.encode()).hexdigest()[:16])
    with open(os.path.join(target, state_file), "w") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    changed = Coverage.differs(state, baseline)
    if not changed:
        print("coverage-report: unchanged, nothing to publish")

    # Ratchet: a pull request may not drop below the baseline minus a tolerance.
    note, failed = "", False
    on_pr = env("EVENT_NAME") == "pull_request" and env("PR_NUMBER")
    if flag("RATCHET") and baseline and on_pr:
        floor = baseline["percent"] - float(env("TOLERANCE", "0.5") or 0.5)
        failed = cov.percent < floor
        verdict = "Below" if failed else "At or above"
        note = f"> {verdict} the ratchet floor of **{floor:.2f}%**."

    raw = env("RAW_URL", "https://raw.githubusercontent.com").rstrip("/")
    repo = env("REPO")
    badge_url = (
        f"{raw}/{repo}/{branch}/{stored(badge_file)}" if repo and flag("BADGE_LINK", "true") else ""
    )
    body = report.body(badge_url, note)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and flag("SUMMARY", "true"):
        with open(summary, "a") as handle:
            handle.write(body)
    if on_pr and api and flag("COMMENT", "true"):
        comment = marker + "\n" + body
        print("pr comment: " + api.upsert_comment(env("PR_NUMBER"), marker, comment))

    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as handle:
            handle.write(f"percent={cov.percent:.2f}\n")
            handle.write(f"delta={delta}\n")
            handle.write(f"covered={cov.covered}\n")
            handle.write(f"total={cov.total}\n")
            handle.write(f"stage={stage}\n")
            handle.write(f"changed={'true' if changed else 'false'}\n")

    if failed:
        print(f"::error::coverage {cov.percent:.2f}% is below the ratchet floor")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
