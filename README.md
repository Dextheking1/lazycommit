# lazycommit

You already did the work. Writing the commit message is the part where you
stare at a blinking cursor and type "fix stuff".

lazycommit reads your staged diff, asks a text model for three commit
messages in Conventional Commits format, and lets you pick one. Pick, enter,
done. The thinking was the code. The message is clerical work, so a machine
does it.

## What it does

1. Runs `git diff --cached` and takes your staged changes.
2. Truncates the diff past 6,000 characters so the request stays small.
3. Sends it to the Pollinations text API (free, no API key, open endpoint).
4. Prints three options, in `type(scope): summary` format.
5. You type `1`, `2` or `3`. It commits with that message. `q` walks away
   and commits nothing.

That is the whole tool. One Python file, standard library only, nothing to
install beyond Python 3.

## Install

```bash
git clone <this repo>
cd lazycommit
chmod +x lazycommit.py
# optional: put it on your PATH
ln -s "$PWD/lazycommit.py" ~/.local/bin/lazycommit
```

## Usage

```bash
git add stats.py
lazycommit            # get 3 options, pick one, it commits
lazycommit --print    # print the options only, commit nothing
```

If nothing is staged, it tells you and exits. If the API is unreachable, it
tells you that too, in one line, instead of dumping a traceback.

## Demo

A real run against the live free API, in a throwaway repo. The staged change
adds an empty-list guard to an `average()` helper:

```text
$ git add stats.py
$ lazycommit
  1. feat(stats): handle empty list in average
  2. fix(stats): return 0 for empty numbers
  3. perf(stats): guard against division by zero
pick 1-3 (or q to quit): 1
[master bab7bea] feat(stats): handle empty list in average
 1 file changed, 2 insertions(+)
```

Three usable messages in about ten seconds, most of it network time.
Writing any one of them by hand takes longer, and you still have to decide
whether it was a `feat` or a `fix`. (Reasonable people disagree. The model
offered both.)

## Configuration

No config file. Two flags, or the matching environment variables:

| Setting  | Flag         | Env var              | Default                          |
| -------- | ------------ | -------------------- | -------------------------------- |
| Model    | `--model`    | `LAZYCOMMIT_MODEL`   | `openai`                         |
| Endpoint | `--endpoint` | `LAZYCOMMIT_ENDPOINT` | `https://text.pollinations.ai/` |
| Diff cap | `--max-diff-chars` | n/a            | `6000`                           |

The endpoint speaks the usual chat shape (a `messages` array in, text or
OpenAI-style JSON out), so pointing it at another compatible service is a
one-line change. If your endpoint needs a key, use one that reads it from
the environment, or wrap the call. The default endpoint needs no key at all.

## How it works

- The prompt asks for exactly three lines, Conventional Commits format,
  imperative mood, under 72 characters, each from a slightly different
  angle on the same change.
- The reply is parsed defensively. Numbering, bullets and backticks are
  stripped, lines that match the Conventional Commits pattern win, and
  chatty extras ("Here are your messages!") are ignored. If nothing usable
  comes back, you get a clean error, not a garbage commit.
- Only the staged diff leaves your machine, capped at the character limit.
  Unstaged work stays home.

## Tests

Offline, with the API and git mocked:

```bash
python3 -m unittest -v   # 23 tests
```

## The laziness math

A commit message takes maybe 30 to 60 seconds of genuine thought if you
write a good one, several times a day, every day you code. lazycommit
turns that into reading three lines and pressing one key. The saved
minutes are small. The saved decision is the point: one less context
switch between "I finished the change" and "I am done".

## License

MIT. See `LICENSE`.
