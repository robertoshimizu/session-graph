"""
File-watcher daemon that monitors ~/.claude/projects/ for new/modified .jsonl files.
On detection, logs the file and records a watermark. Actual ingestion deferred to Sprint 4.

Usage:
    python -m daemon.sync_daemon [--watch-dir PATH] [--watermark-file PATH]
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_daemon")

DEFAULT_WATCH_DIR = os.path.expanduser("~/.claude/projects/")
DEFAULT_WATERMARK_FILE = os.path.join(os.path.dirname(__file__), "watermarks.json")


class WatermarkStore:
    """Tracks last-processed timestamps per source file."""

    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def update(self, source_path: str):
        ts = datetime.now(timezone.utc).isoformat()
        self.data[source_path] = ts
        self._save()
        return ts

    def get(self, source_path: str) -> str | None:
        return self.data.get(source_path)


class JsonlHandler(FileSystemEventHandler):
    """Watches for .jsonl file creation and modification."""

    def __init__(self, watermarks: WatermarkStore):
        super().__init__()
        self.watermarks = watermarks

    def _handle(self, event):
        if event.is_directory:
            return
        src = event.src_path
        if not src.endswith(".jsonl"):
            return
        ts = self.watermarks.update(src)
        logger.info("Detected %s: %s (watermark: %s)", event.event_type, src, ts)

    def on_created(self, event):
        self._handle(event)

    def on_modified(self, event):
        self._handle(event)


def main():
    parser = argparse.ArgumentParser(description="Watch for new Claude Code sessions")
    parser.add_argument(
        "--watch-dir",
        default=DEFAULT_WATCH_DIR,
        help=f"Directory to watch (default: {DEFAULT_WATCH_DIR})",
    )
    parser.add_argument(
        "--watermark-file",
        default=DEFAULT_WATERMARK_FILE,
        help=f"Watermark JSON file (default: {DEFAULT_WATERMARK_FILE})",
    )
    args = parser.parse_args()

    watch_dir = os.path.expanduser(args.watch_dir)
    if not os.path.isdir(watch_dir):
        logger.error("Watch directory does not exist: %s", watch_dir)
        sys.exit(1)

    watermarks = WatermarkStore(args.watermark_file)
    handler = JsonlHandler(watermarks)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=True)

    shutdown = False

    def _shutdown(signum, frame):
        nonlocal shutdown
        if not shutdown:
            shutdown = True
            logger.info("Shutting down (signal %d)...", signum)
            observer.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Watching %s for .jsonl changes", watch_dir)
    observer.start()

    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
    logger.info("Daemon stopped.")


if __name__ == "__main__":
    main()
