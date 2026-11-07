#!/usr/bin/env python3
"""Re-run the photo indexer for every image already in the gallery bucket.

Invokes the indexer Lambda once per original under the photos prefix. Deploy
the current photo_index function first: it writes a 300x200 JPEG under
`_thumbs/`, a 1280px JPEG under `_lightbox/`, and records both on the photo
index. Those derived objects are skipped here. When Printful already has a
product for an object key, the indexer records its variants and does not
create another product.

Bucket, prefix, indexer name, index key, and region come from `terraform output`
in main/. See gallery_config.py for the optional PHOTO_* overrides.

Usage:
  python3 scripts/reprocess_photos.py
"""

import json
import os
import subprocess
import sys
import tempfile
from urllib.parse import quote

import gallery_config

BUCKET = ""
PREFIX = ""
FUNCTION = ""
REGION = ""
INDEX_KEY = ""
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}
INDEX_NAME = "_index.json"


def main():
    global BUCKET, PREFIX, FUNCTION, REGION, INDEX_KEY
    config = gallery_config.settings()
    BUCKET = config.bucket
    PREFIX = config.prefix
    FUNCTION = config.index_function
    REGION = config.region
    INDEX_KEY = config.index_key
    prefix = PREFIX
    keys = [key for key in list_keys(prefix) if is_image(key)]
    if not keys:
        print(f"No images under s3://{BUCKET}/{prefix}", file=sys.stderr)
        return 1
    print(f"Reprocessing {len(keys)} image(s) with {FUNCTION}")
    failed = []
    for index, key in enumerate(keys, start=1):
        print(f"[{index}/{len(keys)}] {key}")
        error = invoke(key)
        if error:
            failed.append((key, error))
            print(f"  failed: {error}", file=sys.stderr)
    if failed:
        print(f"{len(failed)} of {len(keys)} failed", file=sys.stderr)
        return 1
    print("Done")
    return 0


def list_keys(prefix):
    keys = []
    token = None
    while True:
        command = [
            "aws",
            "s3api",
            "list-objects-v2",
            "--region",
            REGION,
            "--bucket",
            BUCKET,
            "--prefix",
            prefix,
            "--output",
            "json",
        ]
        if token:
            command.extend(["--continuation-token", token])
        page = json.loads(aws(command))
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if key and not key.endswith("/"):
                keys.append(key)
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
        if not token:
            break
    return keys


def is_image(key):
    name = key.rsplit("/", 1)[-1]
    if key == INDEX_KEY or name == INDEX_NAME:
        return False
    relative = key[len(PREFIX) :] if PREFIX and key.startswith(PREFIX) else key
    if relative.startswith("_thumbs/") or relative.startswith("_lightbox/"):
        return False
    _, ext = os.path.splitext(name.lower())
    return ext in IMAGE_EXTS


def invoke(key):
    # S3 delivers the object key URL-encoded. The indexer decodes it.
    event = {
        "Records": [
            {
                "eventName": "ObjectCreated:Put",
                "s3": {"object": {"key": quote(key, safe="/")}},
            }
        ]
    }
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as payload, tempfile.NamedTemporaryFile(
        "w+", encoding="utf-8"
    ) as response:
        json.dump(event, payload)
        payload.flush()
        result = subprocess.run(
            [
                "aws",
                "lambda",
                "invoke",
                "--region",
                REGION,
                "--function-name",
                FUNCTION,
                "--invocation-type",
                "RequestResponse",
                "--cli-binary-format",
                "raw-in-base64-out",
                "--cli-read-timeout",
                "210",
                "--payload",
                f"file://{payload.name}",
                response.name,
            ],
            capture_output=True,
            text=True,
        )
        response.seek(0)
        body = response.read()
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return detail or f"aws lambda invoke exited {result.returncode}"
        meta = json.loads(result.stdout or "{}")
        if meta.get("FunctionError"):
            return body.strip() or meta["FunctionError"]
        return None


def aws(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(detail or f"{command[0]} exited {result.returncode}")
    return result.stdout


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
