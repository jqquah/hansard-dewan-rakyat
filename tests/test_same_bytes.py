"""Verification needs the same bytes on every computer. CI runs this on Linux, Windows and macOS.
If a new pymupdf or Python version changes the output, this test fails before volunteers see it."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hansard", HERE.parent / "hansard.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

# Made on macOS with VERSION 1.1.0, 26 Nov 2026. Update these when VERSION changes.
EXPECTED = {
    "data/2008/2008-04-29.md": "4ed92fd30a3c984f85921e8f60f071867ccd7334138f9d922954cc7b0d4a56a4",
    "data/2026/2026-10-09.md": "23996f8c35dcfc110ca3f826b7ba38ff39957eb5ec41df41d5533beabe2b1e6b",
}


class SameBytes(unittest.TestCase):
    def test_output_is_identical_everywhere(self):
        h.CACHE = HERE / "fixtures"
        rows = {r["sitting_id"]: r for r in h.read_manifest()}
        got = {}
        with tempfile.TemporaryDirectory() as t:
            for sid in ("2008-04-29", "2026-10-09"):
                for p in h.convert_row(rows[sid], out_root=Path(t)):
                    got[p.relative_to(t).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(got, EXPECTED)


if __name__ == "__main__":
    unittest.main()
