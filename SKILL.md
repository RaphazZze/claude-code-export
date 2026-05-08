---
name: export-session
description: Export a Claude Code session from its raw `.jsonl` file into a clean, readable Markdown file. Strips tool calls, tool results, code execution output, and internal thinking blocks — keeping only the human-readable dialogue. Messages are labelled with the speaker's name and time (e.g. `### ❯ User · 10:25 AM`). The date is shown once at the top and again only when it changes, for multi-day sessions. File and image attachments from the user are noted inline (e.g. `_[Image attached: image/jpeg]_`).
---

# export-session

## Instructions

**Step 1 — Ask for the user's name.**
Use the AskUserQuestion tool with a single question: "What's your name? (used to label your messages in the export)" and make it optional/skippable. If the user provides a name, use it in place of `"User"` as the label throughout the export. If they skip or leave it blank, default to `"User"`.

**Step 2 — Resolve the `.jsonl` input file.**

- If a path is provided as an argument, use it as the path to the `.jsonl` file.
- Otherwise, auto-detect: convert the current working directory path to the project folder name (replace `/` with `-`, keeping the leading `-`), then pick the most recently modified `.jsonl` file inside `~/.claude/projects/<project-folder>/`.

Use a short Bash snippet to resolve the path if auto-detecting:

```bash
ls -t ~/.claude/projects/$(pwd | sed 's|/|-|g')/*.jsonl 2>/dev/null | head -1
```

**Step 3 — Run the export using the Bash tool.**

Use the `claudecode_export.py` script that lives next to this SKILL.md (in the skill's base directory):

```bash
python3 <skill_dir>/claudecode_export.py <jsonl_path> --name "<name>" -o .
```

Replace `<skill_dir>` with the skill's base directory (provided to you at invocation time), `<jsonl_path>` with the resolved path from Step 2, and `<name>` with the name from Step 1 (or `User` if skipped).

The script will print the output filename on success. Report it to the user.
