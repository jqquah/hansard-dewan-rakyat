#!/usr/bin/env python3
"""Claim bot. Runs in GitHub Actions only. It never runs code from pull requests.

  python tools/bot.py comment   handle /claim /release /blocked /verify /verified /reject
  python tools/bot.py pr        check a pull request's data files (pull_request_target)
  python tools/bot.py sweep     expire old claims and update the status board (hourly)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ.get("GITHUB_REPOSITORY", "jqquah/hansard-dewan-rakyat")
MAX_CLAIMS = 3
CLAIM_HOURS = 24
VERIFY_HOURS = 6
STATUSES = ["status:todo", "status:claimed", "status:needs-verify", "status:verifying",
            "status:changes-needed", "status:blocked", "status:done"]


def gh(*args: str, check: bool = True) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {p.stderr}")
    return p.stdout.strip()


def ghj(*args: str):
    out = gh(*args)
    return json.loads(out) if out else None


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def set_status(kind: str, number: int, status: str):
    """Exactly one status label at a time."""
    labels = [l["name"] for l in ghj(kind, "view", str(number), "-R", REPO, "--json", "labels")["labels"]]
    remove = [l for l in labels if l.startswith("status:") and l != status]
    args = [kind, "edit", str(number), "-R", REPO, "--add-label", status]
    for r in remove:
        args += ["--remove-label", r]
    gh(*args)


def reply(kind: str, number: int, text: str):
    gh(kind, "comment", str(number), "-R", REPO, "--body", text)


def linked_issue(pr_body: str) -> int | None:
    m = re.search(r"(?:closes|fixes|resolves)\s+#(\d+)", pr_body or "", re.I)
    return int(m.group(1)) if m else None


def is_maintainer(user: str) -> bool:
    p = subprocess.run(["gh", "api", f"repos/{REPO}/collaborators/{user}/permission", "--jq", ".permission"],
                       capture_output=True, text=True)
    return p.stdout.strip() in ("admin", "maintain", "write")

# ---------------------------------------------------------------------------


def handle_comment():
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    body = (ev["comment"]["body"] or "").strip()
    cmd = body.split()[0].lower() if body else ""
    if cmd not in ("/claim", "/release", "/blocked", "/verify", "/verified", "/reject"):
        return
    user = ev["comment"]["user"]["login"]
    item = ev["issue"]
    number = item["number"]
    is_pr = "pull_request" in item
    kind = "pr" if is_pr else "issue"
    labels = [l["name"] for l in item["labels"]]
    assignees = [a["login"] for a in item["assignees"]]

    if cmd == "/claim" and not is_pr:
        if item["state"] != "open" or "status:todo" not in labels or assignees:
            reply(kind, number, f"@{user} this job is not free. Run `python hansard.py work` to get another one.")
            return
        mine = ghj("issue", "list", "-R", REPO, "--assignee", user, "--label", "status:claimed",
                   "--state", "open", "--json", "number") or []
        if len(mine) >= MAX_CLAIMS:
            reply(kind, number, f"@{user} you already have {len(mine)} claimed jobs. Finish one first.")
            return
        gh("issue", "edit", str(number), "-R", REPO, "--add-assignee", user)
        set_status("issue", number, "status:claimed")
        reply(kind, number, f"Claimed by @{user}.\n\nclaimed-at: {iso(now())}\n"
                            f"This claim ends after {CLAIM_HOURS} hours if there is no pull request.")
    elif cmd == "/release":
        if user not in assignees and not is_maintainer(user):
            return
        for a in assignees:
            gh(kind, "edit", str(number), "-R", REPO, "--remove-assignee", a)
        set_status(kind, number, "status:needs-verify" if is_pr else "status:todo")
        reply(kind, number, "Released. Someone else can take it now.")
    elif cmd == "/blocked" and not is_pr:
        if user not in assignees and not is_maintainer(user):
            return
        for a in assignees:
            gh("issue", "edit", str(number), "-R", REPO, "--remove-assignee", a)
        set_status("issue", number, "status:blocked")
        reply(kind, number, "Marked as blocked. A maintainer will look at the error above.")
    elif cmd == "/verify" and is_pr:
        author = item["user"]["login"]
        if user == author:
            reply(kind, number, f"@{user} you cannot verify your own pull request.")
            return
        if "status:needs-verify" not in labels or assignees:
            reply(kind, number, f"@{user} this pull request is not free to verify.")
            return
        gh("pr", "edit", str(number), "-R", REPO, "--add-assignee", user)
        set_status("pr", number, "status:verifying")
        reply(kind, number, f"Verification by @{user}.\n\nclaimed-at: {iso(now())}")
    elif cmd in ("/verified", "/reject") and is_pr:
        author = item["user"]["login"]
        if user not in assignees or user == author or "status:verifying" not in labels:
            return
        issue_no = linked_issue(item.get("body") or "")
        if cmd == "/verified":
            p = subprocess.run(["gh", "pr", "merge", str(number), "-R", REPO, "--squash", "--delete-branch=false"],
                               capture_output=True, text=True)
            if p.returncode != 0:
                set_status("pr", number, "status:blocked")
                reply(kind, number, f"Verified, but the merge failed. A maintainer will look.\n\n```\n{p.stderr[-1500:]}\n```")
                return
            set_status("pr", number, "status:done")
            if issue_no:
                set_status("issue", issue_no, "status:done")
                gh("issue", "close", str(issue_no), "-R", REPO, check=False)
        else:
            set_status("pr", number, "status:blocked")
            if issue_no:
                set_status("issue", issue_no, "status:blocked")
            reply(kind, number, "The two conversions do not agree. A maintainer will look.")

# ---------------------------------------------------------------------------


def handle_pr():
    """Validate a PR's data files with the main branch's code. PR code never runs."""
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    pr = ev["pull_request"]
    number, author = pr["number"], pr["user"]["login"]
    issue_no = linked_issue(pr["body"] or "")
    problems = []
    if not issue_no:
        problems.append("The PR body must say `Closes #<issue number>`.")
    else:
        issue = ghj("issue", "view", str(issue_no), "-R", REPO, "--json", "assignees,body")
        if author not in [a["login"] for a in issue["assignees"]]:
            problems.append(f"Issue #{issue_no} is not assigned to @{author}. Claim it first with `/claim`.")
    job_sittings = None
    if issue_no:
        m = re.search(r"job:\s*(p\d+-s\d+-m\d+(?:-j\d+)?)", issue.get("body") or "")
        if m:
            import csv
            with open(ROOT / "manifest" / "sittings.csv", newline="", encoding="utf-8") as f:
                job_sittings = {r["sitting_id"] for r in csv.DictReader(f) if r["job_id"] == m.group(1)}
        else:
            problems.append(f"Issue #{issue_no} is not a conversion job.")
    files = ghj("pr", "view", str(number), "-R", REPO, "--json", "files")["files"]
    paths = [f["path"] for f in files]
    outside = [p for p in paths if not re.fullmatch(r"data/\d{4}/[0-9A-Za-z.\-]+\.md", p)]
    if outside:
        problems.append("A conversion PR can only change files in `data/`. Other files: "
                        + ", ".join(f"`{p}`" for p in outside[:10]))
    if not problems:
        head = pr["head"]["sha"]
        subprocess.run(["git", "fetch", "-q", "origin", f"pull/{number}/head"], cwd=ROOT, check=True)
        with tempfile.TemporaryDirectory() as tmp:
            for p in paths:
                blob = subprocess.run(["git", "show", f"{head}:{p}"], cwd=ROOT, capture_output=True)
                if blob.returncode != 0:
                    continue  # deleted file
                sid = re.sub(r"\.part\d+$", "", Path(p).stem)
                if job_sittings is not None and sid not in job_sittings:
                    problems.append(f"`{p}` is not part of the job in Issue #{issue_no}.")
                dest = Path(tmp) / p
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob.stdout)
            if problems:
                r = None
            else:
                r = subprocess.run([sys.executable, str(ROOT / "hansard.py"), "check", str(Path(tmp) / "data")],
                               cwd=ROOT, capture_output=True, text=True)
            if r is not None and r.returncode != 0:
                out = r.stdout.replace(tmp + "/", "")
                problems.append("`hansard.py check` failed:\n\n```\n" + out[-3000:] + "\n```")
    if problems:
        set_status("pr", number, "status:changes-needed")
        if issue_no:
            set_status("issue", issue_no, "status:changes-needed")
        reply("pr", number, "Checks failed:\n\n" + "\n\n".join(f"- {p}" for p in problems))
        sys.exit(1)
    set_status("pr", number, "status:needs-verify")
    set_status("issue", issue_no, "status:needs-verify")
    reply("pr", number, f"Checks passed for {len(paths)} files. Now a second volunteer will convert "
                        "the same PDFs and compare. Their `hansard.py work` does this automatically.")

# ---------------------------------------------------------------------------


def claimed_at(kind: str, number: int) -> dt.datetime | None:
    comments = ghj(kind, "view", str(number), "-R", REPO, "--json", "comments")["comments"]
    for c in reversed(comments):
        m = re.search(r"claimed-at: (\S+)", c["body"])
        if m:
            return dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return None


def sweep():
    # 1. expire claims with no PR
    open_prs = ghj("pr", "list", "-R", REPO, "--state", "open", "--json", "body", "--limit", "500") or []
    linked = {linked_issue(p["body"]) for p in open_prs}
    for issue in ghj("issue", "list", "-R", REPO, "--label", "status:claimed", "--state", "open",
                     "--json", "number,assignees", "--limit", "500") or []:
        if issue["number"] in linked:
            continue
        t = claimed_at("issue", issue["number"])
        if t and now() - t > dt.timedelta(hours=CLAIM_HOURS):
            for a in issue["assignees"]:
                gh("issue", "edit", str(issue["number"]), "-R", REPO, "--remove-assignee", a["login"])
            set_status("issue", issue["number"], "status:todo")
            reply("issue", issue["number"], f"Claim ended after {CLAIM_HOURS} hours with no pull request. This job is free again.")
    # 2. expire verifications
    for pr in ghj("pr", "list", "-R", REPO, "--label", "status:verifying", "--state", "open",
                  "--json", "number,assignees", "--limit", "500") or []:
        t = claimed_at("pr", pr["number"])
        if t and now() - t > dt.timedelta(hours=VERIFY_HOURS):
            for a in pr["assignees"]:
                gh("pr", "edit", str(pr["number"]), "-R", REPO, "--remove-assignee", a["login"])
            set_status("pr", pr["number"], "status:needs-verify")
            reply("pr", pr["number"], "Verification ended with no result. It is free to verify again.")
    # 3. status board
    counts = {}
    for s in STATUSES:
        state = "all" if s == "status:done" else "open"
        items = ghj("issue", "list", "-R", REPO, "--label", s, "--state", state, "--json", "number", "--limit", "2000") or []
        counts[s] = len(items)
    active = ghj("issue", "list", "-R", REPO, "--label", "status:claimed", "--state", "open",
                 "--json", "number,title,assignees", "--limit", "100") or []
    total = sum(counts.values()) or 1
    lines = ["# Status board", "", f"Updated {iso(now())} (every hour).", "",
             f"**Done: {counts['status:done']} of {total} jobs ({100 * counts['status:done'] // total}%)**", "",
             "| State | Meetings |", "|---|---|"]
    lines[6] = "| State | Jobs |"
    lines += [f"| `{s}` | {counts[s]} |" for s in STATUSES]
    lines += ["", "## Claimed now", ""]
    lines += [f"- #{i['number']} {i['title']}: @{i['assignees'][0]['login'] if i['assignees'] else '?'}" for i in active] or ["- none"]
    lines += ["", "To help, read [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md)."]
    board = ghj("issue", "list", "-R", REPO, "--label", "board", "--state", "open", "--json", "number") or []
    if board:
        gh("issue", "edit", str(board[0]["number"]), "-R", REPO, "--body", "\n".join(lines))


if __name__ == "__main__":
    {"comment": handle_comment, "pr": handle_pr, "sweep": sweep}[sys.argv[1]]()
