import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def run_help(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "tele.py"), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_help_and_commands():
    result = run_help("--help")
    assert "export-members" in result.stdout
    result = run_help("export-members", "--help")
    assert "--group" in result.stdout


def test_no_real_credentials_in_source():
    for path in ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "27927250" not in text
        assert "f8c49a5954c79df6853d417f55575120" not in text
