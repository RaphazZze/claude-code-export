---
name: export-session
description: Export a Claude Code session from its raw `.jsonl` file into a clean, readable Markdown file. Keeps a one-line marker per tool call; strips tool inputs, tool results, code execution output, and internal thinking blocks — keeping only the human-readable dialogue. Messages are labelled with the speaker's name and time (e.g. `### ❯ User · 10:25 AM`). The date is shown once at the top and again only when it changes, for multi-day sessions. File and image attachments from the user are noted inline (e.g. ``> `📎` Image attached: image/jpeg``).
---

# export-session

## Instructions

**Step 1 — Ask for the user's name.**
Use the AskUserQuestion tool with a single question: "What's your name? (used to label your messages in the export)" and make it optional/skippable. If the user provides a name, use it in place of `"User"` as the label throughout the export. If they skip or leave it blank, default to `"User"`.

**Step 2 — Resolve the `.jsonl` input file.**

- If a path is provided as an argument, use it as the path to the `.jsonl` file.
- Otherwise, auto-detect from this project's session folder under `~/.claude/projects/` (or `$CLAUDE_CONFIG_DIR/projects/`): the current session's `.jsonl` (`$CLAUDE_CODE_SESSION_ID`), else the most recently modified one.

Run this snippet as is to auto-detect (do not modify it; it reproduces Claude Code's default folder naming, checked by `tests/test_autodetect.py`):

```bash
python3 -I - <<'PY'
import glob, os, sys, unicodedata as u
def units(s): return [c for ch in s for c in ([ord(ch)] if ord(ch) < 0x10000 else [0xD800 + ((ord(ch) - 0x10000) >> 10), 0xDC00 + ((ord(ch) - 0x10000) & 0x3FF)])]
def b36(n):
    d = ""
    while True:
        n, r = divmod(n, 36); d = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + d
        if not n: return d
def slug(p):
    cu = units(p)
    s = "".join(chr(c) if c < 128 and chr(c).isalnum() else "-" for c in cu)
    if len(s) <= 200: return s
    h = 0
    for c in cu: h = (h * 31 + c) & 0xFFFFFFFF
    h = h - (1 << 32) if h >= 1 << 31 else h
    return s[:200] + "-" + b36(abs(h))
root = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")
paths = {u.normalize(f, p) for p in {os.environ.get("PWD", ""), os.getcwd()} if p for f in ("NFC", "NFD")}
names = {slug(p) for p in paths} | ({os.environ["CLAUDE_CODE_PROJECT_DIR_NAME"]} if os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME") else set())
found = [j for n in names for j in glob.glob(os.path.join(glob.escape(os.path.join(root, n)), "*.jsonl"))]
sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
mine = [j for j in found if os.path.basename(j) == sid + ".jsonl"]
print(mine[0] if mine else max(found, key=os.path.getmtime) if found else "")
def state(p):
    try: os.listdir(p); return "ok"
    except (FileNotFoundError, NotADirectoryError): return "missing"
    except OSError: return "unreadable"
if not found:
    s = state(root)
    if s != "ok":
        why = ("no projects folder at " if s == "missing" else "cannot read ") + root
    else:
        hits = [(f, state(f)) for f in (os.path.join(root, n) for n in sorted(names))]
        bad = [f for f, s in hits if s == "unreadable"]
        empty = [f for f, s in hits if s == "ok"]
        why = (f"cannot read {bad[0]}" if bad else f"no .jsonl in {empty[0]}" if empty else
               f"no session folder for this directory in {root}")
    print(f"auto-detect: {why}", file=sys.stderr)
PY
```

If it prints no path, tell the user the reason it printed (`auto-detect: …`), then ask for the `.jsonl` path.

**Step 3 — Run the export using the Bash tool.**

Use the `claudecode_export.py` script that lives next to this SKILL.md (in the skill's base directory):

```bash
python3 <skill_dir>/claudecode_export.py <jsonl_path> --name "<name>" -o .
```

Replace `<skill_dir>` with the skill's base directory (provided to you at invocation time), `<jsonl_path>` with the resolved path from Step 2, and `<name>` with the name from Step 1 (or `User` if skipped).

The script will print the output filename on success. Report it to the user.
