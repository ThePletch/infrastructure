import base64
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}

# DER-encoded DigestInfo header for SHA-256, prepended to the hash in
# PKCS #1 v1.5 signatures (RFC 8017, section 9.2).
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

bucket = os.environ["PHOTO_BUCKET"]
prefix = os.environ["PHOTO_PREFIX"]
index_key = os.environ["INDEX_KEY"]
cache_ttl = int(os.environ["CACHE_TTL_SECONDS"])
url_ttl = int(os.environ["URL_TTL_SECONDS"])
site_origin = os.environ["SITE_ORIGIN"]
signing_key_id = os.environ["SIGNING_KEY_ID"]

s3 = boto3.client("s3")
ssm = boto3.client("ssm")


def _load_signing_key():
    response = ssm.get_parameter(Name=os.environ["SIGNING_KEY_PARAM"], WithDecryption=True)
    pem = response["Parameter"]["Value"]
    body = "".join(line for line in pem.splitlines() if not line.startswith("-----"))
    return _parse_rsa_private_key(base64.b64decode(body))


def _der_read(data, offset):
    tag = data[offset]
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(data[offset : offset + size], "big")
        offset += size
    return tag, data[offset : offset + length], offset + length


def _der_sequence(data):
    items = []
    offset = 0
    while offset < len(data):
        tag, value, offset = _der_read(data, offset)
        items.append((tag, value))
    return items


def _parse_rsa_private_key(der):
    """Return RSA private-key components from a PKCS #8 or PKCS #1 key.

    Keys generated for this stack include the Chinese Remainder Theorem
    components. Signing with those is a pair of half-size exponentiations
    instead of one full-size one.
    """
    _, body, _ = _der_read(der, 0)
    fields = _der_sequence(body)
    if fields[1][0] == 0x30:
        # PKCS #8: version, AlgorithmIdentifier, OCTET STRING(RSAPrivateKey)
        _, body, _ = _der_read(fields[2][1], 0)
        fields = _der_sequence(body)
    # RSAPrivateKey: version, n, e, d, p, q, dP, dQ, qInv, ...
    ints = [int.from_bytes(value, "big") for tag, value in fields if tag == 0x02]
    n, d = ints[1], ints[3]
    if len(ints) >= 9:
        return (n, d, ints[4], ints[5], ints[6], ints[7], ints[8])
    return (n, d)


signing_key = _load_signing_key()


def _rsa_sha256_sign(message):
    n = signing_key[0]
    size = (n.bit_length() + 7) // 8
    digest = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    encoded = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    m = int.from_bytes(encoded, "big")
    if len(signing_key) == 7:
        _, _, p, q, dp, dq, qinv = signing_key
        m1 = pow(m, dp, p)
        m2 = pow(m, dq, q)
        signature = m2 + q * ((qinv * (m1 - m2)) % p)
    else:
        signature = pow(m, signing_key[1], n)
    return signature.to_bytes(size, "big")


def _cloudfront_b64(data):
    return base64.b64encode(data).decode().translate(str.maketrans("+=/", "-_~"))


def _signed_query(resource, expires):
    policy = json.dumps(
        {
            "Statement": [
                {
                    "Resource": resource,
                    "Condition": {"DateLessThan": {"AWS:EpochTime": expires}},
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    return (
        f"Policy={_cloudfront_b64(policy)}"
        f"&Signature={_cloudfront_b64(_rsa_sha256_sign(policy))}"
        f"&Key-Pair-Id={signing_key_id}&Hash-Algorithm=SHA256"
    )


def lambda_handler(event, context):
    expires = int(time.time()) + url_ttl
    # The bucket listing and the index read do not depend on each other.
    # Signing does not go faster in a thread pool: each signature is one
    # modular exponentiation, and CPython holds the GIL across it. A custom
    # policy per derivative prefix covers every object CloudFront already
    # serves from that prefix, so this signs twice per response.
    with ThreadPoolExecutor(max_workers=2) as pool:
        listed = pool.submit(_list_photos)
        indexed = pool.submit(_load_index)
        photos = listed.result()
        index = indexed.result()
    queries = {
        folder: _signed_query(
            f"{site_origin}/{quote(prefix + folder, safe='/')}*", expires
        )
        for folder in ("_thumbs/", "_lightbox/")
    }
    published = []
    for item in photos:
        photo = _decorate(item, index, queries)
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


def _decorate(photo, index, queries):
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
    thumbnail = _derivative_url(entry.get("thumbnail"), "_thumbs/", queries)
    lightbox = _derivative_url(entry.get("lightbox"), "_lightbox/", queries)
    if not thumbnail or not lightbox:
        return None
    return {
        "thumbnail": thumbnail,
        "lightbox": lightbox,
        "name": relative,
        "title": title,
        "description": description,
        "tags": [str(tag) for tag in tags],
        "prints": [_decorate_print(item) for item in prints if _is_print(item)],
        "lastModified": photo["lastModified"],
    }


def _derivative_url(key, folder, queries):
    if not isinstance(key, str) or not key.startswith(f"{prefix}{folder}"):
        return None
    return f"{site_origin}/{quote(key, safe='/')}?{queries[folder]}"


def _is_print(item):
    return isinstance(item, dict) and item.get("id") is not None and item.get("label")


def _decorate_print(item):
    return {
        "id": item.get("id"),
        "label": str(item.get("label")),
        "price": str(item.get("price") or ""),
    }
