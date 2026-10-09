#!/usr/bin/env python3
"""Create-only installation. Never changes config.yaml or activates the engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

PLUGIN_FILES = ("__init__.py", "plugin.yaml", "contracts.py", "store.py", "observer.py", "backend.py", "engine.py")


def refuse_symlinks(path: Path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink destinations are refused")


def install(home: Path, source: Path | None = None) -> dict:
    home = Path(home).expanduser().absolute()
    refuse_symlinks(home)
    if not home.is_dir():
        raise ValueError("The explicitly selected Hermes home must already exist")
    source = source or Path(__file__).resolve().parents[1] / "observational"
    target = home / "plugins" / "observational"
    refuse_symlinks(target)
    if target.exists():
        raise FileExistsError("Destination exists; refusing to overwrite")
    blobs = {}
    for name in PLUGIN_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Incomplete or unsafe source package")
        blobs[name] = path.read_bytes()
    for folder in (home / "plugins",):
        refuse_symlinks(folder)
        folder.mkdir(mode=0o700, exist_ok=True)
    target.mkdir(mode=0o700)
    try:
        for name, body in blobs.items():
            fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
        manifest = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in PLUGIN_FILES}
        if manifest != {name: hashlib.sha256(body).hexdigest() for name, body in blobs.items()}:
            raise RuntimeError("Installed byte verification failed")
        return {"installed": str(target), "activated": False, "config_changed": False, "sha256": manifest}
    except BaseException:
        # Only the create-only directory owned by this invocation is removed.
        shutil.rmtree(target)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.home), indent=2))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "installed": False, "activated": False}))
        raise SystemExit(1)
