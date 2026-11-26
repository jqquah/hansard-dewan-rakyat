#!/usr/bin/env python3
"""Hansard Dewan Rakyat: PDF to searchable Markdown.

One file, no LLM. Commands:

  python hansard.py doctor              check that this computer is ready
  python hansard.py work [--jobs N]     volunteer loop: claim, convert, open PR, verify
  python hansard.py convert SITTING_ID  convert one sitting (for testing)
  python hansard.py check [PATH ...]    validate output files (CI uses this)
  python hansard.py export OUTDIR       build the download files (ZIP and speeches JSONL)
  python hansard.py crawl               maintainers: rebuild manifest/sittings.csv
  python hansard.py survey              maintainers: test-convert samples from every Parliament
  python hansard.py seed                maintainers: create labels and one Issue per meeting
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = "1.1.0"
REPO = os.environ.get("HANSARD_REPO", "jqquah/hansard-dewan-rakyat")
ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest" / "sittings.csv"
DATA = ROOT / "data"
CACHE = ROOT / ".cache"
SITE = "https://www.parlimen.gov.my"
TREE = SITE + "/hansard-dewan-rakyat.html?uweb=dr&arkib=yes&ajx={ajx}"
UA = f"hansard-dewan-rakyat-text/{VERSION} (+https://github.com/{REPO})"
DELAY = 3.0          # seconds between requests to parlimen.gov.my (be polite: many volunteers share it)
MIN_CHARS_PER_PAGE = 300  # less than this means the PDF has no usable text layer (scan without OCR)
MAX_FILE = 300_000   # bytes; GitHub code search skips files over ~350 KB
CLAIM_WAIT = 120     # seconds to wait for the claim bot

JOB_SIZE = 20       # sittings per job (old scanned PDFs are up to 25 MB each)

MANIFEST_FIELDS = ["sitting_id", "date", "job_id", "meeting_id", "parlimen", "penggal",
                   "mesyuarat", "meeting_title", "pdf_path"]

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def say(msg: str):
    print(msg, flush=True)


_last_request = 0.0
_ctx = None


def ssl_context():
    """parlimen.gov.my does not send its intermediate certificate.
    We add that public certificate (certs/) to the normal trust store, so checks stay on."""
    global _ctx
    if _ctx is None:
        import ssl
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _ctx = ssl.create_default_context()
        _ctx.load_verify_locations(cafile=str(ROOT / "certs" / "sectigo-dv-r36.pem"))
    return _ctx


def fetch(url: str, retries: int = 4) -> bytes:
    """Polite GET with retries. Sleeps DELAY seconds between calls."""
    global _last_request
    for attempt in range(retries):
        wait = DELAY - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180, context=ssl_context()) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            say(f"  retry {attempt + 1} for {url}: {e}")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("unreachable")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run(cmd: list[str], check: bool = True, capture: bool = True) -> str:
    p = subprocess.run(cmd, cwd=ROOT, text=True,
                       capture_output=capture)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{p.stderr or ''}{p.stdout or ''}")
    return (p.stdout or "").strip()


def gh(*args: str, check: bool = True) -> str:
    return run(["gh", *args], check=check)


def gh_json(*args: str):
    out = gh(*args)
    return json.loads(out) if out else None


def read_manifest() -> list[dict]:
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pdf_url(pdf_path: str) -> str:
    return SITE + urllib.parse.quote(pdf_path)

# --------------------------------------------------------------------------
# crawl: walk the archive tree (Parlimen > Penggal > Mesyuarat > sitting)
# --------------------------------------------------------------------------

ORD = {"pertama": 1, "kedua": 2, "ketiga": 3, "keempat": 4, "kelima": 5,
       "keenam": 6, "ketujuh": 7, "kelapan": 8, "kesembilan": 9}


def tree_children(node_id: str | None) -> list[tuple[str, str, str]]:
    url = TREE.format(ajx=0) if node_id is None else TREE.format(ajx=1) + "&id=" + node_id
    raw = fetch(url)
    root = ET.fromstring(raw)
    out = []
    for item in root.findall("item"):
        ud = item.find("userdata")
        out.append((item.get("id"), item.get("text") or "", (ud.text or "") if ud is not None else ""))
    return out


ORD_WORDS = {"pertama": 1, "kedua": 2, "ketiga": 3, "keempat": 4, "kelima": 5, "keenam": 6,
             "ketujuh": 7, "kelapan": 8, "kesembilan": 9, "kesepuluh": 10, "kesebelas": 11}
UNITS = {"dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "lapan": 8, "sembilan": 9}


def parse_ordinal(text: str) -> int:
    t = text.lower().strip()
    m = re.match(r"ke(\w+) belas", t)          # Kelima Belas = 15
    if m and m.group(1) in UNITS:
        return 10 + UNITS[m.group(1)]
    return ORD_WORDS[t.split()[0]]


def current_parlimen() -> int:
    return 15


def current_meeting_rows(known: set) -> list[dict]:
    html = fetch(SITE + "/hansard-dewan-rakyat.html?uweb=dr").decode("utf-8", "replace")
    m = re.search(r"Mesyuarat (\w+), Penggal (\w+) Parlimen ([\w ]+?) \((\d{4})\)", html)
    if not m:
        say("  WARNING: could not read the current meeting on the main page")
        return []
    mm, ss, pp = parse_ordinal(m.group(1)), parse_ordinal(m.group(2)), parse_ordinal(m.group(3))
    title = f"Mesyuarat {m.group(1)}, Penggal {m.group(2)}, Parlimen {m.group(3)} ({m.group(4)})"
    rows = []
    for path in dict.fromkeys(re.findall(r"loadResult\('(/files/hindex/pdf/[^']+)'", html)):
        if path in known:
            continue
        rows.append({"date": date_from_pdf(path) or "", "meeting_id": f"p{pp:02d}-s{ss}-m{mm}",
                     "parlimen": pp, "penggal": ss, "mesyuarat": mm,
                     "meeting_title": title, "pdf_path": path})
    say(f"  current meeting p{pp:02d}-s{ss}-m{mm}: {len(rows)} sittings")
    return rows


def date_from_pdf(pdf_path: str) -> str | None:
    m = re.search(r"(?<!\d)(\d{2})[ ._-]?(\d{2})[ ._-]?((?:19|20)\d{2})(?!\d)", Path(pdf_path).name)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def assign_ids(rows: list[dict], old: dict | None = None) -> None:
    """sitting_id = date (plus a suffix when two PDFs share a date); job_id = meeting + chunk.
    Sittings already in the manifest keep their ids, so finished jobs never change.
    New sittings go into new jobs."""
    old = old or {}
    known = [r for r in rows if r["pdf_path"] in old]
    new = [r for r in rows if r["pdf_path"] not in old]
    for r in known:
        r["sitting_id"], r["job_id"], r["date"] = (old[r["pdf_path"]][k] for k in ("sitting_id", "job_id", "date"))
    if known:
        taken = {r["sitting_id"] for r in known}
        _assign_new(new, taken, {r["job_id"] for r in known})
        rows.sort(key=lambda r: (r["date"], r["sitting_id"]))
        return
    _assign_new(rows, set(), set())


def _assign_new(rows: list[dict], taken_ids: set, taken_jobs: set) -> None:
    for r in rows:
        r["date"] = date_from_pdf(r["pdf_path"]) or r.get("date") or ""
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"] or "nodate", []).append(r)
    for date, group in by_date.items():
        group.sort(key=lambda r: r["pdf_path"])
        for i, r in enumerate(group):
            if len(group) == 1:
                r["sitting_id"] = date
            else:
                stem = Path(r["pdf_path"]).stem.lower()
                suffix = re.sub(r"[^a-z0-9]+", "-", stem)
                suffix = re.sub(r"^dr-?", "", suffix)
                suffix = re.sub(r"\d{2}-?\d{2}-?\d{4}", "", suffix).strip("-")
                r["sitting_id"] = f"{date}-{suffix or i + 1}"
    for r in rows:
        if r["sitting_id"] in taken_ids:   # same date as a sitting that is already known
            r["sitting_id"] = f"{r['sitting_id']}-{re.sub(r'[^a-z0-9]+', '-', Path(r['pdf_path']).stem.lower()).strip('-')}"
    ids = [r["sitting_id"] for r in rows]
    for sid in {x for x in ids if ids.count(x) > 1}:
        for i, r in enumerate(x for x in rows if x["sitting_id"] == sid):
            r["sitting_id"] = f"{sid}-{i + 1}"
    rows.sort(key=lambda r: (r["date"], r["sitting_id"]))
    by_meeting: dict[str, list[dict]] = {}
    for r in rows:
        by_meeting.setdefault(r["meeting_id"], []).append(r)
    for mid, group in by_meeting.items():
        n = -(-len(group) // JOB_SIZE)
        if not taken_jobs:
            for i, r in enumerate(group):
                r["job_id"] = mid if n == 1 else f"{mid}-j{i * n // len(group) + 1}"
            continue
        # new sittings in a meeting that already has jobs: start new job numbers after the last one
        used = [int(m.group(1)) for j in taken_jobs if j.startswith(mid)
                for m in [re.fullmatch(re.escape(mid) + r"(?:-j(\d+))?", j)] if m and m.group(1)]
        used += [1] if mid in taken_jobs else []
        start = max(used, default=0) + 1
        for i, r in enumerate(group):
            k = start + i * n // len(group)
            r["job_id"] = mid if (start == 1 and n == 1) else f"{mid}-j{k}"


def cmd_crawl(args):
    rows = []
    for pid, ptext, _ in tree_children(None):
        if args.parlimen and pid != f"0_{args.parlimen}":
            continue
        say(f"{ptext}")
        for sid, stext, _ in tree_children(pid):
            for mid, mtext, _ in tree_children(sid):
                parts = mid.split("_")  # 0_P_S_M
                p, s, m = parts[1], parts[2], parts[3]
                meeting_id = f"p{int(p):02d}-s{s}-m{m}"
                title = f"{mtext}, {stext}, {ptext}"
                for _, dtext, url in tree_children(mid):
                    mm = re.search(r"loadResult\('([^']+)'", url)
                    if not mm:
                        continue
                    path = mm.group(1)
                    rows.append({"date": date_from_pdf(path) or "", "meeting_id": meeting_id,
                                 "parlimen": p, "penggal": s, "mesyuarat": m,
                                 "meeting_title": title, "pdf_path": path, "label": dtext})
                say(f"  {meeting_id}: {sum(1 for r in rows if r['meeting_id'] == meeting_id)} sittings")
    # the current meeting is only on the main page, not in the archive tree
    if not args.parlimen or args.parlimen == current_parlimen():
        rows += current_meeting_rows({r["pdf_path"] for r in rows})
    old = {r["pdf_path"]: r for r in read_manifest()} if MANIFEST.exists() else {}
    assign_ids(rows, old)
    MANIFEST.parent.mkdir(exist_ok=True)
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    say(f"wrote {len(rows)} sittings to {MANIFEST.relative_to(ROOT)}")

# --------------------------------------------------------------------------
# convert: PDF -> Markdown (deterministic)
# --------------------------------------------------------------------------

MONTHS = r"(JAN|FEB|MAR|APR|MAY|MEI|JUN|JUL|AUG|OGO|SEP|OCT|OKT|NOV|DEC|DIS)[A-Z]*"
FURNITURE = [
    re.compile(r"^DR\.?\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\d{2,4}$", re.I),   # DR. 25.11.2026
    re.compile(r"^\d{1,4}$"),                                                # page number
    re.compile(r"^[ivxlcdm]{1,8}$", re.I),                                   # roman page number
    re.compile(r"^\d{1,2}\s+" + MONTHS + r",?\s+\d{4}$", re.I),              # 20 MAY 1964
    re.compile(r"^\d{1,4}\s+\d{1,2}\s+" + MONTHS + r",?\s+\d{4}(\s+\d{1,4})?$", re.I),
]
CHAIR = (r"(?:Tuan|Timbalan|Puan)\s+(?:Yang\s+di-?Pertua|Speaker|Pengerusi)|Mr\.?\s+(?:Deputy\s+)?Speaker|"
         r"Mr\.?\s+(?:Deputy\s+)?Chairman|Yang\s+di-?Pertua|Beberapa\s+Ahli|Seorang\s+Ahli|"
         r"Ahli-ahli|Pengerusi|Tuan\s+Pengerusi|Timbalan\s+Pengerusi")
# Name [Seat or office]:   (1990s onward)
RE_SQ = re.compile(r"^(?P<label>(?P<name>[A-Z][^\[\]:\n]{1,140}?)\s*\[[^\[\]\n]{2,160}\])\s*:")
# Name (Seat):            (1959 onward)
RE_RD = re.compile(r"^(?P<label>(?P<name>[A-Z][^()\[\]:\n]{1,100}?)\s*\([^()\n]{2,80}\))\s*:")
# Chair or crowd without a bracket
RE_CH = re.compile(r"^(?P<label>(?P<name>" + CHAIR + r"))\s*:", re.I)


def is_furniture(line: str) -> bool:
    s = line.strip()
    return any(p.match(s) for p in FURNITURE)


def extract_pages(pdf_bytes: bytes) -> list[list[str]]:
    import pymupdf  # imported here so 'check' works without it
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text("text")
        pages.append([ln.rstrip() for ln in text.splitlines()])
    return pages


def strip_furniture(pages: list[list[str]]) -> list[list[str]]:
    """Remove page headers and footers: furniture lines in the first 4 or last 3 non-empty lines."""
    out = []
    for lines in pages:
        idx = [i for i, ln in enumerate(lines) if ln.strip()]
        edge = set(idx[:4] + idx[-3:])
        out.append([ln for i, ln in enumerate(lines)
                    if ln.strip() and not (i in edge and is_furniture(ln))])
    return out


def speaker_at(text: str):
    if len(text) < 4 or not text[0].isupper():
        return None
    for rx in (RE_SQ, RE_RD, RE_CH):
        m = rx.match(text)
        if m:
            name = m.group("name").strip()
            if len(name.split()) > 16 or re.search(r"[.?!;,]$", name):
                continue
            return m.group("label")
    return None


ABBREV = re.compile(r"(?:\b[A-Z]|Dr|Mohd|Muhd|Abd|Md|Hj|Sdn|Bhd|Ir|Ts|St|Jr|Sr|Kol|Lt|Kapt|Prof|Mr|Mrs|Dato|Tg|No)\.$")


HONORIFIC = re.compile(r"(Tuan|Puan|Cik|Dato|Datuk|Datin|Dr|Tan Sri|Tun|Tunku|Tengku|Raja|Wan|Haji|Hajah|"
                       r"Ustaz|Prof|Ir|Kapten|Komander|Kolonel|Mejar|Leftenan|Senator|Yang|Timbalan|Menteri|"
                       r"Perdana|Setiausaha|Enche|Inche|Mr|Mrs|Miss|The|Penghulu|Pengiran|Sri|Seri)\b")


def ends_sentence(line: str) -> bool:
    s = line.strip()
    return bool(re.search(r"[.?!;,…]$", s)) and not ABBREV.search(s)


def is_heading(line: str) -> bool:
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    return (3 <= len(letters) and len(s) <= 90 and not any(c.islower() for c in s)
            and not re.search(r"[.,;?!]$", s) and speaker_at(s) is None)  # "PDRM." ends a sentence


def segment(pages: list[list[str]]):
    """Yield blocks: ('page', n) | ('heading', text) | ('speech', label, lines) | ('text', lines)."""
    blocks: list = []
    cur = None  # current open block (speech or text)

    def close():
        nonlocal cur
        if cur is not None:
            blocks.append(cur)
            cur = None

    for pno, lines in enumerate(pages, start=1):
        if cur is not None:
            cur[-1].append(("page", pno))
        else:
            blocks.append(("page", pno))
        i = 0
        while i < len(lines):
            ln = lines[i].strip()
            # A speaker label can wrap over many lines (narrow or justified columns):
            # "Enche' Mohamed Yusof bin Mah-" / "mud (Temerloh): Tuan Yang di-Pertua,"
            # Only try this at a paragraph start, so normal sentences do not match.
            prev = lines[i - 1].strip() if i > 0 else ""
            at_start = (i == 0 or is_heading(prev) or re.search(r"[.?!:;…\])\"'’”]$", prev) is not None)
            joined, used = ln, 1
            if at_start and ln[:1].isupper() and speaker_at(ln) is None:
                for k in range(2, 16):
                    if i + k > len(lines):
                        break
                    head = [x.strip() for x in lines[i:i + k - 1]]
                    if any(is_heading(x) or ends_sentence(x) for x in head):
                        break
                    cand = " ".join(x.strip() for x in lines[i:i + k])
                    if len(cand) > 220:
                        break
                    lab = speaker_at(cand)
                    if lab is not None and len(ln.split()) >= 3 and not HONORIFIC.match(ln) \
                            and ln.count("(") == ln.count(")") and ln.count("[") == ln.count("]") \
                            and not re.search(r"(\b(and|dan|of|bagi|untuk|serta)|[,&-])$", ln) \
                            and speaker_at(" ".join(x.strip() for x in lines[i + 1:i + k])) is not None:
                        break  # line i is a sub-heading; the label starts on the next line
                    if lab is not None and len(lab) > len(" ".join(x.strip() for x in lines[i:i + k - 1])):
                        joined, used = cand, k
                        break
            label = speaker_at(joined)
            if label is not None:
                close()
                rest = joined[len(label):].lstrip()
                assert rest.startswith(":")
                cur = ("speech", label, [])
                body = rest[1:].strip()
                if body:
                    cur[2].append(("line", body))
                i += used
                continue
            if is_heading(ln):
                close()
                blocks.append(("heading", ln))
                i += 1
                continue
            if cur is None:
                cur = ("text", None, [])
            cur[2].append(("line", ln))
            i += 1
    close()
    return blocks


def reflow(items: list) -> list[str]:
    """Join PDF lines into paragraphs. Keeps every character; only whitespace changes."""
    lines = [x[1] for x in items if x[0] == "line"]
    lens = sorted(len(x) for x in lines) or [80]
    full = lens[int(len(lens) * 0.8)] if lens else 80
    paras: list[str] = []
    buf = ""
    for kind, val in items:
        if kind == "page":
            buf = (buf + " " if buf else "") + f"[p.{val}]"
            continue
        line = val
        if buf and re.match(r"^(\d{1,3}\.|[▪•●\-]|\([a-z0-9]{1,3}\))\s", line):
            paras.append(buf)      # numbered or bulleted list item starts a paragraph
            buf = ""
        if not buf:
            buf = line
        elif buf.endswith("-") and not buf.endswith(" -") and line[:1].islower():
            buf += line            # split word: keep the hyphen, no space
        else:
            buf += " " + line
        ends = re.search(r"[.?!:\]\"'’”)]$", line)
        if ends and len(line) < 0.85 * full:
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)
    return paras


def render(blocks) -> list[str]:
    """Return Markdown body parts, one per block, so files can split between blocks."""
    parts = []
    for b in blocks:
        if b[0] == "page":
            parts.append(f"[p.{b[1]}]\n")
        elif b[0] == "heading":
            parts.append(f"### {b[1]}\n")
        else:
            paras = reflow(b[2])
            if b[0] == "speech":
                first = f"**{b[1]}:**" + (" " + paras[0] if paras else "")
                paras = [first] + paras[1:]
            parts.append("\n\n".join(paras) + "\n")
    return parts


MARKUP = re.compile(r"\[p\.\d+\]|^### |\*\*", re.M)


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def fidelity(pages: list[list[str]], body: str) -> None:
    """Prove that the Markdown has every character of the PDF text, in order."""
    src = squash("".join("".join(p) for p in pages))
    out = squash(MARKUP.sub("", body))
    if src != out:
        n = next((i for i, (a, b) in enumerate(zip(src, out)) if a != b), min(len(src), len(out)))
        raise AssertionError(f"fidelity failed at char {n}: pdf={src[n-40:n+40]!r} md={out[n-40:n+40]!r}")


def front_matter(meta: dict) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)


def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("no front matter")
    end = text.index("\n---\n", 4)
    meta = {}
    for ln in text[4:end].splitlines():
        k, v = ln.split(": ", 1)
        meta[k] = json.loads(v)
    return meta, text[end + 5:]


def out_paths(row: dict, n: int) -> list[Path]:
    year = row["sitting_id"][:4] if row["sitting_id"][:4].isdigit() else "unknown"
    base = DATA / year / row["sitting_id"]
    return [base.with_suffix(".md") if i == 0 else Path(f"{base}.part{i + 1}.md") for i in range(n)]


def get_pdf(row: dict) -> bytes:
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / (row["sitting_id"] + ".pdf")
    if cached.exists():
        return cached.read_bytes()
    b = fetch(pdf_url(row["pdf_path"]))
    if not b.startswith(b"%PDF"):
        raise RuntimeError(f"not a PDF: {row['pdf_path']} (got {b[:60]!r})")
    cached.write_bytes(b)
    return b


def text_check(pages: list[list[str]]) -> None:
    """Stop when a PDF has (almost) no text. The fidelity proof cannot catch this:
    an empty file loses nothing, so it would pass."""
    chars = sum(len(squash("".join(p))) for p in pages)
    if not pages or chars / len(pages) < MIN_CHARS_PER_PAGE:
        raise ValueError(f"the PDF has almost no text ({chars} characters on {len(pages)} pages). "
                         "It is probably a scan without OCR. A maintainer must look at it.")


def convert_row(row: dict, out_root: Path | None = None) -> list[Path]:
    pdf = get_pdf(row)
    pages = strip_furniture(extract_pages(pdf))
    text_check(pages)
    blocks = segment(pages)
    parts = render(blocks)
    fidelity(pages, "\n".join(parts))
    speeches = sum(1 for b in blocks if b[0] == "speech")
    chars = sum(len(squash("".join(p))) for p in pages)
    # split into files under MAX_FILE at block boundaries
    chunks, cur, size = [], [], 0
    for p in parts:
        n = len(p.encode())
        if cur and size + n > MAX_FILE - 2000:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    chunks.append(cur)
    import pymupdf
    paths = out_paths(row, len(chunks))
    if out_root is not None:
        paths = [out_root / p.relative_to(ROOT) for p in paths]
    for i, (path, chunk) in enumerate(zip(paths, chunks)):
        body = "\n".join(chunk)
        meta = {
            "sitting_id": row["sitting_id"], "date": row["date"], "house": "Dewan Rakyat",
            "parlimen": int(row["parlimen"]), "penggal": int(row["penggal"]),
            "mesyuarat": int(row["mesyuarat"]), "meeting_id": row["meeting_id"],
            "part": i + 1, "parts": len(chunks),
            "source_url": pdf_url(row["pdf_path"]), "source_sha256": sha256(pdf),
            "pages": len(pages), "speeches": speeches, "chars": chars,
            "converter": f"hansard.py {VERSION}; pymupdf {pymupdf.__version__}",
            "body_sha256": sha256(body.encode()),
        }
        title = f"# Dewan Rakyat, {row['date']}" + (f" (part {i + 1} of {len(chunks)})" if len(chunks) > 1 else "")
        path.parent.mkdir(parents=True, exist_ok=True)
        # write bytes, so Windows does not change "\n" to "\r\n" (verification compares bytes)
        path.write_bytes((front_matter(meta) + title + "\n\n" + body).encode("utf-8"))
    # remove stale extra parts from an older run
    for stale in sorted(paths[0].parent.glob(row["sitting_id"] + ".part*.md")):
        if stale not in paths:
            stale.unlink()
    return paths


def cmd_convert(args):
    rows = {r["sitting_id"]: r for r in read_manifest()}
    for sid in args.sitting_id:
        if sid not in rows:
            die(f"unknown sitting {sid}; see manifest/sittings.csv")
        paths = convert_row(rows[sid])
        for p in paths:
            say(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size // 1024} KB)")

# --------------------------------------------------------------------------
# check: validate output files without the PDF (CI)
# --------------------------------------------------------------------------

REQUIRED = ["sitting_id", "date", "house", "parlimen", "penggal", "mesyuarat", "meeting_id",
            "part", "parts", "source_url", "source_sha256", "pages", "speeches", "chars",
            "converter", "body_sha256"]


def check_file(path: Path, manifest: dict) -> list[str]:
    errs = []
    raw = path.read_bytes()
    if len(raw) > MAX_FILE:
        errs.append(f"{path}: {len(raw)} bytes, max {MAX_FILE}")
    try:
        meta, rest = parse_front_matter(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"{path}: bad front matter: {e}"]
    for k in REQUIRED:
        if k not in meta:
            errs.append(f"{path}: missing field {k}")
    if errs:
        return errs
    row = manifest.get(meta["sitting_id"])
    if row is None:
        errs.append(f"{path}: sitting {meta['sitting_id']} not in manifest")
    else:
        if meta["source_url"] != pdf_url(row["pdf_path"]):
            errs.append(f"{path}: source_url does not match manifest")
        if meta["meeting_id"] != row["meeting_id"]:
            errs.append(f"{path}: meeting_id does not match manifest")
        expect = out_paths(row, meta["parts"])[meta["part"] - 1]
        if path.resolve() != expect.resolve() and path.name != expect.name:
            errs.append(f"{path}: wrong file name, expected {expect.relative_to(ROOT)}")
    if not meta["converter"].startswith(f"hansard.py {VERSION};"):
        errs.append(f"{path}: made by {meta['converter']}, current is {VERSION}; update and convert again")
    body = rest.split("\n\n", 1)[1] if "\n\n" in rest else ""
    if sha256(body.encode()) != meta["body_sha256"]:
        errs.append(f"{path}: body changed after conversion (hand edits are not allowed)")
    if not re.fullmatch(r"[0-9a-f]{64}", meta["source_sha256"]):
        errs.append(f"{path}: bad source_sha256")
    return errs


def cmd_check(args):
    manifest = {r["sitting_id"]: r for r in read_manifest()}
    files = []
    for p in args.paths or [str(DATA)]:
        pp = Path(p)
        files += sorted(pp.rglob("*.md")) if pp.is_dir() else [pp]
    errs = []
    for f in files:
        errs += check_file(f, manifest)
    for e in errs:
        print(e)
    say(f"checked {len(files)} files: {'PASS' if not errs else f'FAIL ({len(errs)} errors)'}")
    sys.exit(1 if errs else 0)

# --------------------------------------------------------------------------
# export: one ZIP of the Markdown, and one JSON line per speech
# --------------------------------------------------------------------------

LABEL_LINE = re.compile(r"^\*\*(?P<label>.+?):\*\*\s?(?P<rest>.*)$")
PAGE = re.compile(r"\[p\.(\d+)\]")


def iter_records(meta: dict, body: str, state: dict):
    """Yield one record per speech or text block. state carries page and heading across parts."""
    cur = None
    prev_heading = False
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("### "):
            # a heading can span several lines in the PDF; join lines that come one after another
            line = block[4:].strip()
            state["heading"] = f"{state['heading']} {line}" if prev_heading and state["heading"] else line
            prev_heading = True
            continue
        if not PAGE.fullmatch(block):
            prev_heading = False
        m = LABEL_LINE.match(block)
        if m or cur is None:
            if cur:
                yield cur
            label = m.group("label") if m else None
            cur = {"sitting_id": meta["sitting_id"], "date": meta["date"], "parlimen": meta["parlimen"],
                   "penggal": meta["penggal"], "mesyuarat": meta["mesyuarat"], "seq": state["seq"],
                   "speaker": label, "page": state["page"], "heading": state["heading"],
                   "source_url": meta["source_url"], "text": ""}
            state["seq"] += 1
            block = m.group("rest") if m else block
        pages = [int(x) for x in PAGE.findall(block)]
        text = PAGE.sub("", block).strip()
        if text:
            cur["text"] = (cur["text"] + "\n\n" + text).strip()
        if pages:
            state["page"] = pages[-1]
    if cur:
        yield cur


def cmd_export(args):
    import gzip
    import zipfile
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    data = Path(args.data)
    files = sorted(data.rglob("*.md"))
    by_sitting: dict[str, list[tuple[dict, str, Path]]] = {}
    for f in files:
        meta, rest = parse_front_matter(f.read_text(encoding="utf-8"))
        body = rest.split("\n\n", 1)[1] if "\n\n" in rest else ""
        by_sitting.setdefault(meta["sitting_id"], []).append((meta, body, f))
    n = 0
    with gzip.open(out / "hansard-dewan-rakyat-speeches.jsonl.gz", "wt", encoding="utf-8") as g, \
            zipfile.ZipFile(out / "hansard-dewan-rakyat-markdown.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for sid in sorted(by_sitting):
            parts = sorted(by_sitting[sid], key=lambda x: x[0]["part"])
            state = {"seq": 1, "page": 1, "heading": None}
            for meta, body, f in parts:
                z.write(f, f.relative_to(data.parent).as_posix())
                for rec in iter_records(meta, body, state):
                    if rec["speaker"] is None and not rec["text"]:
                        continue
                    g.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
        z.write(MANIFEST, "manifest/sittings.csv")
    say(f"exported {len(by_sitting)} sittings, {n} records to {out}")

# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def cmd_doctor(args):
    ok = True

    def item(good, text):
        nonlocal ok
        ok &= bool(good)
        say(("  OK   " if good else "  FAIL ") + text)

    say("Checking this computer:")
    item(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (need 3.10+)")
    try:
        import pymupdf
        item(True, f"pymupdf {pymupdf.__version__}")
    except ImportError:
        item(False, "pymupdf missing: run  pip install -r requirements.txt")
    item(shutil.which("git"), "git installed")
    item(shutil.which("gh"), "GitHub CLI (gh) installed: https://cli.github.com")
    if shutil.which("gh"):
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        item(r.returncode == 0, "gh is logged in (if not: gh auth login)")
    try:
        fetch(TREE.format(ajx=0), retries=1)
        item(True, "parlimen.gov.my is reachable")
    except Exception as e:  # noqa: BLE001
        item(False, f"parlimen.gov.my is not reachable: {e}")
    say("READY" if ok else "NOT READY: fix the FAIL lines above")
    return ok

# --------------------------------------------------------------------------
# work: the volunteer loop
# --------------------------------------------------------------------------

def me() -> str:
    return gh("api", "user", "--jq", ".login")


SAME_REPO = False  # True for maintainers who push branches to the main repository


def setup_git():
    global SAME_REPO
    remotes = run(["git", "remote"]).split()
    origin = run(["git", "remote", "get-url", "origin"])
    if REPO.lower() in origin.lower().removesuffix(".git"):
        perm = gh("api", f"repos/{REPO}", "--jq", ".permissions.push", check=False)
        if perm != "true":
            die("this folder is a copy of the main repository, not your fork. Run: "
                f"gh repo fork {REPO} --clone   then run this command in the new folder")
        SAME_REPO = True
        if "upstream" not in remotes:
            run(["git", "remote", "add", "upstream", origin])
    elif "upstream" not in remotes:
        run(["git", "remote", "add", "upstream", f"https://github.com/{REPO}.git"])
    run(["git", "fetch", "-q", "upstream"])


def job_of(text: str | None) -> str | None:
    m = re.search(r"job:\s*(p\d+-s\d+-m\d+(?:-j\d+)?)", text or "")
    return m.group(1) if m else None


def find_own_issue(user: str, handled: set):
    """My unfinished job. Skip jobs done in this run, and claimed jobs that already have my PR
    (the bot moves their label to status:needs-verify a short time after the PR opens)."""
    claimed = gh_json("issue", "list", "-R", REPO, "--assignee", user, "--state", "open",
                      "--label", "status:claimed", "--json", "number,title,body", "--limit", "10") or []
    redo = gh_json("issue", "list", "-R", REPO, "--assignee", user, "--state", "open",
                   "--label", "status:changes-needed", "--json", "number,title,body", "--limit", "10") or []
    if claimed:
        prs = gh_json("pr", "list", "-R", REPO, "--author", user, "--state", "open",
                      "--json", "body", "--limit", "100") or []
        with_pr = {int(m.group(1)) for p in prs
                   for m in [re.search(r"closes\s+#(\d+)", p.get("body") or "", re.I)] if m}
        claimed = [i for i in claimed if i["number"] not in with_pr]
    issues = [i for i in claimed + redo if i["number"] not in handled]
    return issues[0] if issues else None


def claim(kind: str, number: int, user: str, command: str) -> bool:
    gh(kind, "comment", str(number), "-R", REPO, "--body", command)
    say(f"  asked the bot for #{number}; waiting up to {CLAIM_WAIT}s")
    t0 = time.time()
    while time.time() - t0 < CLAIM_WAIT:
        time.sleep(15)
        d = gh_json(kind, "view", str(number), "-R", REPO, "--json", "assignees,labels")
        if any(a["login"].lower() == user.lower() for a in d["assignees"]):
            return True
        if d["assignees"]:
            return False
    return False


def do_convert_job(issue: dict, user: str) -> None:
    job = job_of(issue.get("body"))
    if not job:
        die(f"issue #{issue['number']} has no job id")
    rows = [r for r in read_manifest() if r["job_id"] == job]
    say(f"Job #{issue['number']}: {job}, {len(rows)} sittings")
    branch = f"job/{job}"
    run(["git", "checkout", "-q", "-B", branch, "upstream/main"])
    done, failed = [], []
    for r in rows:
        try:
            paths = convert_row(r)
            done += paths
            say(f"  OK   {r['sitting_id']} ({len(paths)} file{'s' if len(paths) > 1 else ''})")
        except Exception as e:  # noqa: BLE001
            failed.append((r["sitting_id"], str(e)[:300]))
            say(f"  FAIL {r['sitting_id']}: {str(e)[:200]}")
    if failed:
        body = "Blocked. These sittings failed:\n\n" + "\n".join(f"- `{s}`: {e}" for s, e in failed)
        gh("issue", "comment", str(issue["number"]), "-R", REPO, "--body", body + "\n\n/blocked")
        say("  reported as blocked; a maintainer will look at it")
        run(["git", "checkout", "-q", "-"], check=False)
        return
    manifest = {r["sitting_id"]: r for r in read_manifest()}
    errs = [e for p in done for e in check_file(p, manifest)]
    if errs:
        die("check failed after conversion:\n" + "\n".join(errs))
    run(["git", "add", *[p.relative_to(ROOT).as_posix() for p in done]])
    if not run(["git", "status", "--porcelain"]):
        say("  nothing changed")
        return
    run(["git", "-c", "user.name=" + user,
         "-c", f"user.email={user}@users.noreply.github.com",
         "commit", "-q", "-m", f"{job}: {len(rows)} sittings"])
    run(["git", "push", "-q", "-f", "origin", branch])
    existing = gh_json("pr", "list", "-R", REPO, "--head", branch, "--author", user,
                       "--state", "open", "--json", "number") or []
    body = (f"Closes #{issue['number']}\n\njob: {job}\nsittings: {len(rows)}\n"
            f"files: {len(done)}\nconverter: hansard.py {VERSION}\n")
    if existing:
        gh("pr", "edit", str(existing[0]["number"]), "-R", REPO, "--body", body)  # keep the version line true
        say(f"  updated PR #{existing[0]['number']}")
    else:
        url = gh("pr", "create", "-R", REPO, "--head", branch if SAME_REPO else f"{user}:{branch}", "--base", "main",
                 "--title", f"{job}: {len(rows)} sittings", "--body", body)
        say(f"  opened {url}")
    run(["git", "checkout", "-q", "upstream/main"], check=False)


def do_verify_job(pr: dict, user: str) -> None:
    """Convert again on this computer and compare byte for byte."""
    job = job_of(pr["body"])
    if not job:
        say(f"  PR #{pr['number']} has no job id; skip")
        return
    say(f"Verify PR #{pr['number']}: {job}")
    files = gh_json("pr", "view", str(pr["number"]), "-R", REPO, "--json", "files")["files"]
    head = gh_json("pr", "view", str(pr["number"]), "-R", REPO, "--json", "headRefOid")["headRefOid"]
    run(["git", "fetch", "-q", "upstream", f"pull/{pr['number']}/head"])
    rows = [r for r in read_manifest() if r["job_id"] == job]
    mine: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for r in rows:
            for p in convert_row(r, out_root=Path(tmp)):
                mine[p.relative_to(tmp).as_posix()] = sha256(p.read_bytes())
    theirs = {}
    for f in files:
        blob = subprocess.run(["git", "show", f"{head}:{f['path']}"], cwd=ROOT, capture_output=True)
        theirs[f["path"]] = sha256(blob.stdout) if blob.returncode == 0 else "missing"
    bad = sorted(k for k in set(mine) | set(theirs) if mine.get(k) != theirs.get(k))
    if bad:
        body = "/reject\n\nMy conversion does not match these files:\n\n" + "\n".join(f"- `{b}`" for b in bad[:50])
        say(f"  MISMATCH in {len(bad)} files; rejected")
    else:
        body = (f"/verified\n\nI converted all {len(rows)} sittings again on my computer. "
                f"All {len(mine)} files match byte for byte.\n\nhead: {head}")
        say(f"  all {len(mine)} files match; verified")
    gh("pr", "comment", str(pr["number"]), "-R", REPO, "--body", body)


def self_update() -> None:
    """Always run the newest code. A fork can be old, and old code makes files that the check rejects
    (26 Nov 2026: a volunteer's fork ran 1.0.0 after 1.1.0 was released)."""
    latest = subprocess.run(["git", "show", "upstream/main:hansard.py"], cwd=ROOT, capture_output=True).stdout
    mine = Path(__file__).read_bytes()
    if latest.replace(b"\r\n", b"\n") == mine.replace(b"\r\n", b"\n"):
        return
    if os.environ.get("HANSARD_UPDATED"):
        die("the update did not work; run: git checkout upstream/main")
    req_before = (ROOT / "requirements.txt").read_bytes()
    run(["git", "checkout", "-q", "upstream/main"])
    say("Updated to the newest version of hansard.py. Restarting.")
    if (ROOT / "requirements.txt").read_bytes() != req_before:
        run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], capture=False)
    os.environ["HANSARD_UPDATED"] = "1"
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())] + sys.argv[1:])


def cmd_work(args):
    if not cmd_doctor(args):
        die("this computer is not ready")
    user = me()
    setup_git()
    if run(["git", "status", "--porcelain", "--untracked-files=no"]):
        die("you have uncommitted changes in this folder; commit or remove them first")
    self_update()
    say(f"\nWorking as {user}. Jobs to do: {args.jobs}\n")
    handled: set = set()  # job Issues done in this run; never do one twice
    for n in range(args.jobs):
        run(["git", "checkout", "-q", "upstream/main"], check=False)
        # 1. own unfinished work first (continue after a crash)
        own = None if args.verify_only else find_own_issue(user, handled)
        if own:
            say(f"Continue my claimed job #{own['number']}")
            handled.add(own["number"])
            do_convert_job(own, user)
            continue
        # 2. verification (another person's PR)
        if not args.no_verify:
            prs = gh_json("pr", "list", "-R", REPO, "--state", "open", "--label", "status:needs-verify",
                          "--json", "number,author,body", "--limit", "30") or []
            prs = [p for p in prs if p["author"]["login"].lower() != user.lower()]
            took = False
            for pr in sorted(prs, key=lambda p: p["number"]):
                if claim("pr", pr["number"], user, "/verify"):
                    do_verify_job(pr, user)
                    took = True
                    break
            if took:
                continue
        if args.verify_only:
            say("No pull requests to verify now.")
            break
        # 3. a new conversion job
        todo = gh_json("issue", "list", "-R", REPO, "--state", "open", "--label", "status:todo",
                       "--json", "number,title,body", "--limit", "20",
                       "--search", "sort:created-asc no:assignee") or []
        took = False
        for issue in todo:
            if claim("issue", issue["number"], user, "/claim"):
                handled.add(issue["number"])
                do_convert_job(issue, user)
                took = True
                break
            say(f"  #{issue['number']} was taken by someone else; try the next one")
        if not took:
            say("No free jobs now. Thank you! Try again later.")
            break
    run(["git", "checkout", "-q", "upstream/main"], check=False)
    say("\nDone.")

def cmd_survey(args):
    """Maintainers: test-convert sample sittings from every Parliament. Writes nothing to data/.
    Reports text per page, speeches, unusual speaker labels, and errors."""
    rows = read_manifest()
    by_p: dict[int, list[dict]] = {}
    for r in rows:
        by_p.setdefault(int(r["parlimen"]), []).append(r)
    picks = []
    for p in sorted(by_p):
        if args.parlimen and p not in args.parlimen:
            continue
        group = by_p[p]
        n = min(args.per, len(group))
        picks += [group[(i * (len(group) - 1)) // max(n - 1, 1)] for i in range(n)]
    report = []
    say(f"Survey of {len(picks)} sittings. Downloads wait {DELAY}s each.\n")
    say(f"{'sitting':<24}{'pages':>6}{'chars/p':>8}{'empty':>6}{'speech':>7}{'odd':>5}  result")
    with tempfile.TemporaryDirectory() as tmp:
        for r in picks:
            rec = {"sitting_id": r["sitting_id"], "parlimen": int(r["parlimen"]), "pdf": pdf_url(r["pdf_path"])}
            try:
                pdf = get_pdf(r)
                rec["mb"] = round(len(pdf) / 1e6, 1)
                pages = strip_furniture(extract_pages(pdf))
                chars = [len(squash("".join(p))) for p in pages]
                blocks = segment(pages)
                labels = [b[1] for b in blocks if b[0] == "speech"]
                odd = sorted({x for x in labels if not HONORIFIC.match(x) and not re.match(
                    r"(Beberapa|Seorang|Ahli|Minister|Assistant|Deputy|Speaker|Menteri|Timbalan|Setiausaha|Mr)", x)})
                rec.update(pages=len(pages), chars_per_page=round(sum(chars) / max(len(pages), 1)),
                           empty_pages=sum(1 for c in chars if c < 50), speeches=len(labels),
                           speakers=len(set(labels)), odd_labels=odd[:20],
                           headings=sum(1 for b in blocks if b[0] == "heading"))
                files = convert_row(r, out_root=Path(tmp))
                rec["files"] = len(files)
                rec["result"] = "OK"
            except Exception as e:  # noqa: BLE001
                rec["result"] = f"FAIL: {str(e)[:300]}"
            report.append(rec)
            say(f"{rec['sitting_id']:<24}{rec.get('pages', '-'):>6}{rec.get('chars_per_page', '-'):>8}"
                f"{rec.get('empty_pages', '-'):>6}{rec.get('speeches', '-'):>7}{len(rec.get('odd_labels', [])):>5}  "
                f"{rec['result'][:70]}")
            if not args.keep_pdfs:
                (CACHE / (r["sitting_id"] + ".pdf")).unlink(missing_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    fails = [x for x in report if x["result"] != "OK"]
    say(f"\n{len(report) - len(fails)} OK, {len(fails)} FAIL. Full report: {args.out}")


def cmd_reopen(args):
    """Maintainers: put jobs back to status:todo (after a converter change, or a bad merge)."""
    issues = gh_json("issue", "list", "-R", REPO, "--state", "all", "--limit", "2000",
                     "--json", "number,body,state,assignees,labels") or []
    for i in issues:
        job = job_of(i.get("body"))
        if not job or (args.job and job not in args.job):
            continue
        if not args.job and not args.all:
            continue
        for pr in gh_json("pr", "list", "-R", REPO, "--state", "open", "--search", f"Closes #{i['number']}",
                          "--json", "number") or []:
            gh("pr", "close", str(pr["number"]), "-R", REPO, "--comment", f"Closed: job reopened ({args.reason}).")
        if i["state"] != "OPEN":
            gh("issue", "reopen", str(i["number"]), "-R", REPO)
        cmd = ["issue", "edit", str(i["number"]), "-R", REPO, "--add-label", "status:todo"]
        for l in i["labels"]:
            if l["name"].startswith("status:") and l["name"] != "status:todo":
                cmd += ["--remove-label", l["name"]]
        for a in i["assignees"]:
            cmd += ["--remove-assignee", a["login"]]
        gh(*cmd)
        gh("issue", "comment", str(i["number"]), "-R", REPO, "--body", f"Reopened: {args.reason}. This job is free again.")
        say(f"reopened #{i['number']} {job}")

# --------------------------------------------------------------------------
# seed: maintainers create labels and one Issue per meeting
# --------------------------------------------------------------------------

LABELS = {
    "status:todo": ("0e8a16", "Free to take"),
    "status:claimed": ("fbca04", "Someone is converting this"),
    "status:needs-verify": ("1d76db", "PR open, needs a second person to reproduce it"),
    "status:verifying": ("5319e7", "Second person is reproducing it"),
    "status:changes-needed": ("d93f0b", "Check or verification failed"),
    "status:blocked": ("b60205", "Script failed; a maintainer must look"),
    "status:done": ("000000", "Merged"),
}


def cmd_seed(args):
    for name, (color, desc) in LABELS.items():
        gh("label", "create", name, "-R", REPO, "--color", color, "--description", desc, "--force")
    have = gh_json("issue", "list", "-R", REPO, "--state", "all", "--limit", "2000",
                   "--json", "body") or []
    have_ids = {job_of(i.get("body")) for i in have}
    jobs: dict[str, list[dict]] = {}
    for r in read_manifest():
        jobs.setdefault(r["job_id"], []).append(r)
    order = sorted(jobs, key=lambda j: jobs[j][0]["date"], reverse=not args.oldest_first)
    made = 0
    for jid in order:
        if jid in have_ids or (args.only and jid != args.only):
            continue
        rows = jobs[jid]
        title = f"{jid}: {rows[0]['meeting_title']} ({len(rows)} sittings)"
        body = (f"job: {jid}\n\nSittings: {rows[0]['date']} to {rows[-1]['date']}\n\n"
                "To work on this, follow [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md). Do not edit this Issue.\n")
        gh("issue", "create", "-R", REPO, "--title", title, "--body", body, "--label", "status:todo")
        made += 1
        say(f"created {title}")
        if args.limit and made >= args.limit:
            break
        time.sleep(3)  # GitHub limits how fast issues can be created
    say(f"created {made} issues")

# --------------------------------------------------------------------------

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # Windows consoles that cannot print all characters
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    w = sub.add_parser("work")
    w.add_argument("--jobs", type=int, default=1)
    w.add_argument("--no-verify", action="store_true", help="only take conversion jobs")
    w.add_argument("--verify-only", action="store_true", help="only verify other people's pull requests")
    w.set_defaults(fn=cmd_work)
    c = sub.add_parser("convert")
    c.add_argument("sitting_id", nargs="+")
    c.set_defaults(fn=cmd_convert)
    k = sub.add_parser("check")
    k.add_argument("paths", nargs="*")
    k.set_defaults(fn=cmd_check)
    e = sub.add_parser("export")
    e.add_argument("outdir")
    e.add_argument("--data", default=str(DATA))
    e.set_defaults(fn=cmd_export)
    cr = sub.add_parser("crawl")
    cr.add_argument("--parlimen", type=int, help="only this Parliament (for testing)")
    cr.set_defaults(fn=cmd_crawl)
    sv = sub.add_parser("survey")
    sv.add_argument("--per", type=int, default=2, help="sittings per Parliament")
    sv.add_argument("--parlimen", type=int, nargs="*", help="only these Parliaments")
    sv.add_argument("--out", default="survey.json")
    sv.add_argument("--keep-pdfs", action="store_true")
    sv.set_defaults(fn=cmd_survey)
    ro = sub.add_parser("reopen")
    ro.add_argument("job", nargs="*", help="job ids; or use --all")
    ro.add_argument("--all", action="store_true")
    ro.add_argument("--reason", required=True)
    ro.set_defaults(fn=cmd_reopen)
    s = sub.add_parser("seed")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--oldest-first", action="store_true")
    s.add_argument("--only", help="create the Issue for this one job id")
    s.set_defaults(fn=cmd_seed)
    a = ap.parse_args()
    r = a.fn(a)
    if a.cmd == "doctor":
        sys.exit(0 if r else 1)


if __name__ == "__main__":
    main()
