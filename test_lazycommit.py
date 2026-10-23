#!/usr/bin/env python3
"""Offline tests for lazycommit. The API and git are mocked throughout.

Run: python3 -m unittest -v
"""

import io
import json
import unittest
from unittest import mock

import lazycommit


class TruncateDiffTests(unittest.TestCase):
    def test_short_diff_unchanged(self):
        diff = "diff --git a/a b/a\n+hello"
        self.assertEqual(lazycommit.truncate_diff(diff, 6000), diff)

    def test_long_diff_is_capped_and_marked(self):
        diff = "x" * 1000
        out = lazycommit.truncate_diff(diff, 100)
        self.assertLessEqual(len(out), 100)
        self.assertIn("truncated", out)
        self.assertTrue(out.startswith("x" * 50))

    def test_exact_limit_unchanged(self):
        diff = "y" * 100
        self.assertEqual(lazycommit.truncate_diff(diff, 100), diff)


class ParseOptionsTests(unittest.TestCase):
    def test_plain_conventional_lines(self):
        text = (
            "feat(auth): add token refresh\n"
            "fix(auth): handle expired tokens on login\n"
            "refactor(auth): extract token parsing\n"
        )
        self.assertEqual(
            lazycommit.parse_options(text),
            [
                "feat(auth): add token refresh",
                "fix(auth): handle expired tokens on login",
                "refactor(auth): extract token parsing",
            ],
        )

    def test_numbering_and_bullets_are_stripped(self):
        text = "1. feat: add a thing\n- fix: repair a thing\n* chore: tidy up\n"
        self.assertEqual(
            lazycommit.parse_options(text),
            ["feat: add a thing", "fix: repair a thing", "chore: tidy up"],
        )

    def test_commentary_lines_are_ignored(self):
        text = (
            "Here are three commit messages for your change:\n"
            "feat: add the thing\n"
            "fix: fix the thing\n"
            "docs: document the thing\n"
            "Let me know if you want more options!\n"
        )
        self.assertEqual(
            lazycommit.parse_options(text),
            ["feat: add the thing", "fix: fix the thing", "docs: document the thing"],
        )

    def test_more_than_three_is_capped(self):
        text = "\n".join(f"feat: option number {i}" for i in range(6))
        self.assertEqual(len(lazycommit.parse_options(text)), 3)

    def test_duplicates_removed(self):
        text = "feat: same line\nfeat: same line\nfix: other line\n"
        self.assertEqual(
            lazycommit.parse_options(text), ["feat: same line", "fix: other line"]
        )

    def test_backticks_stripped(self):
        text = "`feat: wrapped in backticks`"
        self.assertEqual(
            lazycommit.parse_options(text), ["feat: wrapped in backticks"]
        )

    def test_garbage_returns_empty(self):
        self.assertEqual(lazycommit.parse_options(""), [])
        self.assertEqual(lazycommit.parse_options("\n\nshort\n"), [])


class ExtractTextTests(unittest.TestCase):
    def test_plain_text_passthrough(self):
        self.assertEqual(lazycommit.extract_text("feat: hi"), "feat: hi")

    def test_openai_style_json(self):
        body = json.dumps(
            {"choices": [{"message": {"content": "feat: from json"}}]}
        )
        self.assertEqual(lazycommit.extract_text(body), "feat: from json")


class FormatOptionsTests(unittest.TestCase):
    def test_numbered_indented(self):
        out = lazycommit.format_options(["feat: a", "fix: b"])
        self.assertEqual(out, "  1. feat: a\n  2. fix: b")


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RequestOptionsTests(unittest.TestCase):
    def test_request_shape_and_plain_reply(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["payload"] = json.loads(request.data.decode("utf-8"))
            seen["timeout"] = timeout
            return FakeResponse("feat: from the fake API\nfix: also fake\n")

        with mock.patch.object(lazycommit.urllib.request, "urlopen", fake_urlopen):
            options = lazycommit.request_options(
                "the diff", "https://example.invalid/api", "some-model"
            )

        self.assertEqual(seen["url"], "https://example.invalid/api")
        self.assertEqual(seen["payload"]["model"], "some-model")
        content = seen["payload"]["messages"][0]["content"]
        self.assertIn("the diff", content)
        self.assertIn("Conventional Commits", content)
        self.assertEqual(options, ["feat: from the fake API", "fix: also fake"])

    def test_network_failure_becomes_clean_error(self):
        import urllib.error

        def boom(request, timeout=None):
            raise urllib.error.URLError("no route")

        with mock.patch.object(lazycommit.urllib.request, "urlopen", boom):
            with self.assertRaises(lazycommit.LazyCommitError):
                lazycommit.request_options("d", "https://x.invalid/", "m")

    def test_unusable_reply_becomes_clean_error(self):
        with mock.patch.object(
            lazycommit.urllib.request,
            "urlopen",
            lambda request, timeout=None: FakeResponse("???"),
        ):
            with self.assertRaises(lazycommit.LazyCommitError):
                lazycommit.request_options("d", "https://x.invalid/", "m")


def fake_completed(returncode=0, stdout="", stderr=""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


class StagedDiffTests(unittest.TestCase):
    def test_returns_stripped_diff(self):
        with mock.patch.object(
            lazycommit.subprocess,
            "run",
            return_value=fake_completed(stdout="diff --git a b\n"),
        ):
            self.assertEqual(lazycommit.get_staged_diff(), "diff --git a b")

    def test_nothing_staged_is_an_error(self):
        with mock.patch.object(
            lazycommit.subprocess, "run", return_value=fake_completed(stdout="\n")
        ):
            with self.assertRaises(lazycommit.LazyCommitError):
                lazycommit.get_staged_diff()

    def test_not_a_repo_is_an_error(self):
        with mock.patch.object(
            lazycommit.subprocess,
            "run",
            return_value=fake_completed(returncode=128),
        ):
            with self.assertRaises(lazycommit.LazyCommitError):
                lazycommit.get_staged_diff()


class MainFlowTests(unittest.TestCase):
    def test_print_mode_prints_options_and_skips_commit(self):
        stdout = io.StringIO()
        with mock.patch.object(
            lazycommit, "get_staged_diff", return_value="some diff"
        ), mock.patch.object(
            lazycommit,
            "request_options",
            return_value=["feat: one", "fix: two", "chore: three"],
        ), mock.patch.object(
            lazycommit, "commit"
        ) as commit_mock, mock.patch(
            "sys.stdout", stdout
        ):
            code = lazycommit.main(["--print"])
        self.assertEqual(code, 0)
        commit_mock.assert_not_called()
        self.assertIn("1. feat: one", stdout.getvalue())

    def test_pick_commits_the_choice(self):
        with mock.patch.object(
            lazycommit, "get_staged_diff", return_value="some diff"
        ), mock.patch.object(
            lazycommit,
            "request_options",
            return_value=["feat: one", "fix: two"],
        ), mock.patch.object(
            lazycommit, "commit"
        ) as commit_mock, mock.patch(
            "builtins.input", return_value="2"
        ), mock.patch(
            "sys.stdout", io.StringIO()
        ):
            code = lazycommit.main([])
        self.assertEqual(code, 0)
        commit_mock.assert_called_once_with("fix: two")

    def test_quit_commits_nothing(self):
        with mock.patch.object(
            lazycommit, "get_staged_diff", return_value="some diff"
        ), mock.patch.object(
            lazycommit, "request_options", return_value=["feat: one"]
        ), mock.patch.object(
            lazycommit, "commit"
        ) as commit_mock, mock.patch(
            "builtins.input", return_value="q"
        ), mock.patch(
            "sys.stdout", io.StringIO()
        ):
            code = lazycommit.main([])
        self.assertEqual(code, 0)
        commit_mock.assert_not_called()

    def test_error_path_returns_1(self):
        with mock.patch.object(
            lazycommit,
            "get_staged_diff",
            side_effect=lazycommit.LazyCommitError("nothing staged"),
        ), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(lazycommit.main([]), 1)


if __name__ == "__main__":
    unittest.main()
