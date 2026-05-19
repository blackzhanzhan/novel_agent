#!/usr/bin/env python
"""Generate local style diagnostics for a novel workspace."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.style_diagnostics import generate_style_diagnostics  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Chinese style diagnostics for a local novel workspace.")
    parser.add_argument("--book-dir", required=True, type=Path)
    parser.add_argument("--source-count", type=int, default=8)
    parser.add_argument("--draft-file", default="chapter_draft.md")
    parser.add_argument("--draft-chapters", default="")
    parser.add_argument("--fingerprint-output", type=Path, default=Path(".runtime/style_fingerprint.md"))
    parser.add_argument("--review-output", type=Path, default=Path(".runtime/style_review.md"))
    parser.add_argument(
        "--constraints-output",
        type=Path,
        default=Path(".runtime/style_constraints_for_continuation.md"),
    )
    return parser.parse_args()


def write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Wrote {path}")


def main() -> int:
    args = parse_args()
    result = generate_style_diagnostics(
        book_dir=args.book_dir.resolve(),
        source_count=args.source_count,
        draft_file=args.draft_file,
        draft_chapters=args.draft_chapters,
    )
    outputs = result["outputs"]
    write_output(args.fingerprint_output, outputs["style_fingerprint.md"])
    write_output(args.review_output, outputs["style_review.md"])
    write_output(args.constraints_output, outputs["style_constraints_for_continuation.md"])
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
