"""Wrapper run by the Windows Scheduled Task instead of advance_week.py
directly. Keeps the local machine and the GitHub repo (which the cloud
Claude-turn routine reads/writes) in sync around each tick:

    git pull  ->  advance_week.py  ->  git add/commit/push

Uses the repo root as the git working directory; city_sim/ is where the
actual simulation code and state.json live.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CITY_SIM = ROOT / "city_sim"


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result


def main() -> None:
    run(["git", "pull", "--rebase"], cwd=ROOT)

    tick = subprocess.run([sys.executable, "advance_week.py"], cwd=CITY_SIM)

    run(["git", "add", "-A"], cwd=ROOT)
    status = run(["git", "status", "--porcelain"], cwd=ROOT)
    if status.stdout.strip():
        run(["git", "commit", "-m", "Daily tick"], cwd=ROOT)
        run(["git", "push"], cwd=ROOT)
    else:
        print("Nothing changed, skipping commit/push.")

    sys.exit(tick.returncode)


if __name__ == "__main__":
    main()
