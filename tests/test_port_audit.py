"""The port audit runs as a test, so a dropped control fails CI rather than
waiting for the operator to notice it missing."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_streamlit_control_still_exists_in_the_react_app():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "port_audit.py")],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    missing = [l.strip() for l in out.stdout.splitlines() if l.startswith("  MISS")]
    assert not missing, "controls lost in the port:\n" + "\n".join(missing)
    assert "ALL PRESENT" in out.stdout
