#!/usr/bin/env python3
"""Load photo-gallery deployment settings from Terraform state.

Reads root outputs from main/. Set any of the environment variables below
to override that one field without changing state:

  PHOTO_BUCKET             site_bucket_name
  PHOTO_PREFIX             photo_library_prefix
  PHOTO_INDEX_FUNCTION     photo_index_function_name
  PHOTO_INDEX_KEY          photo_index_key
  PHOTO_REGION             aws_region

Run with --shell to print sh-compatible assignments for upload-image.sh.
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parents[3] / "main"
OUTPUTS = {
    "bucket": "site_bucket_name",
    "prefix": "photo_library_prefix",
    "index_function": "photo_index_function_name",
    "index_key": "photo_index_key",
}


class Gallery:
    def __init__(self, bucket, prefix, region, index_function, index_key):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.index_function = index_function
        self.index_key = index_key


def settings(env=None, outputs=None):
    env = os.environ if env is None else env
    bucket = env.get("PHOTO_BUCKET") or ""
    prefix = env.get("PHOTO_PREFIX") or ""
    index_function = env.get("PHOTO_INDEX_FUNCTION") or ""
    index_key = env.get("PHOTO_INDEX_KEY") or ""
    region = env.get("PHOTO_REGION") or ""
    if not (bucket and prefix and index_function and index_key and region):
        data = outputs if outputs is not None else terraform_outputs()
        bucket = bucket or _value(data, OUTPUTS["bucket"])
        prefix = prefix or _value(data, OUTPUTS["prefix"])
        index_function = index_function or _value(data, OUTPUTS["index_function"])
        index_key = index_key or _value(data, OUTPUTS["index_key"])
        region = region or _value(data, "aws_region")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return Gallery(bucket, prefix, region, index_function, index_key)


def terraform_outputs():
    result = subprocess.run(
        ["terraform", f"-chdir={MAIN_DIR}", "output", "-json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(detail or "terraform output failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as err:
        raise SystemExit(f"terraform output -json returned invalid JSON: {err}") from err


def shell_assignments(gallery):
    fields = {
        "PHOTO_BUCKET": gallery.bucket,
        "PHOTO_PREFIX": gallery.prefix,
        "PHOTO_INDEX_FUNCTION": gallery.index_function,
        "PHOTO_INDEX_KEY": gallery.index_key,
        "PHOTO_REGION": gallery.region,
    }
    return "\n".join(f"{name}={shlex.quote(value)}" for name, value in fields.items())


def _value(outputs, name):
    try:
        return outputs[name]["value"]
    except KeyError:
        raise SystemExit(
            f"terraform output {name} is missing. Apply main/ so the photo gallery outputs are in state."
        ) from None


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in ("--shell",):
        raise SystemExit("usage: gallery_config.py [--shell]")
    gallery = settings()
    if "--shell" in sys.argv[1:]:
        print(shell_assignments(gallery))
        return
    print(
        f"bucket={gallery.bucket} prefix={gallery.prefix} "
        f"region={gallery.region} index={gallery.index_function} key={gallery.index_key}"
    )


if __name__ == "__main__":
    main()
