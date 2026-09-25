"""Run this repository's offline tests with only its own runtime modules."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    env = os.environ.copy()
    dependency_paths = [path for path in sys.path if Path(path).name in ("site-packages", "dist-packages")]
    env["PYTHONPATH"] = os.pathsep.join([*(str(ROOT / part) for part in ("tests", "scripts", ".")), *dependency_paths])
    env["SHORT_VIDEO_DEV_OVERLAY"] = env["PYTHONPATH"]
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    args = sys.argv[1:] or ["discover", "-s", "tests", "-t", ".", "-v"]
    raise SystemExit(subprocess.call([sys.executable, "-B", "-m", "unittest", *args], cwd=ROOT, env=env))
