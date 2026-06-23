"""Replay the Discord gateway cascade logs incrementally.

Simulates real-time log growth so the repi worker can pick up new bytes via
watchers as the incident unfolds. Writes to a separate live/ directory so the
static eval logs stay untouched.

Usage:
    # 1. Start the API and worker in separate terminals:
    #      uv run repi serve
    #      uv run python -m repi.worker

    # 2. Register watchers (once) — copy the printed curl commands:
    uv run python eval/dataset_4_discord_gateway_cascade/simulate_live.py --register

    # 3. Replay logs (in a third terminal):
    uv run python eval/dataset_4_discord_gateway_cascade/simulate_live.py

    # Options:
    #   --live-dir /tmp/repi-discord   Output directory (default: eval/.../live/)
    #   --batch-seconds 60             How many log-time seconds per batch (default: 60)
    #   --sleep 5                      Real seconds to sleep between batches (default: 5)
    #   --register                     Print curl commands for watcher registration then exit
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOGS_DIR = Path(__file__).parent / "logs"
DEFAULT_LIVE_DIR = Path(__file__).parent / "live"

SERVICES = [
    ("read-states-svc.log", "read-states-svc"),
    ("gateway.log", "gateway"),
    ("message-svc.log", "message-svc"),
    ("presence-svc.log", "presence-svc"),
    ("cdn-edge.log", "cdn-edge"),
]

API_BASE = os.environ.get("REPI_API", "http://localhost:8000")


def _parse_ts(line: str) -> Optional[datetime]:
    """Extract the leading ISO8601 timestamp from a log line."""
    try:
        ts_str = line.split(" ")[0]
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_lines(filename: str) -> list[tuple[datetime, str]]:
    path = LOGS_DIR / filename
    if not path.exists():
        print(f"  [warn] {path} not found — skipping", file=sys.stderr)
        return []
    entries: list[tuple[datetime, str]] = []
    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        if not line:
            continue
        ts = _parse_ts(line)
        if ts:
            entries.append((ts, line))
    return entries


def _print_watcher_commands(live_dir: Path) -> None:
    print("\nRegister these watchers via the repi API:\n")
    for filename, service in SERVICES:
        target = live_dir / filename
        print(
            f"curl -s -X POST {API_BASE}/watchers \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"service_name\":\"{service}\",\"watch_path\":\"{target}\",\"env\":\"live-demo\"}}'"
        )
        print()
    print(f"Live log files will be written to: {live_dir}\n")


def run_replay(live_dir: Path, batch_seconds: int, sleep_secs: float) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)

    # Collect all entries from all services, sort by timestamp.
    all_entries: list[tuple[datetime, str, Path]] = []
    for filename, _ in SERVICES:
        target = live_dir / filename
        # Truncate (or create) the live file so watcher offset resets.
        target.write_text("")
        for ts, line in _load_lines(filename):
            all_entries.append((ts, line, target))

    all_entries.sort(key=lambda x: x[0])

    if not all_entries:
        print("No log entries found — check LOGS_DIR.", file=sys.stderr)
        sys.exit(1)

    start_ts = all_entries[0][0]
    end_ts = all_entries[-1][0]
    total_log_seconds = (end_ts - start_ts).total_seconds()
    batches = int(total_log_seconds / batch_seconds) + 1

    print(
        f"Replaying {len(all_entries)} log lines across {len(SERVICES)} services\n"
        f"  Log window : {start_ts.isoformat()} → {end_ts.isoformat()}\n"
        f"  Batch size : {batch_seconds}s of log-time per batch\n"
        f"  Sleep      : {sleep_secs}s between batches\n"
        f"  Batches    : ~{batches}\n"
        f"  Live dir   : {live_dir}\n"
        f"  Total wall : ~{int(batches * sleep_secs)}s\n"
    )
    print("─" * 60)

    bucket_start = start_ts
    written_total = 0
    batch_num = 0

    while True:
        bucket_end_ts = bucket_start.timestamp() + batch_seconds
        batch: list[tuple[datetime, str, Path]] = []
        remaining: list[tuple[datetime, str, Path]] = []

        for entry in all_entries:
            if entry[0].timestamp() < bucket_end_ts:
                batch.append(entry)
            else:
                remaining.append(entry)

        if batch:
            batch_num += 1
            # Group by file to do one append per file per batch.
            by_file: dict[Path, list[str]] = {}
            for ts, line, target in batch:
                by_file.setdefault(target, []).append(line)

            now_wall = datetime.now(timezone.utc).strftime("%H:%M:%S")
            log_time = batch[0][0].strftime("%H:%M:%S")
            print(f"[{now_wall}] batch {batch_num:3d}  log-time {log_time}  +{len(batch):3d} lines", end="")

            for target, lines in by_file.items():
                with open(target, "a") as f:
                    f.write("\n".join(lines) + "\n")
                print(f"  {target.stem}({len(lines)})", end="")

            print()
            written_total += len(batch)
            all_entries = remaining

        if not all_entries:
            print(f"\nDone — wrote {written_total} lines total.")
            break

        bucket_start = datetime.fromtimestamp(bucket_end_ts, tz=timezone.utc)
        time.sleep(sleep_secs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Discord cascade logs for live watcher demo")
    parser.add_argument("--live-dir", default=str(DEFAULT_LIVE_DIR), help="Output directory for live log files")
    parser.add_argument("--batch-seconds", type=int, default=60, help="Log-time seconds per batch (default 60)")
    parser.add_argument("--sleep", type=float, default=5.0, help="Real seconds between batches (default 5)")
    parser.add_argument("--register", action="store_true", help="Print watcher curl commands and exit")
    args = parser.parse_args()

    live_dir = Path(args.live_dir).resolve()

    if args.register:
        _print_watcher_commands(live_dir)
        return

    run_replay(live_dir, batch_seconds=args.batch_seconds, sleep_secs=args.sleep)


if __name__ == "__main__":
    main()
