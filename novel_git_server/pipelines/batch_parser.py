"""Parse summary.md Batch Archive sections into structured batch dicts."""

import re
from pathlib import Path
from typing import Optional

_BATCH_HEADING_RE = re.compile(r"^## Batch Archive:\s*(.+?)\s*$")
_RANGE_RE = re.compile(r"CH(\d+)\s*[-–—]\s*(\d+)")


def parse_summary_batches(summary_path: str | Path) -> list[dict]:
    """Parse summary.md into a list of batch dicts.

    Each batch dict contains:
        title:        "Batch Archive: CH1-50"
        chapter_start: 1 (0 for non-standard headings without CH range)
        chapter_end:   50 (0 for non-standard headings without CH range)
        start_line:    16  (1-based, inclusive)
        end_line:      100 (1-based, inclusive)
        text:          raw markdown text of the batch
    """
    summary_path = Path(summary_path)
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.md not found: {summary_path}")
    content = summary_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError("summary.md is empty")

    lines = content.split("\n")

    # Scan for batch heading line numbers (1-based)
    headings: list[tuple[int, str, int, int]] = []  # (line_no, title, ch_start, ch_end)
    for i, line in enumerate(lines, start=1):
        m = _BATCH_HEADING_RE.match(line)
        if m:
            title = m.group(1).strip()
            rm = _RANGE_RE.search(title)
            ch_start = int(rm.group(1)) if rm else 0
            ch_end = int(rm.group(2)) if rm else 0
            headings.append((i, f"Batch Archive: {title}", ch_start, ch_end))

    if not headings:
        raise ValueError("No '## Batch Archive: CH...' headings found in summary.md")

    batches: list[dict] = []
    for idx, (line_no, title, ch_start, ch_end) in enumerate(headings):
        # end_line is the line before the next heading, or EOF
        if idx + 1 < len(headings):
            end_line = headings[idx + 1][0] - 1
        else:
            end_line = len(lines)

        # Extract text (line numbers are 1-based, list is 0-based)
        text_lines = lines[line_no - 1 : end_line]
        # Strip trailing blank lines
        while text_lines and not text_lines[-1].strip():
            text_lines.pop()
        text = "\n".join(text_lines)

        batches.append(
            {
                "title": title,
                "chapter_start": ch_start,
                "chapter_end": ch_end,
                "start_line": line_no,
                "end_line": line_no - 1 + len(text_lines),
                "text": text,
            }
        )

    return batches


def get_completed_batch_titles(book_dir: str | Path) -> set[str]:
    """Scan git log for batch init commits and return completed batch titles."""
    import git as gitmod

    repo = gitmod.Repo(str(book_dir))
    completed: set[str] = set()
    for commit in repo.iter_commits(max_count=200):
        msg = commit.message.strip()
        if msg.startswith("batch init:"):
            completed.add(msg[len("batch init:") :].strip())
    return completed


def filter_remaining_batches(
    batches: list[dict], completed_titles: set[str]
) -> list[dict]:
    """Return batches not yet completed, preserving order."""
    return [b for b in batches if b["title"] not in completed_titles]
