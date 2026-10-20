#!/usr/bin/env python3
"""Record an actual terminal command as an asciicast v2 file.

Example:
  python tools/record_command.py --out runs/recovery.cast -- bash tools/recovery_demo.sh

No commands are simulated. Do not run commands that print credentials.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide the command to record after --")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    master, slave = pty.openpty()
    start = time.monotonic()
    with args.out.open("w") as recording:
        recording.write(json.dumps({"version": 2, "width": 110, "height": 30,
                                    "timestamp": int(time.time()), "title": "Actual pipeline recovery demonstration"}) + "\n")
        recording.flush()
        child = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        try:
            while True:
                readable, _, _ = select.select([master], [], [], 0.2)
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    recording.write(json.dumps([round(time.monotonic() - start, 6), "o", text]) + "\n")
                    recording.flush()
                elif child.poll() is not None:
                    break
        finally:
            os.close(master)
            if child.poll() is None:
                child.terminate()
            code = child.wait()
    print(f"Recorded actual process output: {args.out}; exit={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
