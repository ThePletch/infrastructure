#!/usr/bin/env python3
"""Write title, description, and tag metadata into an existing image.

The photo library indexer (modules/photo-library/lambda/photo_index.py)
reads dc:title, dc:description, and dc:subject from the start of the file.
JPEG XMP stays in an APP1 segment near the SOI marker. PNG and WebP XMP
is written immediately after the image header so it falls inside that
prefix. Updates the file in place unless --output is set.

Examples:
  python3 scripts/tag_image.py photo.jpg \\
    --title "Glacier valley" \\
    --description "Ice falling through a high mountain pass." \\
    --tag landscape --tag snow
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

XMP_NS_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXT_HEADER = b"http://ns.adobe.com/xmp/extension/\x00"
PNG_XMP_KEYWORD = b"XML:com.adobe.xmp"
WEBP_XMP_NAMES = (b"XMP ", b"XMP\x00")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, help="JPEG, PNG, or WebP file to update")
    parser.add_argument("-o", "--output", type=Path, help="Write a new file instead of updating the image in place")
    parser.add_argument("--title", default="", help="dc:title shown as the photo title")
    parser.add_argument("--description", default="", help="dc:description shown in the gallery")
    parser.add_argument("--tag", action="append", default=[], metavar="TAG", help="dc:subject tag; repeat for more than one")
    args = parser.parse_args(argv)

    tags = [tag.strip() for tag in args.tag if tag.strip()]
    title = args.title.strip()
    description = args.description.strip()
    if not title and not description and not tags:
        parser.error("pass at least one of --title, --description, or --tag")

    source = args.image
    data = source.read_bytes()
    updated = embed_metadata(data, title, description, tags)
    destination = args.output or source
    destination.write_bytes(updated)
    print(f"wrote {destination}")


def embed_metadata(data, title, description, tags):
    packet = build_xmp(title, description, tags)
    if data.startswith(b"\xff\xd8"):
        return embed_jpeg(data, packet)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return embed_png(data, packet)
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return embed_webp(data, packet)
    raise SystemExit("expected a JPEG, PNG, or WebP (the gallery reads metadata from those)")


def build_xmp(title, description, tags):
    body = []
    if title:
        body.append(
            "<dc:title><rdf:Alt><rdf:li xml:lang=\"x-default\">"
            + escape(title)
            + "</rdf:li></rdf:Alt></dc:title>"
        )
    if description:
        body.append(
            "<dc:description><rdf:Alt><rdf:li xml:lang=\"x-default\">"
            + escape(description)
            + "</rdf:li></rdf:Alt></dc:description>"
        )
    if tags:
        items = "".join("<rdf:li>" + escape(tag) + "</rdf:li>" for tag in tags)
        body.append("<dc:subject><rdf:Bag>" + items + "</rdf:Bag></dc:subject>")
    xml = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        + "".join(body)
        + "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    return xml.encode("utf-8")


def embed_jpeg(data, xmp):
    segment = _jpeg_app1(xmp)
    offset = 2
    insert_at = 2
    length = len(data)
    while offset + 4 <= length:
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        if marker in (0xDA, 0xD9):
            break
        if marker in (0x00, 0xFF):
            offset += 1
            continue
        if 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        segment_len = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        start = offset + 4
        end = start + segment_len - 2
        if segment_len < 2 or end > length:
            break
        payload = data[start:end]
        if marker == 0xE1 and _is_xmp_app1(payload):
            return data[:offset] + segment + data[end:]
        offset = end
        if marker == 0xE0:
            insert_at = offset
    return data[:insert_at] + segment + data[insert_at:]


def _jpeg_app1(xmp):
    payload = XMP_NS_HEADER + xmp
    if len(payload) > 65533:
        raise SystemExit("XMP is too large for a JPEG APP1 segment")
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _is_xmp_app1(payload):
    if payload.startswith(XMP_NS_HEADER) or payload.startswith(XMP_EXT_HEADER):
        return True
    return b"<x:xmpmeta" in payload or b"<xmpmeta" in payload


def embed_png(data, xmp):
    # iTXt goes immediately after IHDR. The indexer only reads the first
    # 256KB, and a chunk placed before IEND sits past the image data.
    chunk = _png_chunk(b"iTXt", PNG_XMP_KEYWORD + b"\x00\x00\x00\x00\x00" + xmp)
    offset = 8
    out = bytearray(data[:8])
    inserted = False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + size
        if end > len(data):
            break
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + size]
        is_xmp = chunk_type == b"iTXt" and _png_keyword(payload) == "XML:com.adobe.xmp"
        if chunk_type == b"IEND":
            if not inserted:
                out += chunk
            out += data[offset:end]
            return bytes(out)
        if not is_xmp:
            out += data[offset:end]
        if chunk_type == b"IHDR" and not inserted:
            out += chunk
            inserted = True
        offset = end
    raise SystemExit("PNG is missing an IEND chunk")


def _png_keyword(payload):
    null = payload.find(b"\x00")
    if null < 0:
        return ""
    return payload[:null].decode("latin-1")


def _png_chunk(chunk_type, payload):
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def embed_webp(data, xmp):
    chunks = _webp_chunks(data)
    width, height = _webp_canvas(chunks)
    kept = []
    vp8x = None
    for fourcc, payload in chunks:
        if fourcc == b"VP8X" and vp8x is None:
            vp8x = payload
            continue
        if fourcc in WEBP_XMP_NAMES:
            continue
        kept.append((fourcc, payload))
    if vp8x is None:
        vp8x = bytes([0x10, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    else:
        flags = bytearray(vp8x)
        if len(flags) < 10:
            raise SystemExit("WebP VP8X chunk is truncated")
        flags[0] |= 0x10
        vp8x = bytes(flags)
    # XMP sits right after VP8X so the indexer's header read can see it.
    kept.insert(0, (b"VP8X", vp8x))
    kept.insert(1, (b"XMP ", xmp))
    return _webp_bytes(kept)


def _webp_chunks(data):
    chunks = []
    offset = 12
    while offset + 8 <= len(data):
        fourcc = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        start = offset + 8
        end = start + size
        if end > len(data):
            break
        chunks.append((fourcc, data[start:end]))
        offset = end + (size % 2)
    if not chunks:
        raise SystemExit("WebP has no chunks")
    return chunks


def _webp_canvas(chunks):
    for fourcc, payload in chunks:
        if fourcc == b"VP8X" and len(payload) >= 10:
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
            return width, height
        if fourcc == b"VP8 " and len(payload) >= 10:
            width = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
            height = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
            return max(width, 1), max(height, 1)
        if fourcc == b"VP8L" and len(payload) >= 5:
            bits = struct.unpack("<I", payload[1:5])[0]
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height
    raise SystemExit("WebP is missing a canvas size")


def _webp_bytes(chunks):
    body = bytearray()
    for fourcc, payload in chunks:
        body += fourcc
        body += struct.pack("<I", len(payload))
        body += payload
        if len(payload) % 2:
            body += b"\x00"
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
    except OSError as err:
        raise SystemExit(err) from err
