"""Regression tests for the volunteer loop (GitHub calls are replaced by fakes)."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("hansard", Path(__file__).resolve().parent.parent / "hansard.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def fake_gh(claimed, redo, prs):
    def gh_json(*args):
        if args[:2] == ("issue", "list") and "status:claimed" in args:
            return claimed
        if args[:2] == ("issue", "list") and "status:changes-needed" in args:
            return redo
        if args[:2] == ("pr", "list"):
            return prs
        raise AssertionError(args)
    return gh_json


class FindOwnIssue(unittest.TestCase):
    def setUp(self):
        self.real = h.gh_json

    def tearDown(self):
        h.gh_json = self.real

    def test_claimed_job_with_open_pr_is_not_done_again(self):
        # 26 Nov 2026: job #4 was converted 3 times in one run, because its label
        # was still status:claimed for ~30 s after the PR opened.
        h.gh_json = fake_gh([{"number": 4, "body": "job: p15-s5-m3-j2"}], [], [{"body": "Closes #4\n\njob: x"}])
        self.assertIsNone(h.find_own_issue("me", set()))

    def test_claimed_job_without_pr_is_continued(self):
        h.gh_json = fake_gh([{"number": 4, "body": "job: a"}], [], [])
        self.assertEqual(h.find_own_issue("me", set())["number"], 4)

    def test_job_done_in_this_run_is_skipped(self):
        h.gh_json = fake_gh([], [{"number": 9, "body": "job: a"}], [])
        self.assertIsNone(h.find_own_issue("me", {9}))

    def test_changes_needed_is_continued_even_with_pr(self):
        h.gh_json = fake_gh([], [{"number": 9, "body": "job: a"}], [{"body": "Closes #9"}])
        self.assertEqual(h.find_own_issue("me", set())["number"], 9)


if __name__ == "__main__":
    unittest.main()
