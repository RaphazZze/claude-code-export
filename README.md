# claude-code-export

Convert Claude Code `.jsonl` session files into clean, readable Markdown.

## What it does

Claude Code stores every session as a raw `.jsonl` file. This tool parses those files and produces a Markdown export suitable for archiving, sharing, or reviewing past sessions.

### What's kept

- All user and assistant text messages
- Queued messages — text typed while Claude is mid-turn, which the harness
  stores as an attachment rather than a user message
- File creations (`+`) and modifications (`~`)
- Shell commands (`$`) — the one-line description only, never the command
- Sub-agent dispatches (description, agent type and model)
- Skill invocations (name only — marked as `⚙ Skill: <name>`, attributed to
  the assistant, since the assistant is what invokes a skill)
- Slash commands typed by the user (marked as `⌘ Command: /<name>`). `/model`
  additionally names the model it selected — `⌘ Command: /model → Sonnet 5`
- The model that produced the session, on a `**Model:**` header line, and a
  `◆ Model changed to <id>` marker at any point the model actually changes
  mid-session. Harness-written lines (`<synthetic>`) are not a model and never
  read as a change
- Background task completions (marked as `⚑ Task notification: <summary>`)
- MCP tool calls (server, method, and all input parameters)
- User question prompts and answers
- Image and file attachment notices (marked as `📎 File attached: <name>`)
- Pasted text, verbatim, without the `<pasted_content>` wrapper the harness
  puts around it
- IDE selection context (marked as `⌖ Selected lines <a> to <b> of <file>`,
  the selected text quoted below)

### What's stripped

- Tool call outputs and results
- Shell command bodies (only the description survives)
- Thinking blocks
- Sub-agent prompts and skill bodies
- Background task result payloads (the summary line is kept)
- Harness-injected messages that arrive with the `user` role — plugin skill
  bodies, workflow resume prompts, image-resize notices
- Internal system tags (`<system-reminder>`, `<local-command-caveat>`, `<ide_opened_file>`),
  and an assistant text block that is nothing but a system reminder
- Sidechain messages
- File history snapshots
- The API request log (`api-request-blob` records), which replays earlier
  messages without timestamps and would otherwise repeat whole turns
- Harness compaction summaries. When context is compacted the harness writes a
  templated digest of the dialogue so far and re-injects it as the continued
  session's first message, under the `user` role. It is not dialogue, so it is
  replaced by a `⇱ Context compacted` marker. `/compact` compacts in place, so
  the conversation it digests is still above it in the same file and the export
  loses nothing; if the digest ever names a *different* session file, the marker
  says so, because then the dialogue really is elsewhere
- Command output, except the model name from `/model`

### Sanitization

- **Absolute paths** are converted to relative paths (project root, `~/.claude/`, `~/`)
- **Relative paths** with file extensions are wrapped in backticks for readability.
  Fenced code blocks, inline code spans, markdown links and images, and bare URLs
  are left untouched, so an existing `[label](path/file.md)` link stays intact
- **Cloud-storage paths** are reduced to a provider placeholder so they reveal
  nothing about the machine's setup — iCloud app containers become
  `<Appname>/`, Google Drive, OneDrive and Dropbox mounts become
  `<Google Drive>/` and so on. The placeholder and its path are wrapped as one
  span: `` `<Obsidian>/Notes/index.md` ``
- A sanitization note is included at the top of every export

## Install as a Claude Code skill

This repo ships with a [SKILL.md](SKILL.md) so you can invoke it from inside Claude Code as `/export-session`. Symlink the repo into your skills directory:

```bash
ln -s "$(pwd)" ~/.claude/skills/export-session
```

Then run `/export-session` from any Claude Code session.

## Usage

```bash
# Single file
python3 claudecode_export.py <file.jsonl>

# With user name and 24-hour time
python3 claudecode_export.py <file.jsonl> --name Boris --time 24

# Batch export to a specific directory
python3 claudecode_export.py *.jsonl -o exports/ --name Boris

# Custom assistant label (e.g. for a named agent)
python3 claudecode_export.py *.jsonl --name Raph --assistant-name KAIZEN

# Full help
python3 claudecode_export.py --help
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-n`, `--name` | Label for user messages | `User` |
| `-A`, `--assistant-name` | Label for assistant messages | `Claude` |
| `-t`, `--time` | Time format: `12` or `24` | `12` |
| `-o`, `--output` | Output directory | `claude-session-exports/` (created under the current dir) |
| `-c`, `--count-only` | Print message counts without exporting | off |
| `-a`, `--include-sub-agents` | Include `agent-*.jsonl` sub-agent files | off |

### Sub-agent sessions

Claude Code's Task tool creates sub-agent session files named `agent-*.jsonl` inside `<session-uuid>/subagents/`. These are skipped by default — they typically contain only internal tool-use traces without user messages, and produce empty exports. Pass `--include-sub-agents` / `-a` if you want them (e.g., for debugging or audit).

### Output filename

Files are named `session_export_<date>_<time>_<id>.md` where:
- `<date>_<time>` is when the session started (local timezone)
- `<id>` is the first 5 characters of the session UUID (to avoid collisions)

Example: `session_export_2026-03-24_1807_ffaab.md`

## Tests

```bash
python3 tests/test_export.py            # run
python3 tests/test_export.py --update   # regenerate the expected export
```

`tests/every_record_class.jsonl` holds one record of every class this tool has
ever mishandled, and `tests/every_record_class.expected.md` is the Markdown it
should produce. The test diffs the two, checks that `--count-only` agrees with the
export, and asserts that none of the content the fixture deliberately carries
— command bodies, injected skill bodies, task payloads, sidechain messages,
absolute home paths — reaches the output.

The timezone is pinned and `Path.home()` is patched, so the expected export is
byte-identical on any machine. `--update` rewrites it; since it is checked in,
that lands as a reviewable diff rather than a silent pass.

## Where are the .jsonl files?

Claude Code stores sessions per project at:

```
~/.claude/projects/<project-folder>/*.jsonl
```

The `<project-folder>` name is derived from the working directory path with `/` replaced by `-`.

## Requirements

- Python 3.9+ (uses `zoneinfo`)
- No external dependencies
