"""Standalone command bootstrap. No package installation or credential copying."""
import json
import os
import subprocess
import sys
from pathlib import Path


def bootstrap_hermes(source_arg):
    os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    if sys.version_info < (3, 11):
        runtime = json.loads(subprocess.run(["hermes", "--print-runtime-command"], check=True, capture_output=True, text=True, timeout=30).stdout)
        os.execv(runtime[0], [runtime[0], str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
    source = Path(source_arg).expanduser().resolve(strict=True)
    if not (source / "hermes_bootstrap.py").is_file():
        raise ValueError("Not an installed Hermes source checkout")
    sys.path.insert(0, str(source))
    import hermes_bootstrap  # noqa: F401
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from hermes_constants import get_hermes_home
    home = get_hermes_home().resolve(strict=True)
    scratch = home / "cache" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return home, scratch
