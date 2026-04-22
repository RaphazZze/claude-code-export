#!/usr/bin/env python3
"""
claude-code-export — Convert Claude Code .jsonl session files to clean Markdown.

Strips tool calls, tool results, thinking blocks, and code execution output.
Keeps only human-readable dialogue. Replaces absolute paths with relative ones.

Usage:
    python3 claudecode_export.py <file.jsonl> [file2.jsonl ...]
    python3 claudecode_export.py *.jsonl
    python3 claudecode_export.py <file.jsonl> -o /output/dir
    python3 claudecode_export.py <file.jsonl> --name "Boris" --time 24
"""

import json, os, sys, re, argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path


# ── Timezone ────────────────────────────────────────────────────────────────

def detect_local_tz():
    """Detect local timezone from /etc/localtime symlink, fall back to UTC."""
    try:
        link = os.readlink("/etc/localtime")
        tz_name = link.split("zoneinfo/")[-1]
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")

LOCAL_TZ = detect_local_tz()


# ── Helpers ─────────────────────────────────────────────────────────────────

SKILL_PREFIX = "Base directory for this skill: "


def skill_name_from_injection(text):
    """If text is a Claude Code skill injection, return the skill name. Else None."""
    if not isinstance(text, str) or not text.startswith(SKILL_PREFIX):
        return None
    first_line = text.split('\n', 1)[0]
    path = first_line[len(SKILL_PREFIX):].strip()
    return Path(path).name or None


def clean(text):
    """Remove internal Claude Code tags from user messages."""
    text = re.sub(r'<local-command-caveat>.*?</local-command-caveat>', '', text, flags=re.DOTALL)
    text = re.sub(r'<ide_opened_file>.*?</ide_opened_file>', '', text, flags=re.DOTALL)
    text = re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL)
    return text.strip()


def fix_table_spacing(text):
    """Ensure a blank line before markdown table rows that follow non-table lines."""
    lines = text.split('\n')
    result = []
    for line in lines:
        if line.startswith('|') and result and result[-1].strip() and not result[-1].lstrip().startswith('|'):
            result.append('')
        result.append(line)
    return '\n'.join(result)


def make_rel(project_root):
    """Return a closure that converts absolute paths to relative ones."""
    home_claude = Path.home() / '.claude'

    def rel(file_path):
        p = Path(file_path)
        if project_root:
            try:
                return str(p.relative_to(project_root))
            except ValueError:
                pass
        try:
            p.relative_to(home_claude)
            return str(Path(p.parent.name) / p.name)
        except ValueError:
            pass
        return p.name

    return rel


def parse_timestamp(ts_raw, time_format):
    """Parse ISO timestamp string, return (date_str, time_str)."""
    try:
        dt = datetime.strptime(ts_raw, '%Y-%m-%dT%H:%M:%S.%fZ') \
                      .replace(tzinfo=timezone.utc) \
                      .astimezone(LOCAL_TZ)
        date_str = dt.strftime('%Y-%m-%d')
        if time_format == "24":
            time_str = dt.strftime('%H:%M')
        else:
            time_str = dt.strftime('%I:%M %p').lstrip('0')
        return date_str, time_str
    except Exception:
        return '', ''


# ── Core conversion ────────────────────────────────────────────────────────

def convert(jsonl_path, user_label, time_format):
    """Parse a .jsonl session file and return (markdown_string, message_count, start_datetime)."""

    # First pass: find project root and first timestamp from first non-snapshot record
    project_root = None
    first_timestamp = None
    with open(jsonl_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get('type') == 'file-history-snapshot':
                continue
            if not project_root:
                cwd_val = obj.get('cwd', '')
                if cwd_val:
                    project_root = Path(cwd_val)
            if not first_timestamp:
                ts_raw = obj.get('timestamp', '')
                if ts_raw:
                    try:
                        first_timestamp = datetime.strptime(ts_raw, '%Y-%m-%dT%H:%M:%S.%fZ') \
                                                  .replace(tzinfo=timezone.utc) \
                                                  .astimezone(LOCAL_TZ)
                    except Exception:
                        pass
            if project_root and first_timestamp:
                break

    rel = make_rel(project_root)

    # Second pass: extract messages
    messages = []
    pending_questions = {}

    with open(jsonl_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue

            if obj.get('type') == 'file-history-snapshot':
                continue
            if obj.get('isSidechain'):
                continue

            msg = obj.get('message', {})
            role = msg.get('role')
            content = msg.get('content', '')
            date_str, time_str = parse_timestamp(obj.get('timestamp', ''), time_format)

            if role == 'user':
                # Claude Code skill injections arrive as user messages whose first
                # text block starts with "Base directory for this skill: <path>".
                # Replace the full skill body with a one-line marker.
                if isinstance(content, str):
                    skill_text = content
                elif isinstance(content, list):
                    skill_text = next(
                        (b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text'),
                        ''
                    )
                else:
                    skill_text = ''
                skill_name = skill_name_from_injection(skill_text)
                if skill_name:
                    messages.append((
                        'user',
                        f"> `⚙` Skill: **{skill_name}**",
                        date_str, time_str
                    ))
                    continue

                if isinstance(content, str):
                    text = clean(content)
                    if text:
                        messages.append(('user', text, date_str, time_str))
                elif isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get('type')
                        if btype == 'text':
                            t = clean(block.get('text', ''))
                            if t:
                                text_parts.append(t)
                        elif btype == 'image':
                            media = block.get('source', {}).get('media_type', 'image')
                            text_parts.append(f"_[Image attached: {media}]_")
                        elif btype == 'document':
                            title = block.get('title') or block.get('source', {}).get('filename') or 'document'
                            text_parts.append(f"_[File attached: {title}]_")
                        elif btype == 'tool_result':
                            tid = block.get('tool_use_id')
                            if tid and tid in pending_questions:
                                raw = block.get('content', '')
                                if isinstance(raw, str):
                                    matches = re.findall(r'"([^"]+)"="([^"]+)"', raw)
                                    answered = {q: a for q, a in matches}
                                    for qinfo in pending_questions[tid]:
                                        answer = answered.get(qinfo['question'], raw.strip())
                                        text_parts.append(f"_{qinfo['question']}_\n→ **{answer}**")
                                del pending_questions[tid]
                    if text_parts:
                        messages.append(('user', '\n\n'.join(text_parts), date_str, time_str))

            elif role == 'assistant':
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get('type')
                        if btype == 'text':
                            t = fix_table_spacing(block.get('text', '').strip())
                            if t:
                                text_parts.append(t)
                        elif btype == 'tool_use':
                            name = block.get('name', '')
                            inp = block.get('input', {})
                            tid = block.get('id', '')
                            if name == 'Write':
                                fp = inp.get('file_path', '')
                                if fp:
                                    text_parts.append(f"> `+` Created `{rel(fp)}`")
                            elif name == 'Edit':
                                fp = inp.get('file_path', '')
                                if fp:
                                    text_parts.append(f"> `~` Modified `{rel(fp)}`")
                            elif name == 'Agent':
                                desc = inp.get('description', '')
                                model = inp.get('model', '')
                                header = f"> `▶` Sub-agent"
                                if desc:
                                    header += f": {desc}"
                                if model:
                                    header += f" ({model})"
                                text_parts.append(header)
                            elif name.startswith('mcp__'):
                                # MCP tool call — show tool name and inputs
                                # mcp__glean_default__chat → Glean: chat
                                parts = name.split('__')
                                server = parts[1] if len(parts) > 1 else ''
                                method = parts[-1] if len(parts) > 2 else name
                                label = server.replace('_default', '').replace('_', ' ').title()
                                header = f"> `⚡` {label}: {method}"
                                # Show all input params as nested blockquote
                                param_lines = []
                                for k, v in inp.items():
                                    param_lines.append(f"> > **{k}:** {v}")
                                if param_lines:
                                    header += "\n" + '\n'.join(param_lines)
                                text_parts.append(header)
                            elif name == 'AskUserQuestion':
                                qs = inp.get('questions', [])
                                if isinstance(qs, str):
                                    try:
                                        qs = json.loads(qs)
                                    except Exception:
                                        qs = []
                                qinfos = []
                                for q in qs:
                                    if not isinstance(q, dict):
                                        continue
                                    opts = [o.get('label', '') if isinstance(o, dict) else str(o) for o in q.get('options', [])]
                                    qinfos.append({'question': q.get('question', ''), 'options': opts})
                                if tid and qinfos:
                                    pending_questions[tid] = qinfos
                    if text_parts:
                        messages.append(('assistant', '\n\n'.join(text_parts), date_str, time_str))
                elif isinstance(content, str):
                    text = fix_table_spacing(content.strip())
                    if text:
                        messages.append(('assistant', text, date_str, time_str))

    # Deduplicate consecutive identical messages
    deduped = []
    prev = None
    for m in messages:
        key = (m[0], m[1])
        if key != prev:
            deduped.append(m)
            prev = key

    # Build Markdown
    lines = []
    lines.append(f"# Claude Code Session Export")
    lines.append(f"**Source:** `{jsonl_path.name}`  ")
    lines.append(f"**Exported:** {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("> **Sanitization note:** This export has been cleaned for readability. "
                 "Absolute paths were converted to relative paths. "
                 "Tool call outputs, thinking blocks, and internal system tags were removed. "
                 "File creations and modifications are noted inline.")
    lines.append("")
    lines.append("---")
    lines.append("")

    current_date = None
    for role, text, date_str, time_str in deduped:
        if date_str and date_str != current_date:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            lines.append(f"### [{dt.strftime('%B %-d, %Y')}]")
            lines.append("")
            current_date = date_str
        label = f"### ❯ {user_label}" if role == "user" else "### ❯ Claude"
        ts_str = f" · {time_str}" if time_str else ""
        lines.append(f"{label}{ts_str}")
        lines.append("")
        lines.append(text)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Final pass: scrub absolute paths and wrap all paths in backticks
    output = '\n'.join(lines)

    # Regex for the tail of a path: segments (allowing spaces within names) ending with .ext
    # e.g. "Client Success/Accounts/client_index.md" or "memory/file.md"
    PTAIL = r'(?:[\w.-]+(?:\s[\w.-]+)*/)*[\w.-]+(?:\s[\w.-]+)*\.\w+'

    # 1. Absolute paths rooted at project dir → backticked relative paths
    if project_root:
        root_esc = re.escape(str(project_root) + '/')
        output = re.sub(
            r'(?<!`)' + root_esc + r'(' + PTAIL + r')(?!`)',
            r'`\1`', output
        )
        # Clean up any remaining bare project root references (dirs, no extension)
        output = output.replace(str(project_root) + '/', '')
        output = output.replace(str(project_root), '')

    # 2. Paths under ~/.claude → backticked ~/...
    home_claude = str(Path.home() / '.claude')
    hc_esc = re.escape(home_claude + '/')
    output = re.sub(
        r'(?<!`)' + hc_esc + r'(' + PTAIL + r')(?!`)',
        r'`~/.claude/\1`', output
    )
    output = output.replace(home_claude + '/', '~/.claude/')
    output = output.replace(home_claude, '~/.claude')

    # 3. Paths under home dir → backticked ~/...
    home_dir = str(Path.home())
    hd_esc = re.escape(home_dir + '/')
    output = re.sub(
        r'(?<!`)' + hd_esc + r'(' + PTAIL + r')(?!`)',
        r'`~/\1`', output
    )
    output = output.replace(home_dir + '/', '~/')
    output = output.replace(home_dir, '~')

    # 3b. Normalize cloud storage / iCloud app paths that reveal Mac setup
    #     iCloud app vaults: ~/Library/Mobile Documents/iCloud~vendor~app/Documents/
    #     Extract the app name from the bundle-style segment (last ~-delimited token).
    output = re.sub(
        r'~/Library/Mobile Documents/iCloud~[^/~]+~([^/]+)/Documents/',
        lambda m: f'<{m.group(1).capitalize()}>/',
        output,
    )
    # Anything else under ~/Library/Mobile Documents/ (other iCloud containers)
    output = output.replace('~/Library/Mobile Documents/', '<iCloud>/')
    # Google Drive — newer mount point (~/Library/CloudStorage/GoogleDrive-account/My Drive/)
    output = re.sub(
        r'~/Library/CloudStorage/GoogleDrive-[^/]+/My Drive/',
        '<Google Drive>/',
        output,
    )
    # Google Drive — legacy ~/My Drive/ mount
    output = output.replace('~/My Drive/', '<Google Drive>/')
    # OneDrive
    output = re.sub(
        r'~/Library/CloudStorage/OneDrive[^/]*/',
        '<OneDrive>/',
        output,
    )
    # Dropbox
    output = re.sub(
        r'~/Library/CloudStorage/Dropbox[^/]*/',
        '<Dropbox>/',
        output,
    )

    # 4. Remaining bare relative paths (no spaces — common case)
    output = re.sub(r'(?<!`)(\b[\w.~-]+/[\w./_-]+\.\w+)(?!`)', r'`\1`', output)

    user_count = sum(1 for r, _, _, _ in deduped if r == 'user')
    assistant_count = sum(1 for r, _, _, _ in deduped if r == 'assistant')
    return output, (user_count, assistant_count), first_timestamp


def count_messages(jsonl_path):
    """Quick message count without full conversion — skips Markdown generation."""
    messages = []
    with open(jsonl_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get('type') == 'file-history-snapshot':
                continue
            if obj.get('isSidechain'):
                continue
            msg = obj.get('message', {})
            role = msg.get('role')
            content = msg.get('content', '')
            if role == 'user':
                if isinstance(content, str):
                    text_sig = clean(content)
                elif isinstance(content, list):
                    parts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
                    text_sig = clean('\n'.join(parts))
                else:
                    text_sig = ''
                skill_name = skill_name_from_injection(text_sig)
                if skill_name:
                    text_sig = f"> `⚙` Skill: **{skill_name}**"
                if text_sig:
                    messages.append((role, text_sig))
            elif role == 'assistant':
                if isinstance(content, list):
                    has_visible = any(
                        isinstance(b, dict) and (
                            b.get('type') == 'text' or
                            (b.get('type') == 'tool_use' and b.get('name', '') in ('Write', 'Edit', 'Agent', 'AskUserQuestion') or b.get('name', '').startswith('mcp__'))
                        )
                        for b in content
                    )
                    if has_visible:
                        parts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
                        messages.append((role, '\n'.join(parts).strip()))
                elif isinstance(content, str) and content.strip():
                    messages.append((role, content.strip()))
    # Deduplicate consecutive identical (role, text) pairs — matches convert() logic
    user_count = 0
    assistant_count = 0
    prev = None
    for m in messages:
        if m != prev:
            if m[0] == 'user':
                user_count += 1
            else:
                assistant_count += 1
            prev = m
    return user_count, assistant_count


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert Claude Code .jsonl sessions to Markdown.",
        epilog="Examples:\n"
               "  python3 export_conversation.py session.jsonl\n"
               "  python3 export_conversation.py *.jsonl -o exports/ --name Boris\n"
               "  python3 export_conversation.py *.jsonl --time 24\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="+", help=".jsonl file(s) to convert")
    parser.add_argument("-o", "--output", default=".", help="output directory (default: current dir)")
    parser.add_argument("-n", "--name", default="User", help="label for user messages (default: User)")
    parser.add_argument("-t", "--time", choices=["12", "24"], default="12", help="time format (default: 12)")
    parser.add_argument("-c", "--count-only", action="store_true", help="print message counts without exporting")
    parser.add_argument(
        "-a", "--include-sub-agents",
        action="store_true",
        help="include sub-agent session files (agent-*.jsonl). "
             "By default these are skipped — they are created automatically by "
             "Claude Code's Task tool and typically contain only internal "
             "tool-use traces without user messages.",
    )

    args = parser.parse_args()

    def is_sub_agent_file(path):
        return path.name.startswith("agent-")

    if args.count_only:
        for filepath in args.files:
            jsonl_path = Path(filepath)
            if not jsonl_path.exists() or jsonl_path.suffix != '.jsonl':
                continue
            if is_sub_agent_file(jsonl_path) and not args.include_sub_agents:
                continue
            try:
                user_c, asst_c = count_messages(jsonl_path)
                print(f"{jsonl_path.name}\t{user_c + asst_c}\t({user_c} user, {asst_c} Claude)")
            except Exception as e:
                print(f"{jsonl_path.name}\tERROR: {e}", file=sys.stderr)
        return

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if any .jsonl files matched
    jsonl_files = [f for f in args.files if Path(f).suffix == '.jsonl' and Path(f).exists()]
    if not jsonl_files:
        print("  WARN  No .jsonl files found — check your path or glob pattern.", file=sys.stderr)
        sys.exit(1)

    total_files = 0
    failed = 0
    for filepath in args.files:
        jsonl_path = Path(filepath)
        if not jsonl_path.exists():
            print(f"  SKIP  {filepath} (not found)", file=sys.stderr)
            continue
        if not jsonl_path.suffix == '.jsonl':
            print(f"  SKIP  {filepath} (not a .jsonl file)", file=sys.stderr)
            continue
        if is_sub_agent_file(jsonl_path) and not args.include_sub_agents:
            print(f"  SKIP  {jsonl_path.name} (sub-agent session — pass -a to include)", file=sys.stderr)
            continue

        try:
            md, (user_c, asst_c), start_dt = convert(jsonl_path, args.name, args.time)
            short_id = jsonl_path.stem[:5]
            if start_dt:
                stamp = start_dt.strftime('%Y-%m-%d_%H%M')
            else:
                stamp = jsonl_path.stem
            out_path = out_dir / f"session_export_{stamp}_{short_id}.md"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(md)
            print(f"  OK    {jsonl_path.name} → {out_path.name}  ({user_c + asst_c} messages: {user_c} user, {asst_c} Claude)")
            total_files += 1
        except Exception as e:
            print(f"  FAIL  {jsonl_path.name}: {e}", file=sys.stderr)
            failed += 1

    display_dir = str(out_dir.resolve()).replace(str(Path.home()), '~')
    print(f"\nDone — {total_files} file(s) exported to {display_dir}")
    if failed:
        print(f"  {failed} file(s) failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
