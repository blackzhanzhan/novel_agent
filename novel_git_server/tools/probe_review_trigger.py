#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe /api/world/deduce_stream and print review-trigger related SSE events.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--book-id", default="", help="book_id to send")
    parser.add_argument("--book-name", default="", help="book_name to send when book_id is unavailable")
    parser.add_argument("--active-file", required=True, help="Active file, e.g. arc_outline.md")
    parser.add_argument("--intent", required=True, help="User intent")
    parser.add_argument("--file-type", default="", help="Optional file_type override")
    return parser.parse_args()


def iter_sse_events(response):
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if not line.strip():
            if data_lines:
                raw_data = "\n".join(data_lines)
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    data = {"raw": raw_data}
                yield event_name, data
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())


def main() -> int:
    args = parse_args()
    payload = {
        "intent": args.intent,
        "active_file": args.active_file,
    }
    if args.book_id:
        payload["book_id"] = args.book_id
    if args.book_name:
        payload["book_name"] = args.book_name
    if args.file_type:
        payload["file_type"] = args.file_type

    req = urllib.request.Request(
        url=f"{args.base_url.rstrip('/')}/api/world/deduce_stream",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            interesting = {"ack", "stage", "preview", "reasoning", "draft_ready", "done", "error"}
            for event_name, data in iter_sse_events(response):
                if event_name not in interesting:
                    continue
                print(json.dumps({"event": event_name, "data": data}, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"status": "http_error", "code": exc.code, "body": body}, ensure_ascii=False))
        return 1
    except Exception as exc:  # pragma: no cover - probe convenience script
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
