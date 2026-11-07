import json
import os
from datetime import timezone
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}

bucket = os.environ["PHOTO_BUCKET"]
prefix = os.environ["PHOTO_PREFIX"]
index_key = os.environ["INDEX_KEY"]

s3 = boto3.client("s3")


def lambda_handler(event, context):
    photos = _list_photos()
    index = _load_index()
    body = {"photos": [_decorate(photo, index) for photo in photos]}
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "public, max-age=60",
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


def _decorate(photo, index):
    key = photo["key"]
    relative = key[len(prefix) :]
    entry = index.get(key) or {}
    title = entry.get("title") or relative
    description = entry.get("description") or ""
    tags = entry.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    prints = entry.get("prints") or []
    if not isinstance(prints, list):
        prints = []
    return {
        "url": "/" + quote(key, safe="/"),
        "name": relative,
        "title": title,
        "description": description,
        "tags": [str(tag) for tag in tags],
        "prints": [_decorate_print(item) for item in prints if _is_print(item)],
        "lastModified": photo["lastModified"],
    }


def _is_print(item):
    return isinstance(item, dict) and item.get("id") is not None and item.get("label")


def _decorate_print(item):
    return {
        "id": item.get("id"),
        "label": str(item.get("label")),
        "price": str(item.get("price") or ""),
    }
