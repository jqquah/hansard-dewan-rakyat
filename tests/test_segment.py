"""Regression tests. Each case is a real layout found in a Hansard PDF.
Run: python -m unittest discover tests
Rule: when you find a new conversion bug, add its lines here first."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("hansard", Path(__file__).resolve().parent.parent / "hansard.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def labels(lines):
    pages = [lines]
    blocks = h.segment(pages)
    h.fidelity(pages, "\n".join(h.render(blocks)))  # never lose or change a character
    return [b[1] for b in blocks if b[0] == "speech"]


class Labels(unittest.TestCase):
    def test_modern_one_line(self):  # 2026-11-25
        self.assertEqual(labels(["Tuan Cha Kee Chin [Rasah]: Terima kasih."]), ["Tuan Cha Kee Chin [Rasah]"])

    def test_chair_without_bracket(self):  # 2008-04-29
        self.assertEqual(labels(["Tuan Yang di-Pertua: Ahli-ahli Yang Berhormat."]), ["Tuan Yang di-Pertua"])

    def test_question_line_is_not_a_label(self):  # "Tuan X [Rasah] minta Menteri ..." has no colon
        self.assertEqual(labels(["1.", "Tuan Cha Kee Chin [Rasah] minta Menteri Pengangkutan menyatakan"]), [])

    def test_1964_round_brackets(self):  # 1964-05-20
        self.assertEqual(labels(["their hour of bereavement.", "Dr Tan Chee Khoon (Batu): Tuan"]),
                         ["Dr Tan Chee Khoon (Batu)"])

    def test_1964_name_wraps_two_lines(self):  # 1964-05-20
        self.assertEqual(labels(["Front.", "Tuan Haji Ahmad bin Abdullah", "(Kelantan Hilir): Tuan Yang di-Pertua,"]),
                         ["Tuan Haji Ahmad bin Abdullah (Kelantan Hilir)"])

    def test_1964_hyphen_split_name(self):  # 1964-05-20
        self.assertEqual(labels(["Sekian-lah.", "Enche' Mohamed Yusof bin Mah-", "mud (Temerloh): Tuan"]),
                         ["Enche' Mohamed Yusof bin Mah- mud (Temerloh)"])

    def test_name_ending_in_haji(self):  # 1964-05-20: line ends in a name word, not a joining word
        self.assertEqual(labels(["principles in this nation.", "Enche' Mohamed Asri bin Haji",
                                 "Muda (Pasir Puteh): Tuan Yang di-"]),
                         ["Enche' Mohamed Asri bin Haji Muda (Pasir Puteh)"])

    def test_justified_one_word_per_line(self):  # 2026-11-25 p.47: 9 lines for one label
        lines = ["tadi.", "Dato’", "Sri", "Ikmal", "Hisham", "bin", "Abdul", "Aziz", "[Tanah", "Merah]: Bismillah."]
        self.assertEqual(labels(lines), ["Dato’ Sri Ikmal Hisham bin Abdul Aziz [Tanah Merah]"])

    def test_heading_not_glued_to_label(self):  # 1964-05-20: "MOTIONS / ACCESS TO PARLIAMENT"
        self.assertEqual(labels(["MOTIONS", "ACCESS TO PARLIAMENT", "The Minister of Home Affairs and",
                                 "Minister of Justice (Dato' Dr Ismail):"]),
                         ["The Minister of Home Affairs and Minister of Justice (Dato' Dr Ismail)"])

    def test_sentence_not_glued_to_label(self):  # 1964-05-20
        self.assertEqual(labels(["kaseh,", "Tuan Yang di-Pertua.", "Enche' D. R. Seenivasagam (Ipoh):"]),
                         ["Enche' D. R. Seenivasagam (Ipoh)"])

    def test_ellipsis_ends_sentence(self):  # 2025-08-14
        self.assertEqual(labels(["Okey, nombor dua, Tuan Pengerusi ialah KWSP. Saya minta supaya Akaun 3 ini…",
                                 "Timbalan Yang di-Pertua [Dato’ Dr Ramli bin Dato’ Mohd Nor]: Ya."]),
                         ["Timbalan Yang di-Pertua [Dato’ Dr Ramli bin Dato’ Mohd Nor]"])

    def test_title_case_subheading_not_glued(self):  # 2024-12-10
        self.assertEqual(labels(["RANG UNDANG-UNDANG PERBEKALAN 2025", "Bacaan Kali Yang Kedua dan Ketiga",
                                 "Dato’ Seri Dr. Shahidan bin Kassim [Arau]: Terima kasih."]),
                         ["Dato’ Seri Dr. Shahidan bin Kassim [Arau]"])

    def test_open_bracket_title_wraps(self):  # 2022-12-19
        self.assertEqual(labels(["ini.", "Menteri di Jabatan Perdana Menteri (Undang-Undang dan Reformasi",
                                 "Institusi) [Dato’ Sri Azalina Othman Said]: Terima kasih."]),
                         ["Menteri di Jabatan Perdana Menteri (Undang-Undang dan Reformasi Institusi) "
                          "[Dato’ Sri Azalina Othman Said]"])


class Headings(unittest.TestCase):
    def test_acronym_ending_sentence_is_not_heading(self):  # 2026-06-22: "NCII." and "PDRM."
        for line in ("NCII.", "PDRM.", "NFA?", "M.C.A.", "ANTHONY FREDERICKS, A.M.N."):
            self.assertFalse(h.is_heading(line), line)

    def test_real_headings(self):
        for line in ("DOA", "PERTANYAAN-PERTANYAAN BAGI JAWAB LISAN", "USUL:", "RANG UNDANG-UNDANG:"):
            self.assertTrue(h.is_heading(line), line)


class Furniture(unittest.TestCase):
    def test_page_header_removed(self):
        pages = h.strip_furniture([["DR. 25.11.2026", "2", "PERKESO, masih dimasukkan"]])
        self.assertEqual(pages, [["PERKESO, masih dimasukkan"]])

    def test_1964_header_removed(self):
        pages = h.strip_furniture([["59", "20 MAY 1964", "60", "memorable not because"]])
        self.assertEqual(pages, [["memorable not because"]])

    def test_number_in_body_kept(self):  # only the first 4 and last 3 lines are page edges
        lines = ["a", "b", "c", "d", "e", "1.", "f", "g", "h", "i"]
        self.assertIn("1.", h.strip_furniture([lines])[0])


class Fidelity(unittest.TestCase):
    def test_detects_changed_word(self):
        pages = [["Tuan Cha Kee Chin [Rasah]: Terima kasih."]]
        with self.assertRaises(AssertionError):
            h.fidelity(pages, "**Tuan Cha Kee Chin [Rasah]:** Terima kasihh.")


if __name__ == "__main__":
    unittest.main()
