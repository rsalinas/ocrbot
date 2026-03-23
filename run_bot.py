#!/usr/bin/env python3

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
BOT_FILE = PROJECT_DIR / "bot.py"
POLL_SECONDS = float(os.getenv("BOT_AUTO_RELOAD_POLL_SECONDS", "1.0"))
WATCH_EXTENSIONS = {".py"}
IGNORED_DIRS = {".git", ".venv", "__pycache__"}


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for path in PROJECT_DIR.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in WATCH_EXTENSIONS:
            files.append(path)
    return sorted(files)


def snapshot_mtimes() -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    for path in iter_source_files():
        try:
            snapshot[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def start_bot() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    return subprocess.Popen([sys.executable, str(BOT_FILE)], env=env)


def stop_bot(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    process = start_bot()
    known_snapshot = snapshot_mtimes()

    try:
        while True:
            time.sleep(POLL_SECONDS)

            if process.poll() is not None:
                return process.returncode or 0

            current_snapshot = snapshot_mtimes()
            if current_snapshot != known_snapshot:
                stop_bot(process)
                process = start_bot()
                known_snapshot = current_snapshot
    except KeyboardInterrupt:
        stop_bot(process)
        return 0
    finally:
        stop_bot(process)


if __name__ == "__main__":
    raise SystemExit(main())