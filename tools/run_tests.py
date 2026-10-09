#!/usr/bin/env python3
"""Run against the installed Hermes runtime, never the live profile state."""
import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"

# macOS's /usr/bin/python3 may be too old even to import Hermes bootstrap.
# Resolve the installed interpreter through the supported CLI, never guess it.
if sys.version_info < (3, 11):
    import json
    import subprocess
    runtime = json.loads(subprocess.run(["hermes", "--print-runtime-command"], check=True, capture_output=True, text=True, timeout=30).stdout)
    os.execv(runtime[0], [runtime[0], str(Path(__file__).resolve()), *sys.argv[1:]])

parser = argparse.ArgumentParser()
parser.add_argument("--hermes-repo", required=True)
parser.add_argument("--pattern", default="test_*.py")
args = parser.parse_args()
source = Path(args.hermes_repo).expanduser().resolve(strict=True)
if not (source / "hermes_bootstrap.py").is_file():
    parser.error("Not a Hermes source checkout")
# Activate existing dependencies before redirecting application state. A fresh
# HERMES_HOME before bootstrap means a fresh dependency installation in this build.
sys.path.insert(0, str(source))
import hermes_bootstrap  # noqa: E402,F401
from hermes_constants import get_hermes_home
scratch = (get_hermes_home() / "cache" / "scratch").resolve()
scratch.mkdir(parents=True, exist_ok=True)
# tempfile may have cached macOS's /var symlink before bootstrap exported TMPDIR.
# Keep every fixture in the explicitly owned scratch boundary instead.
os.environ["TMPDIR"] = str(scratch)
tempfile.tempdir = str(scratch)
os.environ["OM_TEST_HOME"] = tempfile.mkdtemp(prefix="om-tests-", dir=scratch)
os.environ["HERMES_HOME"] = os.environ["OM_TEST_HOME"]
os.environ["HERMES_DISABLE_MCP"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest  # noqa: E402

if __name__ == "__main__":
    import shutil
    root = Path(__file__).resolve().parents[1]
    try:
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    finally:
        shutil.rmtree(os.environ["OM_TEST_HOME"], ignore_errors=False)
