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

# Made on macOS, 26 Nov 2026. 2026-10-09 is byte-identical to PR #285.
EXPECTED = {
    "data/2008/2008-04-29.md": "bfd560b7a8381209464ad60b4dfde59b2a9e6a985e2c823a8635a0dbb530593b",
    "data/2026/2026-10-09.md": "fb421a062cdf201c02e4894d391403c4319d091613d2e3200b0f12834e812d5c",
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
