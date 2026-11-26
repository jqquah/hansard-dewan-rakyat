# Hansard Dewan Rakyat as searchable text

The official record (Hansard) of the Dewan Rakyat, Parliament of Malaysia, from 1959 to now,
converted from PDF to Markdown text. You can search it on GitHub, read it in a browser, or download it.

**Source:** [parlimen.gov.my](https://www.parlimen.gov.my/hansard-dewan-rakyat.html?uweb=dr).
The PDF on parlimen.gov.my is the authoritative record. This text is a copy for search.
Each file links to its source PDF and records the PDF's SHA-256.

## Search

- On GitHub: use the search box at the top of this repository, for example
  [`subsidi diesel`](https://github.com/search?q=repo%3Ajqquah%2Fhansard-dewan-rakyat+%22subsidi+diesel%22&type=code).
- On your computer: `git clone` this repository, then use `grep -r "your words" data/`.

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

## Licence

The code is MIT licensed. The Hansard text is a public record of the Parliament of Malaysia;
this project claims no rights in it.
