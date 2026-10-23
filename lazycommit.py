#!/usr/bin/env python3
"""lazycommit: turn a staged git diff into three commit message options.

Reads `git diff --cached`, sends it to a text model, prints three
conventional-commit messages, and commits with the one you pick.

Stdlib only. No dependencies, no config file, no API key by default.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://text.pollinations.ai/"
DEFAULT_MODEL = "openai"
DEFAULT_MAX_DIFF_CHARS = 6000
REQUEST_TIMEOUT = 60

CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-z0-9._/-]+\))?!?: .+"
)

PROMPT_TEMPLATE = """Write exactly 3 commit messages for the staged diff below.

Rules:
- Conventional Commits format: type(scope): summary
- One message per line, no numbering, no quotes, no extra text
- Imperative mood, summary under 72 characters
- Each message takes a slightly different angle on the same change

Diff:
{diff}
"""


class LazyCommitError(Exception):
    """A user-facing failure. Printed plainly, exit code 1."""


def run_git(args):
    return subprocess.run(
        ["git"] + args, capture_output=True, text=True
    )


def get_staged_diff():
    result = run_git(["diff", "--cached"])
    if result.returncode != 0:
        raise LazyCommitError("not a git repository (or git is missing)")
    diff = result.stdout.strip()
    if not diff:
        raise LazyCommitError(
            "nothing staged. Stage something first: git add <files>"
        )
    return diff


def truncate_diff(diff, limit):
    """Cap the diff so the request stays small and cheap.

    Keeps the head of the diff, which carries the file headers and the
    first hunks, and says plainly that the rest was cut.
    """
    if len(diff) <= limit:
        return diff
    marker = "\n... [diff truncated by lazycommit]"
    return diff[: limit - len(marker)] + marker


def build_prompt(diff):
    return PROMPT_TEMPLATE.format(diff=diff)


def extract_text(body):
    """The endpoint answers with plain text or OpenAI-style JSON."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body.strip()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return body.strip()


def request_options(diff, endpoint, model):
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": build_prompt(diff)}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise LazyCommitError(f"request to {endpoint} failed: {exc}")
    options = parse_options(extract_text(body))
    if not options:
        raise LazyCommitError("the model returned no usable commit messages")
    return options


def clean_line(line):
    line = line.strip().strip("`")
    line = re.sub(r"^(\d+[.)]|[-*])\s+", "", line)
    return line.strip()


def parse_options(text, limit=3):
    """Pull up to `limit` plausible commit subjects out of model output.

    Prefers lines that match Conventional Commits. Falls back to any
    short, clean lines if the model ignored the format.
    """
    lines = [clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    strict = [line for line in lines if CONVENTIONAL_RE.match(line)]
    pool = strict if strict else [l for l in lines if 8 <= len(l) <= 100]
    options = []
    for line in pool:
        if line not in options:
            options.append(line)
        if len(options) == limit:
            break
    return options


def format_options(options):
    return "\n".join(
        f"  {i}. {option}" for i, option in enumerate(options, start=1)
    )


def choose(options):
    print(format_options(options))
    while True:
        try:
            raw = input(f"pick 1-{len(options)} (or q to quit): ").strip()
        except EOFError:
            return None
        if raw.lower() in ("q", ""):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"enter a number between 1 and {len(options)}, or q")


def commit(message):
    result = run_git(["commit", "-m", message])
    if result.returncode != 0:
        raise LazyCommitError("git commit failed:\n" + result.stderr.strip())
    print(result.stdout.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="lazycommit",
        description="Generate commit messages from your staged diff.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("LAZYCOMMIT_MODEL", DEFAULT_MODEL),
        help=f"model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("LAZYCOMMIT_ENDPOINT", DEFAULT_ENDPOINT),
        help=f"API endpoint (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=DEFAULT_MAX_DIFF_CHARS,
        help=f"truncate the diff past this many characters "
        f"(default: {DEFAULT_MAX_DIFF_CHARS})",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_only",
        help="print the options and stop, do not commit",
    )
    args = parser.parse_args(argv)

    try:
        diff = truncate_diff(get_staged_diff(), args.max_diff_chars)
        options = request_options(diff, args.endpoint, args.model)
        if args.print_only:
            print(format_options(options))
            return 0
        message = choose(options)
        if message is None:
            print("nothing committed")
            return 0
        commit(message)
        return 0
    except LazyCommitError as exc:
        print(f"lazycommit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
