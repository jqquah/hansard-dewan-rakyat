# Instructions for AI agents

You are helping a volunteer. Your only task is to run the commands below and report the result.

## Rules

- Do not edit, create or delete any file. Do not read the files in `data/`.
- Do not write comments on GitHub yourself. The script does that.
- Run only the commands in this file.
- If a command fails, show the error to the volunteer and stop. Do not try to fix the script.
- Do not change git settings or GitHub settings.

## Step 1: Check the tools

Run these. Each one must print a version or "Logged in".

```bash
python3 --version
git --version
gh auth status
```

On Windows, use `python` instead of `python3`.
If `gh auth status` says that the volunteer is not logged in, ask the volunteer to run
`gh auth login` themselves, then continue.

## Step 2: Get the repository

If the folder `hansard-dewan-rakyat` does not exist in the current folder, run:

```bash
gh repo fork jqquah/hansard-dewan-rakyat --clone
```

Then go into the folder:

```bash
cd hansard-dewan-rakyat
```

## Step 3: Install (only if the folder `.venv` does not exist)

macOS or Linux:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Windows:

```text
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Step 4: Do the jobs

Use the number of jobs that the volunteer asked for. If they did not say, use 3.

macOS or Linux:

```bash
.venv/bin/python hansard.py work --jobs 3
```

Windows:

```text
.venv\Scripts\python hansard.py work --jobs 3
```

This command can run for 5 to 30 minutes. Let it finish. Do not stop it because it is quiet:
it waits 2 seconds between downloads, and up to 2 minutes for the claim bot.

## Step 5: Report

Tell the volunteer:

- the lines that start with `Job #`, `Verify PR #`, `opened`, `verified` or `FAIL`
- the last line of the output

If the output says `No free jobs now`, tell the volunteer that all jobs are taken, and to try again later.
