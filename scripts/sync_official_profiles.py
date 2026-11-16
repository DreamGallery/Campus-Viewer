"""Manual entry point for the same official profile sync used by Docker."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    raise SystemExit(subprocess.call(
        [sys.executable, '-m', 'campus_story_index.official_profiles', *sys.argv[1:]],
        cwd=Path(__file__).resolve().parents[1]))
