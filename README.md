# Hansard Dewan Rakyat as searchable text

[![tests](https://github.com/jqquah/hansard-dewan-rakyat/actions/workflows/tests.yml/badge.svg)](https://github.com/jqquah/hansard-dewan-rakyat/actions/workflows/tests.yml)
[![Status board](https://img.shields.io/badge/progress-status%20board-blue)](https://github.com/jqquah/hansard-dewan-rakyat/issues?q=is%3Aissue+is%3Aopen+label%3Aboard)
[![Download](https://img.shields.io/badge/download-latest%20data-green)](https://github.com/jqquah/hansard-dewan-rakyat/releases/tag/data-latest)

The official record (Hansard) of the Dewan Rakyat, Parliament of Malaysia, from 1959 to now,
converted from PDF to Markdown text. You can search it on GitHub, read it in a browser, or download it.

**Source:** [parlimen.gov.my](https://www.parlimen.gov.my/hansard-dewan-rakyat.html?uweb=dr).
The PDF on parlimen.gov.my is the authoritative record. This text is a copy for search.
Each file links to its source PDF and records the PDF's SHA-256.

## Read, search and download

- **Read:** open the `data/` folder and choose a year and a date. You do not need an account.
- **Search on GitHub:** use the search box at the top of this page, for example
  [`subsidi diesel`](https://github.com/search?q=repo%3Ajqquah%2Fhansard-dewan-rakyat+%22subsidi+diesel%22&type=code).
  GitHub needs a free account for search.
- **Download everything:** the [latest data release](https://github.com/jqquah/hansard-dewan-rakyat/releases/tag/data-latest)
  has a ZIP of all files, and a JSONL file with one record per speech
  (date, speaker, page, heading, source link, text) for spreadsheets, databases and research.
  It updates every day.
- **On your computer:** `git clone https://github.com/jqquah/hansard-dewan-rakyat`, then `grep -r "your words" data/`.

Text only appears here after a second volunteer has verified it. Until then it is in the open
[pull requests](https://github.com/jqquah/hansard-dewan-rakyat/pulls).

## Files

```
data/2026/2026-11-25.md          one sitting
data/2026/2026-11-25.part2.md    long sittings have more parts (GitHub only searches files under 350 KB)
manifest/sittings.csv            every sitting: date, meeting, PDF link
```

Each file starts with data about the sitting (date, Parliament, term, meeting, source PDF, SHA-256).
In the text:

- `**Tuan Cha Kee Chin [Rasah]:**` marks the start of a speech.
- `### PERTANYAAN-PERTANYAAN BAGI JAWAB LISAN` is a heading from the PDF.
- `[p.12]` marks the start of PDF page 12, so you can cite the page.

The words are not changed. They are not translated or corrected, and old spellings stay as they are.
Old sittings (before about 1990) come from scanned pages, so they can have OCR errors from the original PDF.

## Help with the conversion

There are 4,121 sittings in 281 jobs. Volunteers do the conversion on their own computers,
because parlimen.gov.my does not accept connections from GitHub's servers (tested 26 Nov 2026).
It takes one command, and it needs no AI. See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

Progress: see the [Status board](../../issues?q=is%3Aissue+is%3Aopen+label%3Aboard).

## How it works

`hansard.py` is one Python file. It:

1. reads the list of sittings from the parlimen.gov.my archive (`crawl`),
2. downloads a PDF and reads its text with PyMuPDF,
3. removes page headers, footers and page numbers,
4. joins lines into paragraphs and marks headings and speakers,
5. proves that the output has every character of the PDF text, in the same order,
6. writes the Markdown files.

The conversion is deterministic: the same PDF always gives the same bytes. A second volunteer
converts each meeting again, and the bot merges only when both results are the same.

Run the tests with `python -m unittest discover tests`.

## Project files

| File | For |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | volunteers: how to help |
| [AGENTS.md](AGENTS.md) | AI agents that help a volunteer |
| [MAINTAINING.md](MAINTAINING.md) | maintainers |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | everyone |
| [SECURITY.md](SECURITY.md) | reporting a security problem |
| [CITATION.cff](CITATION.cff) | citing this dataset |

## Licence

- **Code** (`hansard.py`, `tools/`, `tests/`): [MIT](LICENSE).
- **What this project adds to the text** (the markers, metadata and file structure): [CC0](https://creativecommons.org/publicdomain/zero/1.0/), no rights reserved.
- **The Hansard text itself** is the official record of the Parliament of Malaysia. This project claims no rights in it.
  Any rights stay with their owner. If you publish it, cite the official Hansard and link to the source PDF in each file.
