#!/usr/bin/env python3
"""Unpack the vendored Pillow wheel into a Lambda layer directory.

Prints {"dir": "<layer root>"} for Terraform's external data source.
The layer root contains python/PIL, which is the layout Lambda expects.
"""

import fcntl
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ROOT.parent / "files"
LAYER = FILES / "pillow-layer"
STAMP = FILES / "pillow-layer.sha256"
LOCK = FILES / "pillow-layer.lock"


def main():
    wheels = sorted((ROOT / "vendor").glob("pillow-*-cp312-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one Pillow wheel, found {len(wheels)}")
    wheel = wheels[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    FILES.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = (
            STAMP.is_file()
            and STAMP.read_text().strip() == digest
            and (LAYER / "python" / "PIL" / "__init__.py").is_file()
        )
        if not ready:
            tmp = FILES / f"pillow-layer.{os.getpid()}"
            if tmp.exists():
                shutil.rmtree(tmp)
            python_dir = tmp / "python"
            python_dir.mkdir(parents=True)
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(python_dir)
            for cache in python_dir.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)
            if LAYER.exists():
                shutil.rmtree(LAYER)
            tmp.rename(LAYER)
            STAMP.write_text(digest + "\n")
    print(json.dumps({"dir": str(LAYER)}))


if __name__ == "__main__":
    main()
