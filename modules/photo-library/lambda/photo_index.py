import json
import math
import os
import re
import struct
import time
import urllib.error
import urllib.request
import zlib
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote_plus

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}
INDEX_NAME = "_index.json"
HEADER_RANGE = "bytes=0-262143"
MAX_RETRIES = 5

DC_NS = "http://purl.org/dc/elements/1.1/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

s3 = None


def _env(name):
    return os.environ[name]


def _s3():
    global s3
    if s3 is None:
        import boto3

        s3 = boto3.client("s3")
    return s3


def _bucket():
    return _env("PHOTO_BUCKET")


def _index_key():
    return _env("INDEX_KEY")


def lambda_handler(event, context):
    for record in event.get("Records", []):
        _handle_record(record)
    return {"statusCode": 200}


def _handle_record(record):
    key = unquote_plus(record["s3"]["object"]["key"])
    prefix = _env("PHOTO_PREFIX")
    if not key.startswith(prefix):
        return
    if key == _index_key() or key.endswith("/" + INDEX_NAME):
        return
    event_name = record.get("eventName", "")
    if event_name.startswith("ObjectRemoved"):
        _delete_printful(key)
        _update_index(remove_key=key)
        return
    if not _is_image(key):
        _update_index(remove_key=key)
        return
    metadata = _read_metadata(key)
    _update_index(set_key=key, metadata=metadata)


def _is_image(key):
    _, ext = os.path.splitext(key.lower())
    return ext in IMAGE_EXTS


def _read_metadata(key):
    empty = {"title": "", "description": "", "tags": []}
    try:
        header = _get_header(key)
        parsed = extract_metadata(header)
    except Exception:
        return empty
    meta = {
        "title": parsed.get("title") or "",
        "description": parsed.get("description") or "",
        "tags": parsed.get("tags") or [],
        "width": parsed.get("width") or 0,
        "height": parsed.get("height") or 0,
    }
    prints = _sync_printful(key, meta)
    if prints:
        meta["prints"] = prints
    return meta


def _get_header(key):
    from botocore.exceptions import ClientError

    for attempt in range(3):
        try:
            response = _s3().get_object(Bucket=_bucket(), Key=key, Range=HEADER_RANGE)
            return response["Body"].read()
        except ClientError as err:
            code = err.response["Error"]["Code"]
            if code in ("NoSuchKey", "404") and attempt < 2:
                time.sleep(0.5)
                continue
            raise


def _update_index(remove_key=None, set_key=None, metadata=None):
    from botocore.exceptions import ClientError

    for _ in range(MAX_RETRIES):
        current, etag = _load_index()
        if remove_key:
            current.pop(remove_key, None)
        if set_key:
            current[set_key] = metadata
        body = json.dumps(current, separators=(",", ":")).encode("utf-8")
        kwargs = {
            "Bucket": _bucket(),
            "Key": _index_key(),
            "Body": body,
            "ContentType": "application/json",
        }
        if etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = etag
        try:
            _s3().put_object(**kwargs)
            return
        except ClientError as err:
            code = err.response["Error"]["Code"]
            if code in ("PreconditionFailed", "412", "ConditionalRequestConflict"):
                continue
            raise
    raise RuntimeError("Could not update photo index after retries")


def _load_index():
    from botocore.exceptions import ClientError

    try:
        response = _s3().get_object(Bucket=_bucket(), Key=_index_key())
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return {}, None
        raise
    etag = response["ETag"].strip('"')
    try:
        payload = json.loads(response["Body"].read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}, etag
    if not isinstance(payload, dict):
        return {}, etag
    return payload, etag


def extract_metadata(data):
    fields = {"title": "", "description": "", "tags": []}
    if data.startswith(b"\xff\xd8"):
        jpeg = _parse_jpeg(data)
        _merge(fields, jpeg.get("exif", {}))
        _merge(fields, jpeg.get("xmp", {}))
        _copy_size(fields, jpeg)
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        png = _parse_png(data)
        _merge(fields, png.get("text", {}))
        _merge(fields, png.get("xmp", {}))
        _copy_size(fields, png)
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        webp = _parse_webp(data)
        _merge(fields, webp.get("exif", {}))
        _merge(fields, webp.get("xmp", {}))
        _copy_size(fields, webp)
    elif data.startswith(b"GIF8") and len(data) >= 10:
        fields["width"], fields["height"] = struct.unpack("<HH", data[6:10])
    return fields


def _copy_size(fields, source):
    if source.get("width") and source.get("height"):
        fields["width"] = source["width"]
        fields["height"] = source["height"]


def _merge(target, source):
    if not source:
        return
    if source.get("title"):
        target["title"] = source["title"]
    if source.get("description"):
        target["description"] = source["description"]
    if source.get("tags"):
        target["tags"] = source["tags"]


def _parse_jpeg(data):
    result = {"xmp": {}, "exif": {}}
    offset = 2
    length = len(data)
    while offset + 4 <= length:
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        if marker == 0xDA or marker == 0xD9:
            break
        if marker == 0x00 or marker == 0xFF:
            offset += 1
            continue
        if marker >= 0xD0 and marker <= 0xD7:
            offset += 2
            continue
        segment_len = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        start = offset + 4
        end = start + segment_len - 2
        if segment_len < 2 or end > length:
            break
        payload = data[start:end]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC) and len(payload) >= 5:
            result["height"] = struct.unpack(">H", payload[1:3])[0]
            result["width"] = struct.unpack(">H", payload[3:5])[0]
        if marker == 0xE1:
            if payload.startswith(b"Exif\x00\x00"):
                parsed = _parse_exif(payload[6:])
                if parsed:
                    result["exif"] = parsed
            else:
                xmp = _xmp_from_app1(payload)
                if xmp:
                    result["xmp"] = xmp
        offset = end
    return result


def _xmp_from_app1(payload):
    for header in (
        b"http://ns.adobe.com/xap/1.0/\x00",
        b"http://ns.adobe.com/xmp/extension/\x00",
    ):
        if payload.startswith(header):
            return _parse_xmp(payload[len(header) :])
    if b"<x:xmpmeta" in payload or b"<xmpmeta" in payload:
        return _parse_xmp(payload)
    return {}


def _parse_png(data):
    result = {"text": {}, "xmp": {}}
    offset = 8
    text_fields = {"title": "", "description": "", "tags": []}
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            break
        payload = data[start:end]
        if chunk_type == b"IEND":
            break
        if chunk_type == b"IHDR" and len(payload) >= 8:
            result["width"] = struct.unpack(">I", payload[0:4])[0]
            result["height"] = struct.unpack(">I", payload[4:8])[0]
        if chunk_type == b"tEXt":
            _apply_png_text(text_fields, _decode_png_text(payload))
        elif chunk_type == b"zTXt":
            _apply_png_text(text_fields, _decode_png_ztxt(payload))
        elif chunk_type == b"iTXt":
            keyword, text = _decode_png_itxt(payload)
            if keyword == "XML:com.adobe.xmp":
                parsed = _parse_xmp(text.encode("utf-8"))
                if parsed:
                    result["xmp"] = parsed
            else:
                _apply_png_text(text_fields, (keyword, text))
        offset = end + 4
    result["text"] = text_fields
    return result


def _decode_png_text(payload):
    null = payload.find(b"\x00")
    if null < 0:
        return "", ""
    return _decode_bytes(payload[:null]), _decode_bytes(payload[null + 1 :])


def _decode_png_ztxt(payload):
    null = payload.find(b"\x00")
    if null < 0 or null + 2 > len(payload):
        return "", ""
    keyword = _decode_bytes(payload[:null])
    if payload[null + 1] != 0:
        return keyword, ""
    try:
        text = zlib.decompress(payload[null + 2 :]).decode("latin-1")
    except (zlib.error, UnicodeDecodeError):
        return keyword, ""
    return keyword, text


def _decode_png_itxt(payload):
    null = payload.find(b"\x00")
    if null < 0 or null + 3 > len(payload):
        return "", ""
    keyword = _decode_bytes(payload[:null])
    compressed = payload[null + 1]
    rest = payload[null + 3 :]
    # skip language and translated keyword
    for _ in range(2):
        sep = rest.find(b"\x00")
        if sep < 0:
            return keyword, ""
        rest = rest[sep + 1 :]
    if compressed:
        try:
            rest = zlib.decompress(rest)
        except zlib.error:
            return keyword, ""
    return keyword, _decode_bytes(rest)


def _apply_png_text(fields, pair):
    keyword, text = pair
    if not text:
        return
    lowered = keyword.lower()
    if lowered == "title" and not fields["title"]:
        fields["title"] = text
    elif lowered in ("description", "comment") and not fields["description"]:
        fields["description"] = text
    elif lowered in ("keywords", "subject") and not fields["tags"]:
        fields["tags"] = _split_tags(text)


def _parse_webp(data):
    result = {"xmp": {}, "exif": {}}
    offset = 12
    while offset + 8 <= len(data):
        fourcc = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        start = offset + 8
        end = start + size
        if end > len(data):
            break
        payload = data[start:end]
        if fourcc == b"VP8X" and len(payload) >= 10:
            result["width"] = 1 + int.from_bytes(payload[4:7], "little")
            result["height"] = 1 + int.from_bytes(payload[7:10], "little")
        elif fourcc == b"VP8 " and len(payload) >= 10:
            result["width"] = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
            result["height"] = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
        elif fourcc == b"VP8L" and len(payload) >= 5:
            bits = struct.unpack("<I", payload[1:5])[0]
            result["width"] = (bits & 0x3FFF) + 1
            result["height"] = ((bits >> 14) & 0x3FFF) + 1
        if fourcc == b"EXIF":
            tiff = payload[6:] if payload.startswith(b"Exif\x00\x00") else payload
            parsed = _parse_exif(tiff)
            if parsed:
                result["exif"] = parsed
        elif fourcc in (b"XMP ", b"XMP\x00"):
            parsed = _parse_xmp(payload)
            if parsed:
                result["xmp"] = parsed
        offset = end + (size % 2)
    return result


def _parse_exif(tiff):
    if len(tiff) < 8:
        return {}
    endian_mark = tiff[:2]
    if endian_mark == b"MM":
        endian = ">"
    elif endian_mark == b"II":
        endian = "<"
    else:
        return {}
    magic = struct.unpack(endian + "H", tiff[2:4])[0]
    if magic != 42:
        return {}
    ifd_offset = struct.unpack(endian + "I", tiff[4:8])[0]
    description = _read_ifd_ascii(tiff, endian, ifd_offset, 0x010E)
    title = description or _read_ifd_xp(tiff, endian, ifd_offset, 0x9C9B)
    if not title:
        return {}
    return {"title": title}


def _read_ifd_ascii(tiff, endian, ifd_offset, tag):
    entry = _find_ifd_entry(tiff, endian, ifd_offset, tag)
    if not entry:
        return ""
    tag_type, count, value = entry
    if tag_type != 2 or count < 1:
        return ""
    raw = _ifd_value_bytes(tiff, endian, tag_type, count, value)
    return _decode_bytes(raw.split(b"\x00", 1)[0])


def _read_ifd_xp(tiff, endian, ifd_offset, tag):
    entry = _find_ifd_entry(tiff, endian, ifd_offset, tag)
    if not entry:
        return ""
    tag_type, count, value = entry
    raw = _ifd_value_bytes(tiff, endian, tag_type, count, value)
    try:
        return raw.decode("utf-16-le").rstrip("\x00").strip()
    except UnicodeDecodeError:
        return ""


def _find_ifd_entry(tiff, endian, ifd_offset, wanted):
    if ifd_offset + 2 > len(tiff):
        return None
    count = struct.unpack(endian + "H", tiff[ifd_offset : ifd_offset + 2])[0]
    for i in range(count):
        start = ifd_offset + 2 + i * 12
        end = start + 12
        if end > len(tiff):
            return None
        tag, tag_type, value_count, value = struct.unpack(endian + "HHII", tiff[start:end])
        if tag == wanted:
            return tag_type, value_count, value
    return None


def _ifd_value_bytes(tiff, endian, tag_type, count, value):
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1}
    unit = type_sizes.get(tag_type, 1)
    size = unit * count
    if size <= 4:
        packed = struct.pack(endian + "I", value)
        return packed[:size]
    if value + size > len(tiff):
        return b""
    return tiff[value : value + size]


def _parse_xmp(xml_bytes):
    start = xml_bytes.find(b"<")
    if start < 0:
        return {}
    xml_bytes = xml_bytes[start:]
    end_markers = (b"</x:xmpmeta>", b"</xmpmeta>", b"</rdf:RDF>")
    end = -1
    for marker in end_markers:
        found = xml_bytes.find(marker)
        if found >= 0:
            end = found + len(marker)
            break
    if end > 0:
        xml_bytes = xml_bytes[:end]
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {}
    title = _rdf_first(root, f"{{{DC_NS}}}title")
    description = _rdf_first(root, f"{{{DC_NS}}}description")
    tags = _rdf_all(root, f"{{{DC_NS}}}subject")
    fields = {}
    if title:
        fields["title"] = title
    if description:
        fields["description"] = description
    if tags:
        fields["tags"] = tags
    return fields


def _rdf_first(root, tag):
    values = _rdf_all(root, tag)
    return values[0] if values else ""


def _rdf_all(root, tag):
    values = []
    for element in root.iter(tag):
        items = list(element.findall(f".//{{{RDF_NS}}}li"))
        if items:
            for item in items:
                text = "".join(item.itertext()).strip()
                if text:
                    values.append(text)
        else:
            text = "".join(element.itertext()).strip()
            if text:
                values.append(text)
    # de-dupe while preserving order
    seen = set()
    unique = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _split_tags(text):
    parts = []
    for chunk in text.replace(";", ",").split(","):
        tag = chunk.strip()
        if tag:
            parts.append(tag)
    return parts


def _decode_bytes(value):
    try:
        return value.decode("utf-8").strip()
    except UnicodeDecodeError:
        return value.decode("latin-1").strip()


PRINTFUL_API = "https://api.printful.com"
POSTER_PRODUCT_ID = 1
FRAMED_PRODUCT_ID = 2
MIN_DPI = 150
RATIO_TOLERANCE = 0.025
RETAIL_MARKUP = 2.0
SIZE_SETS = (
    (1.0, ((10, 10), (12, 12), (16, 16))),
    (4 / 5, ((8, 10), (16, 20))),
    (3 / 4, ((12, 16), (18, 24))),
    (2 / 3, ((12, 18), (24, 36))),
)

_printful_store_id = None
_printful_catalog = {}


def _printful_token():
    return os.environ.get("PRINTFUL_API_TOKEN", "").strip()


def _public_file_url(key):
    origin = os.environ.get("SITE_ORIGIN", "").rstrip("/")
    return f"{origin}/{quote(key)}"


def _sync_printful(key, meta):
    if not _printful_token():
        return []
    width = meta.get("width") or 0
    height = meta.get("height") or 0
    sizes = _eligible_sizes(width, height)
    if not sizes:
        print(f"printful skip {key}: no matching sizes for {width}x{height}")
        return []
    variants = _build_sync_variants(key, sizes)
    if not variants:
        print(f"printful skip {key}: no catalog variants for {sizes}")
        return []
    title = meta.get("title") or key.rsplit("/", 1)[-1]
    payload = {
        "sync_product": {
            "external_id": key,
            "name": title,
            "thumbnail": _public_file_url(key),
        },
        "sync_variants": variants,
    }
    existing = _printful_request("GET", f"/store/products/@{quote(key, safe='')}")
    if existing and existing.get("sync_product"):
        product_id = existing["sync_product"]["id"]
        result = _printful_request("PUT", f"/store/products/{product_id}", payload)
    else:
        result = _printful_request("POST", "/store/products", payload)
    if not result:
        return []
    return _print_offerings(result)


def _delete_printful(key):
    if not _printful_token():
        return
    existing = _printful_request("GET", f"/store/products/@{quote(key, safe='')}")
    if not existing or not existing.get("sync_product"):
        return
    product_id = existing["sync_product"]["id"]
    _printful_request("DELETE", f"/store/products/{product_id}")


def _eligible_sizes(width, height):
    if not width or not height:
        return []
    ratio = min(width, height) / max(width, height)
    best = None
    best_delta = RATIO_TOLERANCE
    for expected, sizes in SIZE_SETS:
        delta = abs(ratio - expected)
        if delta <= best_delta:
            best = sizes
            best_delta = delta
    if not best:
        return []
    short_px = min(width, height)
    return [size for size in best if short_px / min(size) >= MIN_DPI]


def _build_sync_variants(key, sizes):
    file_url = _public_file_url(key)
    variants = []
    for product_id, kind, frame in (
        (POSTER_PRODUCT_ID, "poster", None),
        (FRAMED_PRODUCT_ID, "framed", "Black"),
    ):
        catalog = _catalog_variants(product_id)
        for width_in, height_in in sizes:
            catalog_id = _match_catalog_variant(catalog, width_in, height_in, frame)
            if catalog_id is None:
                continue
            variants.append(
                {
                    "external_id": f"{key}:{kind}:{width_in}x{height_in}",
                    "variant_id": catalog_id,
                    "retail_price": _retail_price(catalog, catalog_id),
                    "files": [{"type": "default", "url": file_url}],
                    "options": [{"id": "fill_mode", "value": "fit"}],
                }
            )
    return variants


def _catalog_variants(product_id):
    cached = _printful_catalog.get(product_id)
    if cached is not None:
        return cached
    payload = _printful_request("GET", f"/products/{product_id}")
    variants = payload.get("variants") if payload else None
    _printful_catalog[product_id] = variants or []
    return _printful_catalog[product_id]


def _match_catalog_variant(catalog, width_in, height_in, frame_color):
    wanted = {
        _normalize_size(f"{width_in}x{height_in}"),
        _normalize_size(f"{height_in}x{width_in}"),
    }
    for variant in catalog:
        size = _normalize_size(variant.get("size"))
        if size not in wanted:
            continue
        if frame_color:
            color = (variant.get("color") or "").lower()
            if frame_color.lower() not in color:
                continue
        if variant.get("in_stock") is False:
            continue
        return variant.get("id")
    return None


def _normalize_size(value):
    return (value or "").lower().replace(" ", "").replace("×", "x")


def _retail_price(catalog, variant_id):
    cost = 0.0
    for variant in catalog:
        if variant.get("id") == variant_id:
            try:
                cost = float(variant.get("price") or 0)
            except (TypeError, ValueError):
                cost = 0.0
            break
    retail = math.ceil(cost * RETAIL_MARKUP * 100) / 100
    return f"{retail:.2f}"


def _print_offerings(result):
    offerings = []
    for variant in result.get("sync_variants") or []:
        product = variant.get("product") or {}
        catalog_id = product.get("variant_id")
        name = variant.get("name") or ""
        kind = "Framed poster" if "framed" in name.lower() else "Poster"
        size = _size_from_name(name)
        label = f"{kind} · {size}" if size else kind
        offerings.append(
            {
                "id": variant.get("id"),
                "label": label,
                "price": variant.get("retail_price") or "",
                "variant_id": catalog_id,
            }
        )
    return offerings


def _size_from_name(name):
    match = re.search(r"(\d+\s*[x×]\s*\d+)", name, re.I)
    return match.group(1).replace(" ", "") if match else ""


def _printful_request(method, path, payload=None):
    token = _printful_token()
    if not token:
        return None
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "space.shay.zone-indexer",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if path != "/stores":
        store_id = _store_id()
        if store_id:
            headers["X-PF-Store-Id"] = str(store_id)
    request = urllib.request.Request(
        PRINTFUL_API + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        if err.code == 404 and method == "GET":
            return None
        print(f"printful {method} {path} failed: {err.code} {detail}")
        return None
    except urllib.error.URLError as err:
        print(f"printful {method} {path} failed: {err}")
        return None
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed.get("result", parsed)


def _store_id():
    global _printful_store_id
    if _printful_store_id is not None:
        return _printful_store_id
    configured = os.environ.get("PRINTFUL_STORE_ID", "").strip()
    if configured:
        _printful_store_id = configured
        return _printful_store_id
    payload = _printful_request("GET", "/stores")
    stores = payload if isinstance(payload, list) else []
    if stores:
        _printful_store_id = stores[0].get("id")
    else:
        _printful_store_id = ""
    return _printful_store_id
