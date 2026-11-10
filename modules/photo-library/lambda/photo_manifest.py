import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}
# Originals for a gallery photo live at _crops/<parent key>/<filename>.
# The parent key is every segment after _crops/ except the filename, so a
# photo named album/orion.jpg keeps crops under _crops/album/orion.jpg/.
CROPS_DIR = "_crops/"

bucket = os.environ["PHOTO_BUCKET"]
prefix = os.environ["PHOTO_PREFIX"]
index_key = os.environ["INDEX_KEY"]
cache_ttl = int(os.environ["CACHE_TTL_SECONDS"])
site_origin = os.environ["SITE_ORIGIN"]

s3 = boto3.client("s3")


def lambda_handler(event, context):
    # The bucket listing and the index read do not depend on each other.
    with ThreadPoolExecutor(max_workers=2) as pool:
        listed = pool.submit(_list_photos)
        indexed = pool.submit(_load_index)
        photos = listed.result()
        index = indexed.result()
    gallery = []
    crop_items = []
    for item in photos:
        relative = item["key"][len(prefix) :] if item["key"].startswith(prefix) else item["key"]
        if relative.startswith(CROPS_DIR):
            crop_items.append(item)
        else:
            gallery.append(item)
    crops_by_parent = _group_crops(crop_items, index)
    published = []
    for item in gallery:
        photo = _decorate(item, index, crops_by_parent)
        if photo:
            published.append(photo)
    body = {"photos": published}
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": f"public, max-age={cache_ttl}",
        },
        "body": json.dumps(body),
    }


def _list_photos():
    photos = []
    kwargs = {"Bucket": bucket, "Prefix": prefix}
    while True:
        response = s3.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if not _is_image(key):
                continue
            photos.append(
                {
                    "key": key,
                    "lastModified": obj["LastModified"]
                    .astimezone(timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        token = response.get("NextContinuationToken")
        if not token:
            break
        kwargs["ContinuationToken"] = token
    photos.sort(key=lambda photo: photo["lastModified"], reverse=True)
    return photos


def _is_image(key):
    relative = key[len(prefix) :] if key.startswith(prefix) else key
    if relative.startswith("_thumbs/") or relative.startswith("_lightbox/"):
        return False
    _, ext = os.path.splitext(key.lower())
    return ext in IMAGE_EXTS


def _load_index():
    try:
        response = s3.get_object(Bucket=bucket, Key=index_key)
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return {}
        raise
    try:
        payload = json.loads(response["Body"].read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _decorate(photo, index, crops_by_parent):
    key = photo["key"]
    relative = key[len(prefix) :]
    entry = index.get(key) or {}
    title = entry.get("title") or relative
    description = entry.get("description") or ""
    tags = entry.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    thumbnail = _derivative_url(entry.get("thumbnail"), "_thumbs/")
    lightbox = _derivative_url(entry.get("lightbox"), "_lightbox/")
    if not thumbnail or not lightbox:
        return None
    return {
        "thumbnail": thumbnail,
        "lightbox": lightbox,
        "name": relative,
        "title": title,
        "description": description,
        "tags": [str(tag) for tag in tags],
        "prints": _prints(entry),
        "crops": crops_by_parent.get(relative, []),
        "lastModified": photo["lastModified"],
    }


def _group_crops(items, index):
    grouped = {}
    for item in items:
        key = item["key"]
        relative = key[len(prefix) :] if key.startswith(prefix) else key
        parts = _crop_parts(relative)
        if not parts:
            continue
        parent, name = parts
        crop = _decorate_crop(key, name, index)
        if not crop:
            continue
        grouped.setdefault(parent, []).append(crop)
    for crops in grouped.values():
        crops.sort(key=lambda crop: (crop["label"].lower(), crop["name"].lower()))
    return grouped


def _crop_parts(relative):
    if not relative.startswith(CROPS_DIR):
        return None
    rest = relative[len(CROPS_DIR) :]
    parent, sep, name = rest.rpartition("/")
    if not sep or not parent or not name or name.startswith("."):
        return None
    return parent, name


def _decorate_crop(key, name, index):
    entry = index.get(key) or {}
    lightbox = _derivative_url(entry.get("lightbox"), "_lightbox/")
    if not lightbox:
        return None
    stem, _ext = os.path.splitext(name)
    return {
        "name": name,
        "label": stem or name,
        "lightbox": lightbox,
        "prints": _prints(entry),
    }


def _prints(entry):
    prints = entry.get("prints") or []
    if not isinstance(prints, list):
        prints = []
    decorated = [_decorate_print(item) for item in prints if _is_print(item)]
    decorated.sort(key=_print_sort_key)
    return decorated


def _print_sort_key(item):
    label = item.get("label") or ""
    framed = 1 if "framed" in label.lower() else 0
    match = re.search(r"(\d+(?:\.\d+)?)\s*[x×✕]\s*(\d+(?:\.\d+)?)", label, re.IGNORECASE)
    if not match:
        return (framed, 0, 0, 0)
    width = float(match.group(1))
    height = float(match.group(2))
    short, long = sorted((width, height))
    return (framed, short * long, short, long)


def _derivative_url(key, folder):
    if not isinstance(key, str) or not key.startswith(f"{prefix}{folder}"):
        return None
    return f"{site_origin}/{quote(key, safe='/')}"


def _is_print(item):
    return isinstance(item, dict) and item.get("id") is not None and item.get("label")


def _decorate_print(item):
    return {
        "id": item.get("id"),
        "label": str(item.get("label")),
        "price": str(item.get("price") or ""),
    }
