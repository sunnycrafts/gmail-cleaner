"""
CI-lite: the one command that must pass before any build or commit that
matters. Wraps the existing offline backend tests and the headless UI smoke
test, and exits non-zero if either fails — turning "I ran it and it looked
right" into an actual pass/fail gate.

Usage:  python run_checks.py
"""
import subprocess
import sys
import glob
import os

STEPS = [
    ("Backend unit tests", [sys.executable, "test_backend.py"]),
    ("UI smoke test",      [sys.executable, "smoke_ui.py"]),
]


def main():
    failures = []
    for name, cmd in STEPS:
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failures.append(name)
            print(f"*** {name} FAILED (exit {result.returncode})")

    # smoke_ui.py leaves screenshots behind for manual review; clean them
    # up automatically so they don't accumulate as untracked git noise.
    for png in glob.glob("smoke_*.png"):
        try:
            os.remove(png)
        except OSError:
            pass

    print("\n" + "=" * 64)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
