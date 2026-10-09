#!/usr/bin/env python3
"""Create and byte-verify an allowlisted source handoff, without private state."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(output):
    members = [ROOT / "README.md", ROOT / ".gitignore"]
    for folder, patterns in (("observational", ("*.py", "plugin.yaml")), ("tools", ("*.py",)), ("tests", ("test_*.py",)), ("examples", ("*.json",)), ("docs", ("**/*.md", "**/*.json"))):
        for pattern in patterns:
            members.extend((ROOT / folder).glob(pattern))
    files = sorted(set(members))
    payloads = {}
    for path in files:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Unsafe package member")
        relative = path.relative_to(ROOT).as_posix()
        if any(part in {"..", ".git", "__pycache__", "node_modules"} for part in Path(relative).parts):
            raise ValueError("Disallowed package path")
        payloads[relative] = path.read_bytes()
    manifest = {"format": 1, "name": "hermes-observational-memory", "version": "0.1.0", "private_runtime_data_included": False, "sha256": {name: hashlib.sha256(body).hexdigest() for name, body in payloads.items()}}
    payloads["MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = "hermes-observational-memory/"
    with zipfile.ZipFile(output, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in payloads.items():
            info = zipfile.ZipInfo(prefix + name, date_time=(2026, 10, 9, 0, 0, 0))
            info.external_attr = 0o100600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != {prefix + n for n in payloads}:
            raise RuntimeError("Archive integrity/membership verification failed")
        for name, body in payloads.items():
            if archive.read(prefix + name) != body:
                raise RuntimeError("Archive byte verification failed")
    return {"archive": str(output.resolve()), "members": len(payloads), "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.output), indent=2))
