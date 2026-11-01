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
   characters, and say nothing on stderr. When nothing matches it prints no
   path, and its stderr line names the case: no projects folder, an unreadable
   one (or an unreadable config dir above it), an unreadable or empty session
   folder, or no matching folder. The unreadable cases are skipped under root.
3. Session choice: with `CLAUDE_CODE_SESSION_ID` set it prints that session's
   file even when another session wrote later; unset, or naming no file in the
   folder, it falls back to the newest.
"""
import contextlib, json, os, re, subprocess, sys, tempfile, unicodedata as u
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


def run(code, cwd, root, pwd=None, stderr=False, **env_extra):
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    env.update(CLAUDE_CONFIG_DIR=root, PWD=pwd or cwd, **env_extra)
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=cwd, env=env,
                         capture_output=True, text=True, check=True)
    return (out.stdout.strip(), out.stderr.strip()) if stderr else out.stdout.strip()


@contextlib.contextmanager
def mode(path, bits):
    os.chmod(path, bits)
    try:
        yield
    finally:
        os.chmod(path, 0o755)


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
            return (run(code, real_dir, root, pwd, stderr=True, **env_extra),
                    (os.path.join(folder, "s.jsonl"), ""))

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
        root = os.path.join(t, "config")
        none = os.path.join(t, "none")
        os.makedirs(none, exist_ok=True)
        def empty(label, cfg, reason, cwd=none):
            cases.append((label, run(code, cwd, cfg, stderr=True), ("", f"auto-detect: {reason}")))

        empty("no match", root, f"no session folder for this directory in {root}/projects")
        missing = os.path.join(t, "no such config")
        empty("no projects folder", missing, f"no projects folder at {missing}/projects")
        filecfg = os.path.join(t, "file config")
        os.makedirs(filecfg, exist_ok=True)
        Path(filecfg, "projects").write_text("")
        empty("projects is a file, not a folder", filecfg, f"no projects folder at {filecfg}/projects")
        hollow = os.path.join(t, "hollow")
        os.makedirs(hollow, exist_ok=True)
        os.makedirs(os.path.join(root, "projects", slug(hollow)), exist_ok=True)
        empty("session folder with no .jsonl", root,
              f"no .jsonl in {root}/projects/{slug(hollow)}", cwd=hollow)
        if os.geteuid() != 0:
            locked = os.path.join(t, "locked config")
            projects = os.path.join(locked, "projects")
            os.makedirs(projects)
            with mode(projects, 0):
                empty("unreadable projects folder (mode 000)", locked, f"cannot read {projects}")
            with mode(projects, 0o311):
                empty("projects folder searchable but not readable (mode 311)", locked,
                      f"cannot read {projects}")
            with mode(locked, 0):
                empty("unreadable config dir above it", locked, f"cannot read {projects}")
            shut = os.path.join(t, "shut")
            os.makedirs(shut, exist_ok=True)
            shut_folder = os.path.join(root, "projects", slug(shut))
            os.makedirs(shut_folder, exist_ok=True)
            with mode(shut_folder, 0):
                empty("unreadable session folder", root, f"cannot read {shut_folder}", cwd=shut)
            both = os.path.join(t, u.normalize("NFC", "Café three"))
            os.makedirs(both, exist_ok=True)
            f_nfc = os.path.join(root, "projects", slug(u.normalize("NFC", both)))
            f_nfd = os.path.join(root, "projects", slug(u.normalize("NFD", both)))
            os.makedirs(f_nfc, exist_ok=True)
            os.makedirs(f_nfd, exist_ok=True)
            with mode(f_nfc, 0):
                empty("two folders, one unreadable and one empty: the unreadable one is named",
                      root, f"cannot read {f_nfc}", cwd=both)
                with mode(f_nfd, 0):
                    empty("two unreadable folders: the first in sorted order is named",
                          root, f"cannot read {min(f_nfc, f_nfd)}", cwd=both)
            skipped = False
        else:
            skipped = True
            print("SKIP  unreadable-folder cases (running as root)")

        two = os.path.join(t, "two sessions")
        os.makedirs(two, exist_ok=True)
        folder = os.path.join(root, "projects", slug(two))
        os.makedirs(folder, exist_ok=True)
        mine, other = os.path.join(folder, "aaaa-mine.jsonl"), os.path.join(folder, "bbbb-other.jsonl")
        Path(mine).write_text("{}\n")
        Path(other).write_text("{}\n")
        os.utime(mine, (1_000_000, 1_000_000))  # the other session wrote later
        cases.append(("current session wins over a newer one",
                      run(code, two, root, stderr=True, CLAUDE_CODE_SESSION_ID="aaaa-mine"), (mine, "")))
        cases.append(("no session id falls back to the newest",
                      run(code, two, root, stderr=True), (other, "")))
        cases.append(("unknown session id falls back to the newest",
                      run(code, two, root, stderr=True, CLAUDE_CODE_SESSION_ID="zzzz"), (other, "")))

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
          f"path, hashed names, the dir-name override and a glob-character root · an empty result "
          f"names its cause{' (unreadable cases skipped)' if skipped else ''} · the current "
          f"session's file wins, else the newest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
