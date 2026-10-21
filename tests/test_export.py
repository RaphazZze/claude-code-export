#!/usr/bin/env python3
"""Regression test for claudecode_export.py — one fixture, one expected export.

    python3 tests/test_export.py            # run the test
    python3 tests/test_export.py --update   # regenerate the expected export

`every_record_class.jsonl` carries one record of every class the exporter has
ever mishandled, so the diff below is the guard on all of them at once:

  - a skill injection arriving as a user message (the body must not appear;
    the marker comes from the assistant's own `Skill` call)
  - a queued `queued_command` attachment, which has no `message` key and so
    never reaches the role dispatch
  - a queued attachment in `task-notification` mode, which is the harness
    rather than the user, and a queued sub-agent hand-back (`isMeta`, origin
    `peer`), which is the agent rather than the user
  - a background task notification carrying its whole result payload
  - an `isMeta` user record
  - a slash command, plus the expanded body the harness sends after it
  - a sidechain record, and a `file-history-snapshot` record
  - a `Bash` call (description only, never the command) and one with no
    description at all
  - `Write`, `Edit`, `Skill` with args, `Agent` with a type and a model
  - an MCP call with a single-line and a multi-line parameter
  - `AskUserQuestion` and the answer that arrives as a `tool_result`
  - image and document attachments
  - paths needing sanitization, including ones inside a markdown link, an
    inline code span, a fenced block and a bare URL, which must be left alone
  - cloud-storage paths that would otherwise reveal the machine's setup
  - consecutive marker-only blocks that merge, and a duplicate that dedupes
  - a date change, which starts a new date heading
  - assistant records carrying a model, including a `<synthetic>` one, which is
    a harness-written line rather than a model and must not read as a change
  - a `/model` command whose output names the model it selected, and one that
    names nothing, where the record after it is real dialogue and must survive
  - a harness compaction digest, which is not dialogue: once naming this same
    transcript, where the dialogue it covers is still above it, and once naming
    a different one, where it genuinely is elsewhere
  - the bare `/compact` the user typed, which arrives a second time as a
    `<command-name>` record and must not be counted twice
  - pasted text inside the harness's `<pasted_content id="…">` wrapper, once
    inside the user's own ``` fence, and an `<ide_selection>` wrapper — the
    wrappers must not reach the page raw
  - a user who merely mentions `<pasted_content`, across lines and in inline
    code, whose text must survive whole
  - `api-request-blob` records, which replay earlier turns with a role but no
    timestamp and are not dialogue, and a role-bearing record with no `type`
    at all, an older shape that must still export
  - the same `Edit` three times, one call per record with its result between,
    which shows as one marker
  - an image-only user turn followed by a command, which stay two turns
  - an assistant text block that is wholly a harness system reminder

**`--update` is not a way to make a failure go away.** The expected file is
checked in, so a regenerated one lands as a reviewable diff — read that diff
and decide whether the change is the fix or the defect.

A normalised cloud-storage path and its placeholder are expected to render as
one code span — `` `<Obsidian>/Notes/index.md` ``, never with the placeholder
stranded outside it. That was a real defect until 2026-09-09: the bare-path
rule matched from the slash, so the code span opened mid-path.

Determinism: the timezone is pinned to UTC and `Path.home()` is patched, so
the expected export is byte-identical on any machine. The one line that
cannot be pinned — the export date — is normalised before the diff.
"""

import argparse
import difflib
import importlib.util
import pathlib
import re
import sys
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
EXPORTER = HERE.parent / "claudecode_export.py"
FIXTURE = HERE / "every_record_class.jsonl"
EXPECTED = HERE / "every_record_class.expected.md"

# The fixture's paths are rooted here, so sanitization is exercised against a
# synthetic home rather than whatever machine happens to be running the test.
FAKE_HOME = "/home/testuser"

# What the export must contain, counted after dedup and after consecutive
# marker-only blocks merge. `--count-only` has to agree with these too: it is
# a second route to the same answer, and the two drifting apart is the defect
# this pair of assertions exists to catch.
EXPECT_USER = 18
EXPECT_ASSISTANT = 21

# Content the fixture deliberately contains and the export must never carry.
# The full diff would catch each of these as an added line; naming them
# separately means a later edit that quietly drops one from the fixture is
# reported as a missing guard rather than passing silently.
FORBIDDEN = [
    ("hunter2", "a credential inside a Bash command body"),
    ("--password", "a Bash command body"),
    ("ls -la", "a Bash command body with no description"),
    ("Sub-agent reasoning", "a sidechain record"),
    ("The whole skill body", "an injected skill body"),
    ("Harness injection", "an isMeta harness record"),
    ("Expanded command output", "a slash command's expanded body"),
    ("Background ping", "a queued task-notification attachment"),
    ("sub-agent report delivered mid-turn", "a queued sub-agent hand-back"),
    ("entire task result payload", "a task notification's payload"),
    ("Internal reminder", "a system-reminder tag's contents"),
    ("<system-reminder>", "a raw system-reminder tag"),
    ("<task-notification>", "a raw task-notification tag"),
    ("trackedFileBackups", "a file-history-snapshot record"),
    ("Primary Request and Intent", "a harness compaction digest's body"),
    ("A digest the harness wrote", "a compaction digest attributed to the user"),
    ("ran out of context", "a compaction digest's opening line"),
    ("Compacted (ctrl+o", "the /compact command's own output"),
    ("saved as your default", "the /model command's output, beyond the model name"),
    ("\x1b[", "a terminal colour code from command output"),
    ('pasted_content id="4f2a"', "the harness's pasted-text wrapper"),
    ('pasted_content id="9c1d"', "a pasted-text wrapper inside a user fence"),
    ("Tool ran without output", "a system reminder in an assistant text block"),
    ("<ide_selection>", "a raw ide_selection tag"),
    ("This may or may not be related", "the ide_selection boilerplate"),
    ("by the API request log", "an api-request-blob replay"),
    ("_[File attached", "an attachment notice in the old italic form"),
    (FAKE_HOME, "an unsanitized absolute home path"),
]

EXPORT_DATE_RE = re.compile(r"^\*\*Exported:\*\* \d{4}-\d{2}-\d{2}$", re.M)
EXPORT_DATE_PLACEHOLDER = "**Exported:** <NORMALISED>"


def load_exporter():
    spec = importlib.util.spec_from_file_location("claudecode_export", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Pinned rather than detected: the module reads /etc/localtime at import.
    module.LOCAL_TZ = ZoneInfo("UTC")
    return module


def run_exporter(module):
    """Return (normalised markdown, (user_count, assistant_count), count_only)."""
    real_home = pathlib.Path.home
    pathlib.Path.home = classmethod(lambda cls: pathlib.Path(FAKE_HOME))
    try:
        markdown, counts, _ = module.convert(FIXTURE, "User", "Claude", "12")
        count_only = module.count_messages(FIXTURE)
    finally:
        pathlib.Path.home = real_home
    return EXPORT_DATE_RE.sub(EXPORT_DATE_PLACEHOLDER, markdown), counts, count_only


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--update", action="store_true",
                        help="rewrite the expected export from today's exporter")
    args = parser.parse_args()

    if not EXPORTER.exists():
        print(f"FAIL  exporter not found at {EXPORTER}")
        return 1

    module = load_exporter()
    actual, counts, count_only = run_exporter(module)

    if args.update:
        EXPECTED.write_text(actual, encoding="utf-8")
        print(f"  wrote {EXPECTED.name}  ({len(actual.splitlines())} lines)")
        print(f"  export counts:      {counts[0]} user, {counts[1]} assistant")
        print(f"  --count-only says:  {count_only[0]} user, {count_only[1]} assistant")
        print("\n  Review the diff before committing it.")
        return 0

    failures = []

    if not EXPECTED.exists():
        print(f"FAIL  no expected export at {EXPECTED} — run with --update")
        return 1

    expected = EXPECTED.read_text(encoding="utf-8")
    if actual != expected:
        diff = difflib.unified_diff(
            expected.splitlines(keepends=True), actual.splitlines(keepends=True),
            fromfile="expected", tofile="actual", n=2,
        )
        failures.append("the export does not match the expected output:\n"
                        + "".join(diff))

    if counts != (EXPECT_USER, EXPECT_ASSISTANT):
        failures.append(
            f"the export holds {counts[0]} user / {counts[1]} assistant messages, "
            f"expected {EXPECT_USER} / {EXPECT_ASSISTANT}")

    if count_only != counts:
        failures.append(
            f"--count-only disagrees with the export it counts: it reports "
            f"{count_only[0]} user / {count_only[1]} assistant, the export holds "
            f"{counts[0]} / {counts[1]}")

    for needle, what in FORBIDDEN:
        if needle in actual:
            failures.append(f"the export leaked {what} (found {needle!r})")

    checks = 3 + len(FORBIDDEN)
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        print(f"\n{len(failures)} of {checks} checks failed")
        return 1

    print(f"PASS  {checks} checks · {len(actual.splitlines())} lines · "
          f"{counts[0]} user / {counts[1]} assistant messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
