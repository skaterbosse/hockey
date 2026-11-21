#!/usr/bin/env python3
"""Run an unchanged command and append its elapsed time to a run-local JSONL file."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stage', required=True)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command:
        p.error('missing command')
    # Preserve the script and its arguments; add HTTP telemetry only to Python scripts.
    if os.environ.get("STATS_METRICS_LOG") and len(command) > 1 and command[1].endswith(".py") and Path(command[0]).name.startswith("python"):
        command = [command[0], str(Path(__file__).with_name("httpTelemetryRunner.py")), *command[1:]]
    started = time.monotonic()
    try:
        result = subprocess.run(command, check=False)
        code = result.returncode
    except OSError as exc:
        print(f'Failed to start {a.stage}: {exc}', file=sys.stderr)
        code = 127
    seconds = round(time.monotonic() - started, 3)
    path = os.environ.get('STATS_METRICS_LOG')
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'kind': 'stage', 'stage': a.stage, 'durationSeconds': seconds,
                                'exitCode': code, 'finishedAt': datetime.now(timezone.utc).isoformat()}) + '\n')
    print(f'METRIC stage={a.stage} durationSeconds={seconds} exitCode={code}', flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
