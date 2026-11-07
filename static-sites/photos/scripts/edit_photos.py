#!/usr/bin/env python3
"""List and edit title, description, and tags on photos already in the gallery.

Reads and writes the same XMP fields as scripts/tag_image.py. Saving an
image uploads it back to the gallery bucket, which reindexes that object.
Bucket, prefix, and region come from Terraform state through gallery_config.py.

Usage:
  python3 scripts/edit_photos.py list
  python3 scripts/edit_photos.py update-text photo.jpg --title "New title"
  python3 scripts/edit_photos.py update-text photo.jpg --description "New text"
  python3 scripts/edit_photos.py update-tags photo.jpg --add night --remove draft
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import gallery_config
import tag_image

LAMBDA_DIR = Path(__file__).resolve().parents[3] / "modules" / "photo-library" / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
import photo_index  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}
INDEX_NAME = "_index.json"


def main(argv=None):
    parser, subcommands = build_parser()
    args = parser.parse_args(argv)
    command = subcommands.choices[args.command]
    if args.command == "update-text" and args.title is None and args.description is None:
        command.error("pass --title, --description, or both")
    if args.command == "update-tags":
        add = clean_tags(args.add)
        remove = clean_tags(args.remove)
        if not add and not remove:
            command.error("pass at least one --add or --remove")
    config = gallery_config.settings()
    if args.command == "list":
        return list_photos(config)
    keys = image_keys(config)
    key = resolve_key(args.filename, keys, config)
    if args.command == "update-text":
        return update_photo(config, key, lambda fields: apply_text(fields, args.title, args.description))
    return update_photo(config, key, lambda fields: apply_tags(fields, add, remove))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("list", help="List gallery images with title, description, and tags")

    text = subcommands.add_parser("update-text", help="Replace the title, the description, or both")
    text.add_argument("filename", help="Image filename under the photo prefix")
    text.add_argument("--title", help="New dc:title. Omit to leave the title unchanged")
    text.add_argument("--description", help="New dc:description. Omit to leave the description unchanged")

    tags = subcommands.add_parser("update-tags", help="Add or remove dc:subject tags")
    tags.add_argument("filename", help="Image filename under the photo prefix")
    tags.add_argument("--add", action="append", default=[], metavar="TAG", help="Tag to add. Repeat for more than one")
    tags.add_argument("--remove", action="append", default=[], metavar="TAG", help="Tag to remove. Repeat for more than one")
    return parser, subcommands


def list_photos(config):
    keys = image_keys(config)
    if not keys:
        print(f"No images under s3://{config.bucket}/{config.prefix}")
        return 0
    blocks = []
    for key in keys:
        blocks.append(format_photo(relative_name(key, config), stored_metadata(config, key)))
    print("\n\n".join(blocks))
    return 0


def update_photo(config, key, mutate):
    original = get_object(config, key)
    current = read_metadata(original)
    fields = mutate(current)
    if fields != current:
        updated = tag_image.embed_metadata(original, fields["title"], fields["description"], fields["tags"])
        if updated != original:
            put_object(config, key, updated)
    print(format_photo(relative_name(key, config), fields))
    return 0


def apply_text(fields, title, description):
    updated = copy_fields(fields)
    if title is not None:
        updated["title"] = title.strip()
    if description is not None:
        updated["description"] = description.strip()
    return updated


def apply_tags(fields, add, remove):
    original = []
    seen = set()
    for tag in fields["tags"]:
        if tag not in seen:
            seen.add(tag)
            original.append(tag)
    remove_set = set(remove)
    updated = [tag for tag in original if tag not in remove_set]
    present = set(updated)
    for tag in add:
        # Adding a tag that was already on the photo is a no-op, so a tag
        # named in both --add and --remove stays off when it was already there.
        if tag in seen or tag in present:
            continue
        updated.append(tag)
        present.add(tag)
    return {"title": fields["title"], "description": fields["description"], "tags": updated}


def clean_tags(values):
    return [tag.strip() for tag in values if tag and tag.strip()]


def copy_fields(fields):
    return {
        "title": fields["title"],
        "description": fields["description"],
        "tags": list(fields["tags"]),
    }


def read_metadata(data):
    return fields_from_parsed(photo_index.extract_metadata(data))


def stored_metadata(config, key):
    # The indexer reads the first 256KB, then the tail of PNG and WebP files
    # whose XMP was written at the end.
    header, total = get_range(config, key, f"bytes=0-{photo_index.HEADER_BYTES - 1}")
    tail = b""
    if photo_index._trailing_metadata_unread(header, total):
        tail, _ = get_range(config, key, f"bytes=-{photo_index.TAIL_BYTES}")
    return metadata_from_ranges(header, total, tail)


def metadata_from_ranges(header, total, tail=b""):
    parsed = photo_index.extract_metadata(header)
    if tail and photo_index._trailing_metadata_unread(header, total):
        photo_index._merge(parsed, photo_index._xmp_in_bytes(tail))
    return fields_from_parsed(parsed)


def fields_from_parsed(parsed):
    tags = []
    for tag in parsed.get("tags") or []:
        text = str(tag).strip()
        if text:
            tags.append(text)
    return {
        "title": parsed.get("title") or "",
        "description": parsed.get("description") or "",
        "tags": tags,
    }


def format_photo(name, fields):
    tags = ", ".join(fields["tags"])
    return f"{name}\n  title: {fields['title']}\n  description: {fields['description']}\n  tags: {tags}"


def image_keys(config):
    keys = []
    token = None
    while True:
        command = [
            "aws",
            "s3api",
            "list-objects-v2",
            "--region",
            config.region,
            "--bucket",
            config.bucket,
            "--prefix",
            config.prefix,
            "--output",
            "json",
        ]
        if token:
            command.extend(["--continuation-token", token])
        page = json.loads(aws(command))
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if is_image(key, config):
                keys.append(key)
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
        if not token:
            break
    keys.sort()
    return keys


def is_image(key, config):
    name = key.rsplit("/", 1)[-1]
    if key == config.index_key or name == INDEX_NAME:
        return False
    relative = relative_name(key, config)
    if relative.startswith("_thumbs/") or relative.startswith("_lightbox/"):
        return False
    _, ext = os.path.splitext(name.lower())
    return ext in IMAGE_EXTS


def relative_name(key, config):
    if config.prefix and key.startswith(config.prefix):
        return key[len(config.prefix) :]
    return key


def resolve_key(filename, keys, config):
    raw = filename.strip()
    marker = f"s3://{config.bucket}/"
    if raw.startswith(marker):
        raw = raw[len(marker) :]
    if config.prefix and raw.startswith(config.prefix):
        raw = raw[len(config.prefix) :]
    relative = raw.lstrip("/")
    if not relative or relative.endswith("/"):
        raise SystemExit(f"expected an image filename, got {filename!r}")
    direct = config.prefix + relative
    if direct in keys:
        return direct
    if "/" in relative:
        raise SystemExit(f"no image named {filename!r} under s3://{config.bucket}/{config.prefix}")
    matches = [key for key in keys if key.rsplit("/", 1)[-1] == relative]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"no image named {filename!r} under s3://{config.bucket}/{config.prefix}")
    found = "\n".join(relative_name(key, config) for key in matches)
    raise SystemExit(f"{filename!r} matches more than one image:\n{found}")


def get_object(config, key):
    data, _ = get_range(config, key, None)
    return data


def get_range(config, key, byte_range):
    with tempfile.NamedTemporaryFile() as body:
        command = [
            "aws",
            "s3api",
            "get-object",
            "--region",
            config.region,
            "--bucket",
            config.bucket,
            "--key",
            key,
            body.name,
        ]
        if byte_range:
            command.extend(["--range", byte_range])
        meta = json.loads(aws(command) or "{}")
        body.seek(0)
        data = body.read()
    return data, object_total(meta, len(data))


def object_total(meta, data_len):
    content_range = meta.get("ContentRange") or ""
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1]
        if total.isdigit():
            return int(total)
    length = meta.get("ContentLength")
    if isinstance(length, int):
        return length
    if isinstance(length, str) and length.isdigit():
        return int(length)
    return data_len


def put_object(config, key, data):
    suffix = os.path.splitext(key)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix) as body:
        body.write(data)
        body.flush()
        aws(
            [
                "aws",
                "s3",
                "cp",
                body.name,
                f"s3://{config.bucket}/{key}",
                "--region",
                config.region,
                "--only-show-errors",
            ]
        )


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
    except BrokenPipeError:
        sys.exit(0)
    except OSError as err:
        raise SystemExit(err) from err
