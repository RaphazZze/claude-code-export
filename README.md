# claude-code-export

Convert Claude Code `.jsonl` conversation files into clean, readable Markdown.

## What it does

Claude Code stores every conversation as a raw `.jsonl` file. This tool parses those files and produces a Markdown export suitable for archiving, sharing, or reviewing past sessions.

### What's kept

- All user and assistant text messages
- File creations (`+`) and modifications (`~`)
- Sub-agent dispatches (description, model, and full prompt)
- MCP tool calls (server, method, and all input parameters)
- User question prompts and answers
- Image and file attachment notices
- IDE selection context

### What's stripped

- Tool call outputs and results
- Thinking blocks
- Internal system tags (`<system-reminder>`, `<local-command-caveat>`, `<ide_opened_file>`)
- Sidechain messages
- File history snapshots

### Sanitization

- **Absolute paths** are converted to relative paths (project root, `~/.claude/`, `~/`)
- **Relative paths** with file extensions are wrapped in backticks for readability
- A sanitization note is included at the top of every export

## Usage

```bash
# Single file
python3 claudecode_export.py <file.jsonl>

# With user name and 24-hour time
python3 claudecode_export.py <file.jsonl> --name Dario --time 24

# Batch export to a specific directory
python3 claudecode_export.py *.jsonl -o exports/ --name Dario

# Full help
python3 claudecode_export.py --help
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-n`, `--name` | Label for user messages | `User` |
| `-t`, `--time` | Time format: `12` or `24` | `12` |
| `-o`, `--output` | Output directory | Current dir |

### Output filename

Files are named `conversation_export_<date>_<time>_<id>.md` where:
- `<date>_<time>` is when the conversation started (local timezone)
- `<id>` is the first 5 characters of the session UUID (to avoid collisions)

Example: `conversation_export_2026-03-24_1807_ffaab.md`

## Where are the .jsonl files?

Claude Code stores conversations per project at:

```
~/.claude/projects/<project-folder>/*.jsonl
```

The `<project-folder>` name is derived from the working directory path with `/` replaced by `-`.

## Requirements

- Python 3.9+ (uses `zoneinfo`)
- No external dependencies
