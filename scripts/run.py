"""Run the standalone Qianchuan script workbench."""
from pathlib import Path
import runpy
import sys

def main():
    skill_root = Path(__file__).resolve().parents[1]
    source = skill_root / "scripts"
    if not (source / "script_cli.py").is_file():
        raise SystemExit("Skill runtime scripts are missing; install the complete package.")
    sys.path.insert(0, str(source))
    runpy.run_module("script_cli", run_name="__main__", init_globals={"_ALLOWED_COMMANDS": {
        "describe-acquire", "preview-acquire", "acquire", "continue-acquire", "import-run",
        "render-summary", "prepare-analysis", "publish-analysis",
        "analysis-page", "analysis-status", "render-analysis-report",
        "prepare-generation", "publish-generation", "prepare-rewrite", "publish-rewrite", "verify",
    }})

if __name__ == "__main__":
    main()
