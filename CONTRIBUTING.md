# How to help

This project converts the Dewan Rakyat Hansard PDFs into text that is easy to search.
A Python script does all the work. **You do not need an LLM, and the script uses no LLM tokens.**
You give your computer time and internet: the script downloads the PDFs from parlimen.gov.my,
converts them, and sends the result to this repository.

Each job is one parliamentary meeting (about 15 to 35 sittings). One job takes about 2 to 10 minutes.

## What you need (one time only)

1. A GitHub account.
2. Python 3.9 or newer: https://www.python.org/downloads/
3. Git: https://git-scm.com/downloads
4. GitHub CLI: https://cli.github.com
5. Log in to GitHub CLI. Run this, then follow the steps on the screen:

```bash
gh auth login
```

## Option A: paste this into your AI agent

If you use an AI agent that can run terminal commands (for example Claude Code, Codex CLI,
Gemini CLI, Cursor, Copilot agent, Aider, or similar), open it in an empty folder and paste this:

```text
Help the Hansard Dewan Rakyat text project. Read the file AGENTS.md in
https://github.com/jqquah/hansard-dewan-rakyat and follow it exactly.
Do 3 jobs. Do not edit any files. Only run the commands that AGENTS.md gives.
At the end, tell me which jobs you did.
```

The agent only runs commands. It does not read or write the Hansard text, so it uses very few tokens.

## Option B: run it yourself

macOS or Linux:

```bash
gh repo fork jqquah/hansard-dewan-rakyat --clone
```

```bash
cd hansard-dewan-rakyat && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python hansard.py work --jobs 3
```

Windows (PowerShell):

```text
gh repo fork jqquah/hansard-dewan-rakyat --clone
cd hansard-dewan-rakyat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python hansard.py work --jobs 3
```

**Next time**, go into the same folder and run only the last command.

## What the script does

`hansard.py work` does these steps for each job:

1. It continues your own unfinished job first, if you have one.
2. If another volunteer's job needs verification, it takes that. It converts the same PDFs
   again on your computer and compares the result byte for byte.
3. Otherwise, it takes the oldest free job, converts every sitting in it, and opens a pull request.

It shows each step on the screen. You can stop it at any time with Ctrl+C.
If you stop it, run it again later and it continues from where it stopped.

## How the job status works

Each meeting has one GitHub Issue. The label shows its status.
See the [Status board](../../issues?q=is%3Aissue+is%3Aopen+label%3Aboard) for the totals.

| Label | Meaning |
|---|---|
| `status:todo` | Free to take |
| `status:claimed` | A volunteer is converting it (see the assignee) |
| `status:needs-verify` | A pull request is open; it needs a second volunteer |
| `status:verifying` | A second volunteer is converting it again to compare |
| `status:changes-needed` | The check failed; the first volunteer's script will do it again |
| `status:blocked` | The script failed; a maintainer must look |
| `status:done` | Verified and merged |

The script changes the status for you. It writes commands such as `/claim` as comments, and a bot
does the change. You can also write these comments yourself:

| Comment | Where | Effect |
|---|---|---|
| `/claim` | Issue | Take a free job |
| `/release` | Issue | Give back your job |
| `/blocked` | Issue | Tell maintainers that the job fails |
| `/verify` | Pull request | Take a pull request to verify |

Rules that the bot applies:

- One volunteer can have a maximum of 3 claimed jobs.
- A claim ends after 24 hours if there is no pull request. The job is then free again.
- A verification ends after 6 hours with no result.
- You cannot verify your own pull request.
- A pull request is merged only when a second volunteer gets exactly the same files.

## Why this is safe to trust

- The script makes no decisions about the words. It only removes page headers and page numbers,
  joins lines into paragraphs, and marks where each speaker starts.
- During every conversion, the script proves that the text has every character of the PDF text,
  in the same order. If not, it stops.
- Each file records the SHA-256 of the source PDF and of its own text. Hand edits fail the check.
- A second volunteer must get the same bytes from the same PDF before a merge.

## Privacy

Your commits use your GitHub no-reply e-mail address (`USERNAME@users.noreply.github.com`).
The script does not send any other information about you.

## Bugs in the conversion

If you see text in the wrong place (for example, a speaker name that is cut), open an Issue with
the file name and the line. Maintainers fix the script, add a test in `tests/`, and convert the
affected sittings again. Do not edit the files in `data/` by hand.
