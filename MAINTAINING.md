# Maintaining

For people with write access. Volunteers do not need this file.

GitHub's servers cannot reach parlimen.gov.my, so tasks that download from it run on a maintainer's computer.

## Add new sittings (each month, or after each meeting)

```bash
python hansard.py crawl
python -m unittest discover tests
git add manifest/sittings.csv && git commit -m "manifest: new sittings" && git push
python hansard.py seed
```

`crawl` keeps the ids of all known sittings. New sittings go into new jobs (for example `p15-s5-m3-j3`),
so finished jobs never change. `seed` creates Issues only for jobs that do not have one.

## A job is `status:blocked`

1. Read the error in the Issue or the pull request.
2. If the script failed on a PDF, reproduce it: `python hansard.py convert <sitting_id>`.
3. Fix `hansard.py`. Add a test with the real lines in `tests/test_segment.py`.
4. If the output changes, follow "Change the converter" below.
5. Run `python hansard.py reopen <job_id> --reason "fixed in <commit>"`.

If two volunteers got different bytes (`/reject`), compare their `converter` lines first.
A different pymupdf version is the usual cause.

## Change the converter

Any change that changes the output bytes must:

1. raise `VERSION` in `hansard.py` (1.1.0 to 1.2.0),
2. update the hashes in `tests/test_same_bytes.py` (the test prints the new ones),
3. pass CI on Linux, Windows and macOS,
4. reopen the jobs that must be converted again:
   `python hansard.py reopen --all --reason "converter 1.2.0"`.

`check` rejects files from another `VERSION`, so old pull requests cannot be merged by mistake.

Do the same when you update pymupdf in `requirements.txt`. Dependabot does not update it on purpose.

## A PDF on parlimen.gov.my changed

Parliament sometimes replaces a PDF (for example "pembetulan" files). The old file keeps its
`source_sha256`. Reopen its job to convert the new PDF.

## Code pull requests

Code pull requests (not conversions) get the tests in `tests.yml` and need a maintainer review
(see `.github/CODEOWNERS`). They must not change `data/`.

## The bot

| Workflow | When | What |
|---|---|---|
| `claim-bot` | a comment that starts with `/` | `/claim`, `/release`, `/blocked`, `/verify`, `/verified`, `/reject` |
| `pr-check` | a pull request opens or changes | checks conversion PRs with the code on `main`; never runs PR code |
| `sweep` | every hour | ends old claims, updates the Status board |
| `release-data` | every day | builds the download files on the `data-latest` release |
| `tests` | code changes | 26+ tests on 3 systems and 2 Python versions |
