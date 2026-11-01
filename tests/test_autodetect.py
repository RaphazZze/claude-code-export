#!/usr/bin/env python3
"""Test for SKILL.md Step 2's auto-detect snippet.

    python3 tests/test_autodetect.py

The snippet is run exactly as it appears in SKILL.md (extracted from its heredoc).

1. Naming: `slug()` must equal Claude Code's own folder-naming function on every
   path in `autodetect_expected.json`. Those expected names were produced by that
   function (Claude Code 2.1.316), run in Node:
       e = t.replace(/[^a-zA-Z0-9]/g, "-")
       if (e.length <= 200) return e
       return `${e.slice(0, 200)}-${Math.abs(hash(t)).toString(36)}`
   where hash(t) is `(h << 5) - h + t.charCodeAt(i) | 0` over the path.
   Re-pin with that function if Claude Code changes it.
2. Lookup: the whole snippet, run in a temp tree via `CLAUDE_CONFIG_DIR`, must
   find a session folder named from either accent form of the cwd, from `$PWD`
   or from the resolved path, from a path over 200 characters, from
   `CLAUDE_CODE_PROJECT_DIR_NAME`, and under a config dir whose name holds glob
   characters; it prints nothing when no folder matches.
3. Session choice: with `CLAUDE_CODE_SESSION_ID` set it prints that session's
   file even when another session wrote later; unset, or naming no file in the
   folder, it falls back to the newest.
"""
import json, os, re, subprocess, sys, tempfile, unicodedata as u
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
EXPECTED = HERE / "autodetect_expected.json"
STRIPPED = ("CLAUDE_CODE_PROJECT_DIR_NAME", "CLAUDE_CODE_SESSION_ID")


def snippet():
    m = re.search(r"python3 -I - <<'PY'\n(.*?)\nPY\n", SKILL.read_text(), re.S)
    if not m:
        sys.exit(f"FAIL  no auto-detect heredoc in {SKILL}")
    return m.group(1)


def run(code, cwd, root, pwd=None, **env_extra):
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    env.update(CLAUDE_CONFIG_DIR=root, PWD=pwd or cwd, **env_extra)
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=cwd, env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main():
    code = snippet()
    ns = {}
    exec(code.split("\nroot = ")[0], ns)
    slug = ns["slug"]
    failures, checks = [], 0

    pinned = json.loads(EXPECTED.read_text())
    if len(pinned) < 10 or not any(len(want) > 200 for _, want in pinned):
        sys.exit(f"FAIL  {EXPECTED.name} has {len(pinned)} pairs; it needs at least 10, "
                 "one of them over the 200-character cap")
    for path, want in pinned:
        checks += 1
        if slug(path) != want:
            failures.append(f"naming {path!r}: got {slug(path)!r}, want {want!r}")

    with tempfile.TemporaryDirectory() as t:
        t = os.path.realpath(t)
        cases = []

        def session(name, real_dir, root=os.path.join(t, "config"), pwd=None, folder_name=None,
                    make_folder=True, **env_extra):
            os.makedirs(real_dir, exist_ok=True)
            folder = os.path.join(root, "projects", folder_name or slug(name))
            if make_folder:
                os.makedirs(folder, exist_ok=True)
                Path(folder, "s.jsonl").write_text("{}\n")
            return run(code, real_dir, root, pwd, **env_extra), os.path.join(folder, "s.jsonl")

        nfc = os.path.join(t, u.normalize("NFC", "Café one"))
        cases.append(("decomposed-form folder, composed cwd", *session(u.normalize("NFD", nfc), nfc)))
        nfd = os.path.join(t, u.normalize("NFD", "Café two"))
        cases.append(("composed-form folder, decomposed cwd", *session(u.normalize("NFC", nfd), nfd)))

        real1, link1 = os.path.join(t, "real one"), os.path.join(t, "link one")
        os.makedirs(real1, exist_ok=True)
        os.symlink(real1, link1)
        cases.append(("folder named from $PWD (a symlink)", *session(link1, real1, pwd=link1)))
        real2, link2 = os.path.join(t, "real two"), os.path.join(t, "link two")
        os.makedirs(real2, exist_ok=True)
        os.symlink(real2, link2)
        cases.append(("folder named from the resolved path", *session(real2, real2, pwd=link2)))

        deep = os.path.join(t, *(["long folder name"] * 14))
        cases.append(("path over 200 characters (hashed name)", *session(deep, deep)))
        cases.append(("CLAUDE_CODE_PROJECT_DIR_NAME names the folder",
                      *session(None, os.path.join(t, "renamed"), folder_name="custom-name",
                               CLAUDE_CODE_PROJECT_DIR_NAME="custom-name")))
        glob_root = os.path.join(t, "cfg [x]")
        cases.append(("config dir with glob characters in its name",
                      *session(os.path.join(t, "globbed"), os.path.join(t, "globbed"), root=glob_root)))
        got, _ = session(os.path.join(t, "none"), os.path.join(t, "none"), make_folder=False)
        cases.append(("no matching folder prints nothing", got, ""))

        root = os.path.join(t, "config")
        two = os.path.join(t, "two sessions")
        os.makedirs(two, exist_ok=True)
        folder = os.path.join(root, "projects", slug(two))
        os.makedirs(folder, exist_ok=True)
        mine, other = os.path.join(folder, "aaaa-mine.jsonl"), os.path.join(folder, "bbbb-other.jsonl")
        Path(mine).write_text("{}\n")
        Path(other).write_text("{}\n")
        os.utime(mine, (1_000_000, 1_000_000))  # the other session wrote later
        cases.append(("current session wins over a newer one",
                      run(code, two, root, CLAUDE_CODE_SESSION_ID="aaaa-mine"), mine))
        cases.append(("no session id falls back to the newest", run(code, two, root), other))
        cases.append(("unknown session id falls back to the newest",
                      run(code, two, root, CLAUDE_CODE_SESSION_ID="zzzz"), other))

        for label, got, want in cases:
            checks += 1
            if got != want:
                failures.append(f"lookup, {label}: got {got!r}, want {want!r}")

    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        return 1
    print(f"PASS  {checks} checks · naming matches Claude Code's function on {len(pinned)} "
          f"pinned paths · lookup finds folders from both accent forms, $PWD and the resolved "
          f"path, hashed names, the dir-name override and a glob-character root · the current "
          f"session's file wins, else the newest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
