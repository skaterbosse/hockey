#!/usr/bin/env python3
"""Run an existing Python script with opt-in HTTP counting enabled."""
import runpy
import sys
from pathlib import Path
import httpTelemetry  # installs opt-in, best-effort counters

if __name__ == '__main__':
    script = Path(sys.argv[1]).resolve()
    sys.argv = [str(script)] + sys.argv[2:]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')
