"""Rules for when the bot may merge. Each case is a real or likely failure."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("bot", Path(__file__).resolve().parent.parent / "tools" / "bot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

HEAD = "97c6e7943b0e340548e8a52a9495f359b70d8989"
OK = "/verified\n\nI converted all 1 sittings again. All 2 files match byte for byte.\n\nhead: " + HEAD


def live(state="OPEN", head=HEAD, labels=("status:verifying",)):
    return {"state": state, "headRefOid": head, "labels": [{"name": l} for l in labels]}


class MergeBlocker(unittest.TestCase):
    def test_all_good_merges(self):
        self.assertIsNone(bot.merge_blocker(live(), OK, lambda: []))

    def test_closed_pr_is_not_merged(self):  # 26 Nov 2026: PR #3 was verified after it was closed
        self.assertIn("closed", bot.merge_blocker(live(state="CLOSED"), OK, lambda: []))

    def test_new_commit_after_verification_is_not_merged(self):
        self.assertIn("different commit", bot.merge_blocker(live(head="0" * 40), OK, lambda: []))

    def test_comment_without_head_is_not_merged(self):
        self.assertIn("different commit", bot.merge_blocker(live(), "/verified", lambda: []))

    def test_old_converter_version_is_not_merged(self):  # PR #3 had 1.0.0 files after 1.1.0
        r = bot.merge_blocker(live(), OK, lambda: ["made by hansard.py 1.0.0, current is 1.1.0"])
        self.assertIn("data checks fail", r)

    def test_wrong_status_is_not_merged(self):
        self.assertIn("status:verifying", bot.merge_blocker(live(labels=("status:needs-verify",)), OK, lambda: []))


if __name__ == "__main__":
    unittest.main()
