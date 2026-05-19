#!/usr/bin/env python
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "novel_git_server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from pipelines.rolling_chapter import (  # noqa: E402
    build_chapter_context_pack,
    build_human_unlock_artifact,
    build_rolling_plan,
    build_review_packet,
    build_style_repair_delta,
    summarize_style_gate_artifact,
)
from utils.book_storage import get_book_dir, get_storage_root, validate_book_id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan a rolling chapter-production batch without writing prose.")
    parser.add_argument("--book-id", required=True, help="Book workspace id.")
    parser.add_argument("--storage-root", default="", help="Optional storage root override.")
    parser.add_argument("--batch-size", type=int, default=3, help="Requested rolling batch size.")
    parser.add_argument("--review-gate-open", action="store_true", default=True, help="Treat human review gate as open.")
    parser.add_argument("--review-gate-closed", action="store_false", dest="review_gate_open", help="Block production on review.")
    parser.add_argument(
        "--quality-gate-style",
        default="",
        help="Optional generate_style_diagnostics JSON artifact. Style failures are recorded as advisory evidence and do not lock the scheduler.",
    )
    parser.add_argument(
        "--quality-gate-reason",
        default="",
        help="Optional stop reason when --quality-gate-style locks the planner.",
    )
    parser.add_argument("--repair-before-style", default="", help="Optional pre-repair style diagnostics JSON.")
    parser.add_argument("--repair-after-style", default="", help="Optional post-repair style diagnostics JSON.")
    parser.add_argument("--repair-delta-output", default="", help="Optional JSON artifact path for repair delta scoring.")
    parser.add_argument("--review-packet-output", default="", help="Optional JSON artifact path for a no-prose review packet.")
    parser.add_argument("--chapter-context-pack-output", default="", help="Optional JSON artifact path for a no-prose chapter context pack.")
    parser.add_argument("--human-unlock", default="", help="Optional bound human unlock artifact JSON.")
    parser.add_argument("--human-unlock-output", default="", help="Optional path to write a bound human unlock artifact.")
    parser.add_argument("--human-actor", default="", help="Human actor name/id for --human-unlock-output.")
    parser.add_argument("--human-unlock-reason", default="", help="Human reason for --human-unlock-output.")
    parser.add_argument("--human-unlock-decision", default="approve_override", help="Human decision for --human-unlock-output.")
    parser.add_argument("--output", default="", help="Optional JSON artifact path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    parser.add_argument("--unicode", action="store_true", help="Emit raw Unicode instead of ASCII-safe JSON escapes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    book_id = validate_book_id(args.book_id)
    storage_root = Path(args.storage_root).resolve() if args.storage_root else Path(get_storage_root(str(SERVER_ROOT))).resolve()
    book_dir = Path(get_book_dir(book_id, str(storage_root)))
    quality_gate_locked = False
    quality_gate_summary = {}
    quality_gate_source = ""
    if args.quality_gate_style:
        style_path = Path(args.quality_gate_style)
        if not style_path.is_absolute():
            style_path = ROOT / style_path
        quality_gate_source = str(style_path)
        style_artifact = json.loads(style_path.read_text(encoding="utf-8"))
        quality_gate_summary = summarize_style_gate_artifact(style_artifact)
        quality_gate_locked = False
    repair_delta = {}
    if args.repair_before_style or args.repair_after_style:
        if not (args.repair_before_style and args.repair_after_style):
            raise SystemExit("--repair-before-style and --repair-after-style must be provided together")
        before_path = Path(args.repair_before_style)
        after_path = Path(args.repair_after_style)
        if not before_path.is_absolute():
            before_path = ROOT / before_path
        if not after_path.is_absolute():
            after_path = ROOT / after_path
        repair_delta = build_style_repair_delta(
            json.loads(before_path.read_text(encoding="utf-8")),
            json.loads(after_path.read_text(encoding="utf-8")),
        )
        repair_delta["before_source"] = str(before_path)
        repair_delta["after_source"] = str(after_path)
        if args.repair_delta_output:
            delta_out = Path(args.repair_delta_output)
            if not delta_out.is_absolute():
                delta_out = ROOT / delta_out
            delta_out.parent.mkdir(parents=True, exist_ok=True)
            delta_out.write_text(json.dumps(repair_delta, ensure_ascii=args.unicode is False, indent=2 if args.pretty else None) + "\n", encoding="utf-8")
    human_unlock = {}
    if args.human_unlock:
        human_unlock_path = Path(args.human_unlock)
        if not human_unlock_path.is_absolute():
            human_unlock_path = ROOT / human_unlock_path
        human_unlock = json.loads(human_unlock_path.read_text(encoding="utf-8"))
    plan = build_rolling_plan(
        book_id=book_id,
        book_dir=book_dir,
        batch_size=args.batch_size,
        review_gate_open=args.review_gate_open,
        quality_gate_locked=quality_gate_locked,
        quality_gate_reason=args.quality_gate_reason or ("style_advisory" if quality_gate_source else "quality_gate_locked"),
        quality_gate_source=quality_gate_source,
        quality_gate_summary=quality_gate_summary,
        human_unlock=human_unlock,
    )
    if repair_delta:
        plan["repair_delta"] = repair_delta
    plan["generated_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    if args.human_unlock_output:
        if not args.human_actor.strip():
            raise SystemExit("--human-actor is required with --human-unlock-output")
        if not args.human_unlock_reason.strip():
            raise SystemExit("--human-unlock-reason is required with --human-unlock-output")
        unlock_out = Path(args.human_unlock_output)
        if not unlock_out.is_absolute():
            unlock_out = ROOT / unlock_out
        unlock_artifact = build_human_unlock_artifact(
            plan=plan,
            human_actor=args.human_actor.strip(),
            reason=args.human_unlock_reason.strip(),
            decision=args.human_unlock_decision,
            generated_at=plan["generated_at"],
            artifact_id=unlock_out.stem,
        )
        unlock_out.parent.mkdir(parents=True, exist_ok=True)
        unlock_out.write_text(
            json.dumps(unlock_artifact, ensure_ascii=args.unicode is False, indent=2 if args.pretty else None) + "\n",
            encoding="utf-8",
        )
    if args.review_packet_output:
        packet_out = Path(args.review_packet_output)
        if not packet_out.is_absolute():
            packet_out = ROOT / packet_out
        packet = build_review_packet(
            plan=plan,
            repair_delta=repair_delta,
            book_repo={
                "path": str(book_dir),
                "branch": "draft/sandbox",
            },
            generated_at=plan["generated_at"],
            packet_id=packet_out.stem,
        )
        packet_out.parent.mkdir(parents=True, exist_ok=True)
        packet_out.write_text(
            json.dumps(packet, ensure_ascii=args.unicode is False, indent=2 if args.pretty else None) + "\n",
            encoding="utf-8",
        )
    if args.chapter_context_pack_output:
        pack_out = Path(args.chapter_context_pack_output)
        if not pack_out.is_absolute():
            pack_out = ROOT / pack_out
        pack = build_chapter_context_pack(
            plan=plan,
            book_dir=book_dir,
            repair_delta=repair_delta,
            generated_at=plan["generated_at"],
            pack_id=pack_out.stem,
            gate_artifacts=[
                args.quality_gate_style,
                args.repair_before_style,
                args.repair_after_style,
                args.repair_delta_output,
            ],
        )
        pack_out.parent.mkdir(parents=True, exist_ok=True)
        pack_out.write_text(
            json.dumps(pack, ensure_ascii=args.unicode is False, indent=2 if args.pretty else None) + "\n",
            encoding="utf-8",
        )
    text = json.dumps(plan, ensure_ascii=args.unicode is False, indent=2 if args.pretty else None)
    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
