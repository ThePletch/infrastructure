import json
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
THUMBNAIL_DIR = "_thumbs"
LIGHTBOX_DIR = "_lightbox"
# Gallery tiles are 3:2. 300x200 fills that frame on a 1x screen.
THUMBNAIL_SIZE = (300, 200)
# The lightbox is at most 72rem wide, so 1280px covers it at 1x.
LIGHTBOX_MAX_EDGE = 1280
DERIVATIVE_QUALITY = 85
HEADER_BYTES = 262144
TAIL_BYTES = 262144
HEADER_RANGE = f"bytes=0-{HEADER_BYTES - 1}"
TAIL_RANGE = f"bytes=-{TAIL_BYTES}"
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
    # The reprocess script sets this. An S3 notification leaves it off, so an
    # upload keeps the variants already stored on a Printful product.
    overwrite_prices = bool(event.get("overwrite_prices"))
    for record in event.get("Records", []):
        _handle_record(record, overwrite_prices=overwrite_prices)
    return {"statusCode": 200}


def _handle_record(record, overwrite_prices=False):
    key = unquote_plus(record["s3"]["object"]["key"])
    prefix = _env("PHOTO_PREFIX")
    if not key.startswith(prefix):
        return
    if key == _index_key() or key.endswith("/" + INDEX_NAME) or _is_derivative(key):
        return
    event_name = record.get("eventName", "")
    if event_name.startswith("ObjectRemoved"):
        _delete_printful(key)
        _delete_derivatives(key)
        _update_index(remove_key=key)
        return
    if not _is_image(key):
        _update_index(remove_key=key)
        return
    metadata = _read_metadata(key, overwrite_prices=overwrite_prices)
    thumbnail, lightbox = _write_derivatives(key)
    metadata["thumbnail"] = thumbnail
    metadata["lightbox"] = lightbox
    _update_index(set_key=key, metadata=metadata)


def _is_image(key):
    _, ext = os.path.splitext(key.lower())
    return ext in IMAGE_EXTS


def _derivative_prefix(folder):
    return f"{_env('PHOTO_PREFIX')}{folder}/"


def _is_derivative(key):
    # Files under _crops/ are originals for another photo. They are indexed
    # like any other image so each crop gets a lightbox file and print sizes.
    return key.startswith(_derivative_prefix(THUMBNAIL_DIR)) or key.startswith(
        _derivative_prefix(LIGHTBOX_DIR)
    )


def _derivative_key(key, folder):
    # Keep the original filename so cat.jpg and cat.png do not share a derivative.
    prefix = _env("PHOTO_PREFIX")
    relative = key[len(prefix) :]
    return f"{prefix}{folder}/{relative}.jpg"


def _write_derivatives(key):
    response = _s3().get_object(Bucket=_bucket(), Key=key)
    thumbnail_body, lightbox_body = _derivative_bytes(response["Body"].read())
    thumbnail_key = _derivative_key(key, THUMBNAIL_DIR)
    lightbox_key = _derivative_key(key, LIGHTBOX_DIR)
    _put_jpeg(thumbnail_key, thumbnail_body)
    _put_jpeg(lightbox_key, lightbox_body)
    return thumbnail_key, lightbox_key


def _delete_derivatives(key):
    for folder in (THUMBNAIL_DIR, LIGHTBOX_DIR):
        _s3().delete_object(Bucket=_bucket(), Key=_derivative_key(key, folder))


def _put_jpeg(key, body):
    _s3().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=body,
        ContentType="image/jpeg",
    )


def _derivative_bytes(data):
    import io

    from PIL import Image, ImageOps

    # Stacked frames can sit just over Pillow's default decompression-bomb cap.
    Image.MAX_IMAGE_PIXELS = 250_000_000
    with Image.open(io.BytesIO(data)) as image:
        if image.format == "JPEG":
            image.draft("RGB", (LIGHTBOX_MAX_EDGE, LIGHTBOX_MAX_EDGE))
        oriented = ImageOps.exif_transpose(image)
        flat = _flatten_rgb(oriented)
        lightbox = flat.copy()
        lightbox.thumbnail(
            (LIGHTBOX_MAX_EDGE, LIGHTBOX_MAX_EDGE),
            Image.Resampling.LANCZOS,
        )
        thumbnail = _cover_crop(flat, *THUMBNAIL_SIZE)
        return _jpeg_bytes(thumbnail), _jpeg_bytes(lightbox)


def _cover_crop(image, width, height):
    # Scale so the frame covers width x height, then cut the overflow from
    # the center. A source smaller than the target is cropped to the same
    # aspect and left at its own size.
    from PIL import Image

    source_w, source_h = image.size
    if source_w < 1 or source_h < 1:
        return image
    scale = max(width / source_w, height / source_h)
    if scale < 1:
        resized_w = max(width, int(round(source_w * scale)))
        resized_h = max(height, int(round(source_h * scale)))
        resized = image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
        left = (resized_w - width) // 2
        top = (resized_h - height) // 2
        return resized.crop((left, top, left + width, top + height))
    if source_w * height >= source_h * width:
        crop_h = source_h
        crop_w = max(1, min(source_w, source_h * width // height))
    else:
        crop_w = source_w
        crop_h = max(1, min(source_h, source_w * height // width))
    left = (source_w - crop_w) // 2
    top = (source_h - crop_h) // 2
    return image.crop((left, top, left + crop_w, top + crop_h))


def _image_size(key):
    try:
        response = _s3().get_object(Bucket=_bucket(), Key=key)
        data = response["Body"].read()
    except Exception:
        return None
    import io

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 250_000_000
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:
        return None


def _jpeg_bytes(image):
    import io

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=DERIVATIVE_QUALITY, progressive=True)
    return out.getvalue()


def _flatten_rgb(image):
    from PIL import Image

    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (0, 0, 0))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode == "RGB":
        return image
    return image.convert("RGB")


def _read_metadata(key, overwrite_prices=False):
    empty = {"title": "", "description": "", "tags": []}
    try:
        header, total = _get_object_range(key, HEADER_RANGE)
        parsed = extract_metadata(header)
    except Exception:
        return empty
    # Older copies of the tagging script wrote PNG and WebP XMP at the end
    # of the file, past this prefix. Read the tail before giving up.
    if _trailing_metadata_unread(header, total):
        try:
            tail, _ = _get_object_range(key, TAIL_RANGE)
        except Exception:
            tail = b""
        _merge(parsed, _xmp_in_bytes(tail))
    meta = {
        "title": parsed.get("title") or "",
        "description": parsed.get("description") or "",
        "tags": parsed.get("tags") or [],
        "width": parsed.get("width") or 0,
        "height": parsed.get("height") or 0,
    }
    # A large APP segment can push the real frame past the header we parsed.
    # The pixel size is what decides which print sizes are sharp enough.
    if not meta["width"] or not meta["height"]:
        size = _image_size(key)
        if size:
            meta["width"], meta["height"] = size
    prints = _sync_printful(key, meta, overwrite_prices=overwrite_prices)
    if prints:
        meta["prints"] = prints
    return meta


def _get_object_range(key, byte_range):
    from botocore.exceptions import ClientError

    for attempt in range(3):
        try:
            response = _s3().get_object(Bucket=_bucket(), Key=key, Range=byte_range)
            return response["Body"].read(), _object_size(response)
        except ClientError as err:
            code = err.response["Error"]["Code"]
            if code in ("NoSuchKey", "404") and attempt < 2:
                time.sleep(0.5)
                continue
            raise


def _object_size(response):
    content_range = response.get("ContentRange") or ""
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1]
        return int(total) if total.isdigit() else None
    length = response.get("ContentLength")
    return length if isinstance(length, int) else None


def _trailing_metadata_unread(header, total):
    if len(header) < 12:
        return False
    png = header.startswith(b"\x89PNG\r\n\x1a\n")
    webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if not png and not webp:
        return False
    if b"<x:xmpmeta" in header or b"<xmpmeta" in header:
        return False
    if total is None:
        return len(header) >= HEADER_BYTES
    return total > len(header)


def _xmp_in_bytes(data):
    for marker in (b"<x:xmpmeta", b"<xmpmeta"):
        start = data.find(marker)
        if start >= 0:
            return _parse_xmp(data[start:])
    return {}


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
# Short/long side. 5% still leaves each print ratio closer to itself than to
# the next one, and keeps a near-square such as 2946×2866 on the square sizes.
RATIO_TOLERANCE = 0.05
SIZE_SETS = (
    (1.0, ((10, 10), (12, 12), (16, 16), (18, 18), (24, 24))),
    (4 / 5, ((8, 10), (16, 20))),
    (3 / 4, ((12, 16), (18, 24), (24, 32))),
    (2 / 3, ((8, 12), (12, 18), (20, 30), (24, 36))),
    (2 / 5, ((8, 20), (10, 24))),
)

PRICING = {
    "unframed": {
        (8, 10): 20.0,
        (8, 12): 20.0,
        (8, 20): 25.0,
        (10, 10): 20.0,
        (10, 24): 30.0,
        (12, 12): 25.0,
        (12, 16): 25.0,
        (12, 18): 25.0,
        (16, 16): 25.0,
        (16, 20): 30.0,
        (18, 18): 25.0,
        (18, 24): 30.0,
        (20, 30): 30.0,
        (24, 24): 30.0,
        (24, 32): 35.0,
        (24, 36): 40.0,
    },
    "framed": {
        (8, 10): 45.0,
        (10, 10): 50.0,
        (12, 12): 60.0,
        (12, 16): 65.0,
        (12, 18): 70.0,
        (16, 16): 80.0,
        (16, 20): 90.0,
        (18, 18): 90.0,
        (18, 24): 95.0,
        (20, 30): 115.0,
        (24, 36): 155.0,
    }
}

_printful_store_id = None
_printful_catalog = {}
_printful_by_external_id = None


def _printful_token():
    return os.environ.get("PRINTFUL_API_TOKEN", "").strip()


def _public_file_url(key):
    origin = os.environ.get("SITE_ORIGIN", "").rstrip("/")
    return f"{origin}/{quote(key)}"


def _sync_printful(key, meta, overwrite_prices=False):
    if not _printful_token():
        return []
    # A product already stored under this object key is reused. overwrite_prices
    # sends one product update: kept variants include their sync id, new sizes
    # omit it, and sizes that no longer match are left out so Printful drops
    # them. One write is what the sync-product rate limit will accept.
    existing = _existing_printful_product(key)
    if existing:
        if overwrite_prices:
            _sync_existing_printful(key, meta, existing)
        return _print_offerings(existing)
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
    saved = _printful_request("POST", "/store/products", payload)
    if not saved:
        # The @external_id route misses keys that contain a slash, so a product
        # created earlier can be absent from the first lookup. A failed create
        # means it is already there; read it back instead of leaving prints blank.
        existing = _existing_printful_product(key, refresh=True)
        if existing:
            if overwrite_prices:
                _sync_existing_printful(key, meta, existing)
            return _print_offerings(existing)
        return []
    # Create returns only the product summary (id, name, variant count).
    # The sync variant ids the gallery sells are on the product read.
    product_id = saved.get("id") or (saved.get("sync_product") or {}).get("id")
    if product_id:
        detail = _printful_request("GET", f"/store/products/{product_id}")
        if detail:
            return _print_offerings(detail)
    return _print_offerings(saved)


def _existing_printful_product(key, refresh=False):
    # GET /store/products/@{external_id} 404s when the id contains a slash,
    # which every photo key does. The store list returns those ids intact.
    product_id = _printful_product_id(key, refresh=refresh)
    if not product_id:
        return None
    return _printful_request("GET", f"/store/products/{product_id}")


def _printful_product_id(key, refresh=False):
    global _printful_by_external_id
    if refresh or _printful_by_external_id is None:
        _printful_by_external_id = _load_printful_product_ids()
    return _printful_by_external_id.get(key)


def _load_printful_product_ids():
    found = {}
    offset = 0
    while True:
        page = _printful_request(
            "GET", f"/store/products?offset={offset}&limit=100", unwrap=False
        )
        if not isinstance(page, dict):
            break
        items = page.get("result") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if not isinstance(item, dict):
                continue
            external = item.get("external_id")
            product_id = item.get("id")
            if external and product_id is not None:
                found[external] = product_id
        paging = page.get("paging") or {}
        total = paging.get("total")
        offset += len(items)
        if not items or total is None or offset >= total:
            break
    return found


def _delete_printful(key):
    if not _printful_token():
        return
    product_id = _printful_product_id(key, refresh=True)
    if not product_id:
        return
    _printful_request("DELETE", f"/store/products/{product_id}")
    if _printful_by_external_id is not None:
        _printful_by_external_id.pop(key, None)


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
    if not sizes:
        return []
    file_url = _public_file_url(key)
    variants = []
    for product_id, kind, frame in (
        (POSTER_PRODUCT_ID, "poster", None),
        (FRAMED_PRODUCT_ID, "framed", "Black"),
    ):
        catalog = _catalog_variants(product_id)
        for width_in, height_in in sizes:
            price = _listed_price(kind, width_in, height_in)
            if price is None:
                continue
            catalog_id = _match_catalog_variant(catalog, width_in, height_in, frame)
            if catalog_id is None:
                continue
            variants.append(
                {
                    "external_id": f"{key}:{kind}:{width_in}x{height_in}",
                    "variant_id": catalog_id,
                    "retail_price": price,
                    "files": [{"type": "default", "url": file_url}],
                    "options": [{"id": "fill_mode", "value": "fit"}],
                }
            )
    return variants


def _sync_existing_printful(key, meta, product):
    width = meta.get("width") or 0
    height = meta.get("height") or 0
    if not width or not height:
        _overwrite_printful_prices(product)
        return
    sizes = _eligible_sizes(width, height)
    payload = _variant_sync_payload(key, product, sizes)
    if payload is None:
        return
    product_id = _printful_sync_product_id(product)
    if product_id is None:
        print(f"printful skip variant sync for {key}: missing product id")
        return
    saved = _printful_request(
        "PUT",
        f"/store/products/{product_id}",
        {"sync_variants": payload},
    )
    if not isinstance(saved, dict):
        print(f"printful variant sync failed for {key}")
        return
    detail = saved if "sync_variants" in saved else None
    if detail is None:
        detail = _printful_request("GET", f"/store/products/{product_id}")
    if not isinstance(detail, dict) or "sync_variants" not in detail:
        print(f"printful variant sync for {key} did not return variants")
        return
    product["sync_variants"] = detail.get("sync_variants") or []


def _variant_sync_payload(key, product, sizes):
    matching_sizes = {tuple(sorted(size)) for size in sizes}
    present = set()
    payloads = []
    changed = False
    for variant in product.get("sync_variants") or []:
        if _variant_size(variant) not in matching_sizes:
            changed = True
            continue
        identity = _variant_identity(variant)
        if identity:
            present.add(identity)
        price = _price_for_sync_variant(variant)
        current = _money(variant.get("retail_price"))
        if price and current != price:
            changed = True
        payloads.append(_kept_variant_payload(variant, price or current))
    for created in _build_sync_variants(key, sizes):
        identity = _variant_identity(created)
        if identity is None or identity in present:
            continue
        changed = True
        payloads.append(created)
        present.add(identity)
    if not changed:
        return None
    payloads.sort(key=_variant_sort_key)
    return payloads


def _kept_variant_payload(variant, price):
    payload = {"id": variant.get("id")}
    if variant.get("external_id"):
        payload["external_id"] = variant["external_id"]
    variant_id = (variant.get("product") or {}).get("variant_id") or variant.get("variant_id")
    if variant_id is not None:
        payload["variant_id"] = variant_id
    if price:
        payload["retail_price"] = price
    files = _sync_files(variant.get("files"))
    if files:
        payload["files"] = files
    options = _sync_options(variant.get("options"))
    if options:
        payload["options"] = options
    return payload


def _sync_files(files):
    cleaned = []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        entry = {}
        for field in ("id", "type", "url"):
            if item.get(field) not in (None, ""):
                entry[field] = item[field]
        if entry.get("url") or entry.get("id"):
            cleaned.append(entry)
    return cleaned


def _sync_options(options):
    cleaned = []
    for item in options or []:
        if isinstance(item, dict) and item.get("id") and item.get("value") is not None:
            cleaned.append({"id": item["id"], "value": item["value"]})
    return cleaned


def _variant_sort_key(variant):
    identity = _variant_identity(variant)
    if identity is None:
        return (2, 0, 0, 0)
    kind, size = identity
    return (1 if kind == "framed" else 0, size[0] * size[1], size[0], size[1])


def _printful_sync_product_id(product):
    product_id = (product.get("sync_product") or {}).get("id")
    if product_id is not None:
        return product_id
    for variant in product.get("sync_variants") or []:
        if variant.get("sync_product_id") is not None:
            return variant["sync_product_id"]
    return None


def _variant_identity(variant):
    external = variant.get("external_id") or ""
    parts = external.rsplit(":", 2)
    if len(parts) != 3 or parts[1] not in ("poster", "framed"):
        return None
    size = _size_pair(parts[2])
    if not size:
        return None
    return parts[1], tuple(sorted(size))


def _variant_size(variant):
    identity = _variant_identity(variant)
    if identity is None:
        return None
    return identity[1]


def _overwrite_printful_prices(product):
    for variant in product.get("sync_variants") or []:
        price = _price_for_sync_variant(variant)
        sync_id = variant.get("id")
        if not price or sync_id is None:
            continue
        if _money(variant.get("retail_price")) == price:
            continue
        updated = _printful_request(
            "PUT",
            f"/store/variants/{sync_id}",
            {"retail_price": price},
        )
        if not isinstance(updated, dict):
            print(f"printful price update failed for variant {sync_id}")
            continue
        variant["retail_price"] = _money(updated.get("retail_price")) or price


def _listed_price(kind, width_in, height_in):
    group = "framed" if kind == "framed" else "unframed"
    table = PRICING.get(group) or {}
    amount = table.get((width_in, height_in))
    if amount is None:
        amount = table.get((height_in, width_in))
    return _money(amount) or None


def _price_for_sync_variant(variant):
    external = variant.get("external_id") or ""
    parts = external.rsplit(":", 2)
    if len(parts) != 3 or parts[1] not in ("poster", "framed"):
        return None
    size = _size_pair(parts[2])
    if not size:
        return None
    return _listed_price(parts[1], *size)


def _size_pair(value):
    normalized = _normalize_size(value)
    if "x" not in normalized:
        return None
    width, height = normalized.split("x", 1)
    return _size_key(width), _size_key(height)


def _size_key(part):
    number = float(part)
    if number.is_integer():
        return int(number)
    return number


def _money(value):
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _catalog_variants(product_id):
    cached = _printful_catalog.get(product_id)
    if cached is not None:
        return cached
    payload = _printful_request("GET", f"/products/{product_id}")
    variants = payload.get("variants") if isinstance(payload, dict) else None
    # A failed read must not stick: the next photo would then sync no sizes.
    if not variants:
        return []
    _printful_catalog[product_id] = variants
    return variants


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


_SIZE_PAIR = re.compile(
    r"(\d+(?:\.\d+)?)[^\d.x×✕]*[x×✕][^\d.]*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _normalize_size(value):
    # Catalog sizes look like 12″×18″. Compare the numbers so inch marks and
    # the multiply sign do not hide a 12x18 poster.
    match = _SIZE_PAIR.search(value or "")
    if not match:
        return ""
    return "x".join(_size_number(part) for part in match.groups())


def _size_number(part):
    number = float(part)
    if number.is_integer():
        return str(int(number))
    return format(number, "f").rstrip("0").rstrip(".")


def _print_offerings(result):
    offerings = []
    for variant in result.get("sync_variants") or []:
        sync_id = variant.get("id")
        if sync_id is None:
            continue
        product = variant.get("product") or {}
        offerings.append(
            {
                "id": sync_id,
                "label": _offering_label(variant),
                "price": str(variant.get("retail_price") or ""),
                "variant_id": product.get("variant_id") or variant.get("variant_id"),
            }
        )
    offerings.sort(key=_offering_sort_key)
    return offerings


def _offering_sort_key(offering):
    label = offering.get("label") or ""
    framed = 1 if "framed" in label.lower() else 0
    size = _size_pair(label) or (0, 0)
    return (framed, size[0] * size[1], size[0], size[1])


def _offering_label(variant):
    # external_id is "{key}:{poster|framed}:{width}x{height}". Printful's own
    # name often puts the size behind an inch mark ("18″×24″"), which a plain
    # width×height search misses.
    external = variant.get("external_id") or ""
    parts = external.rsplit(":", 2)
    if len(parts) == 3 and parts[1] in ("poster", "framed"):
        size = _normalize_size(parts[2])
        if size:
            kind = "Framed poster" if parts[1] == "framed" else "Poster"
            return f"{kind} · {size}"
    product_name = (variant.get("product") or {}).get("name") or ""
    name = variant.get("name") or ""
    framed = "framed" in name.lower() or "framed" in product_name.lower()
    kind = "Framed poster" if framed else "Poster"
    size = (
        _normalize_size(variant.get("size") or "")
        or _normalize_size(name)
        or _normalize_size(product_name)
    )
    return f"{kind} · {size}" if size else kind


def _printful_request(method, path, payload=None, unwrap=True):
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
    # Sync-product writes share a limit of about 10 per minute. A 429 is a
    # wait, and the same request succeeds once the window opens.
    waited = 0.0
    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            if err.code == 404 and method == "GET":
                return None
            delay = _retry_delay(err, attempt)
            if err.code in (429, 500, 502, 503, 504) and attempt < 3 and waited + delay <= 70:
                print(f"printful {method} {path} waiting {delay:.0f}s after {err.code}")
                time.sleep(delay)
                waited += delay
                continue
            print(f"printful {method} {path} failed: {err.code} {detail}")
            return None
        except urllib.error.URLError as err:
            delay = min(2 ** attempt, 8)
            if attempt < 3 and waited + delay <= 70:
                print(f"printful {method} {path} waiting {delay:.0f}s after {err}")
                time.sleep(delay)
                waited += delay
                continue
            print(f"printful {method} {path} failed: {err}")
            return None
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not unwrap:
        return parsed
    return parsed.get("result", parsed)


def _retry_delay(err, attempt):
    headers = getattr(err, "headers", None)
    raw = headers.get("Retry-After") if headers is not None and hasattr(headers, "get") else None
    try:
        delay = float(raw)
    except (TypeError, ValueError):
        delay = min(2 ** attempt, 30)
    if delay < 0:
        delay = 0
    return min(delay, 60)


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
