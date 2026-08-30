#!/usr/bin/env python3
"""Verify a built PyInstaller executable actually launches a real window
and doesn't crash on startup. Not a pytest test (needs a display/Xvfb and
a prebuilt exe) — used by packaging/README.md's verification steps.

Usage: python3 scripts/_pyinstaller_exe_smoke.py dist/Sweep
"""

import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: _pyinstaller_exe_smoke.py <path-to-executable>")
        return 2
    exe = sys.argv[1]

    proc = subprocess.Popen([exe])
    time.sleep(3)  # give Tk time to come up and any import errors time to surface
    still_running = proc.poll() is None
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    if not still_running:
        print(f"FAILED: {exe} exited on its own within 3 seconds (crash on startup)")
        return 1
    print(f"OK: {exe} launched and was still running after 3 seconds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
