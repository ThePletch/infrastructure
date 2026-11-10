import io
import json
import urllib.error

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from PIL import Image

import photo_index

BUCKET = "photo-bucket"
PREFIX = "photos/"
INDEX_KEY = "photos/_index.json"
PHOTO_KEY = "photos/orion.jpg"


class _ConflictS3:
    def __init__(self, real, failures):
        self._real = real
        self._failures = failures
        self.index_puts = 0

    def put_object(self, **kwargs):
        if kwargs.get("Key") == INDEX_KEY:
            self.index_puts += 1
            if self.index_puts <= self._failures:
                raise ClientError(
                    {"Error": {"Code": "PreconditionFailed", "Message": "conflict"}},
                    "PutObject",
                )
        return self._real.put_object(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _jpeg_bytes(size=(64, 48)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (12, 34, 56)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _event(key, event_name="ObjectCreated:Put"):
    return {
        "Records": [
            {
                "eventName": event_name,
                "s3": {"bucket": {"name": BUCKET}, "object": {"key": key}},
            }
        ]
    }


@pytest.fixture
def bucket(monkeypatch):
    monkeypatch.setenv("PHOTO_BUCKET", BUCKET)
    monkeypatch.setenv("PHOTO_PREFIX", PREFIX)
    monkeypatch.setenv("INDEX_KEY", INDEX_KEY)
    monkeypatch.setenv("SITE_ORIGIN", "https://photos.example")
    monkeypatch.delenv("PRINTFUL_API_TOKEN", raising=False)
    photo_index.s3 = None
    photo_index._printful_catalog = {}
    photo_index._printful_by_external_id = None
    photo_index._printful_store_id = None
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield s3
    photo_index.s3 = None


def _index(s3):
    body = s3.get_object(Bucket=BUCKET, Key=INDEX_KEY)["Body"].read()
    return json.loads(body)


def test_happy_path_writes_derivatives_and_index(bucket):
    bucket.put_object(Bucket=BUCKET, Key=PHOTO_KEY, Body=_jpeg_bytes(), ContentType="image/jpeg")

    result = photo_index.lambda_handler(_event(PHOTO_KEY), None)

    assert result == {"statusCode": 200}
    entry = _index(bucket)[PHOTO_KEY]
    assert entry["title"] == ""
    assert entry["width"] == 64
    assert entry["height"] == 48
    assert entry["thumbnail"] == "photos/_thumbs/orion.jpg.jpg"
    assert entry["lightbox"] == "photos/_lightbox/orion.jpg.jpg"
    for key in (entry["thumbnail"], entry["lightbox"]):
        stored = bucket.get_object(Bucket=BUCKET, Key=key)
        assert stored["ContentType"] == "image/jpeg"
        assert stored["Body"].read()[:2] == b"\xff\xd8"


def test_ignores_unrelated_index_and_derivative_keys(bucket):
    photo_index.lambda_handler(
        {
            "Records": [
                _event("other/orion.jpg")["Records"][0],
                _event(INDEX_KEY)["Records"][0],
                _event("photos/_thumbs/orion.jpg.jpg")["Records"][0],
                _event("photos/_lightbox/orion.jpg.jpg")["Records"][0],
            ]
        },
        None,
    )

    with pytest.raises(ClientError) as caught:
        bucket.get_object(Bucket=BUCKET, Key=INDEX_KEY)
    assert caught.value.response["Error"]["Code"] in ("NoSuchKey", "404")


def test_removal_drops_index_entry_and_derivatives(bucket):
    bucket.put_object(
        Bucket=BUCKET,
        Key=INDEX_KEY,
        Body=json.dumps({PHOTO_KEY: {"title": "Orion"}}).encode(),
    )
    bucket.put_object(Bucket=BUCKET, Key="photos/_thumbs/orion.jpg.jpg", Body=b"thumb")
    bucket.put_object(Bucket=BUCKET, Key="photos/_lightbox/orion.jpg.jpg", Body=b"full")

    photo_index.lambda_handler(_event(PHOTO_KEY, "ObjectRemoved:Delete"), None)

    assert PHOTO_KEY not in _index(bucket)
    for key in ("photos/_thumbs/orion.jpg.jpg", "photos/_lightbox/orion.jpg.jpg"):
        with pytest.raises(ClientError):
            bucket.get_object(Bucket=BUCKET, Key=key)


def test_non_image_is_removed_from_the_index(bucket):
    key = "photos/notes.txt"
    bucket.put_object(
        Bucket=BUCKET,
        Key=INDEX_KEY,
        Body=json.dumps({key: {"title": "Notes"}}).encode(),
    )
    bucket.put_object(Bucket=BUCKET, Key=key, Body=b"hello")

    photo_index.lambda_handler(_event(key), None)

    assert key not in _index(bucket)


def test_corrupt_image_raises(bucket):
    bucket.put_object(Bucket=BUCKET, Key=PHOTO_KEY, Body=b"not an image")

    with pytest.raises(Exception):
        photo_index.lambda_handler(_event(PHOTO_KEY), None)


def test_index_write_retries_then_gives_up(bucket):
    bucket.put_object(Bucket=BUCKET, Key=PHOTO_KEY, Body=_jpeg_bytes())
    flaky = _ConflictS3(boto3.client("s3", region_name="us-east-1"), failures=photo_index.MAX_RETRIES)
    photo_index.s3 = flaky

    with pytest.raises(RuntimeError, match="photo index"):
        photo_index.lambda_handler(_event(PHOTO_KEY), None)

    assert flaky.index_puts == photo_index.MAX_RETRIES


def test_build_sync_variants_uses_price_list(bucket):
    photo_index._printful_catalog[1] = [
        {"id": 11, "size": "12″×18″", "price": "9.50", "in_stock": True},
        {"id": 12, "size": "8″×20″", "price": "4.00", "in_stock": True},
    ]
    photo_index._printful_catalog[2] = [
        {"id": 21, "size": "12″×18″", "color": "Black", "price": "30.00", "in_stock": True},
        {"id": 22, "size": "8″×20″", "color": "Black", "price": "12.00", "in_stock": True},
    ]

    variants = photo_index._build_sync_variants(PHOTO_KEY, ((12, 18), (8, 20)))

    by_external = {item["external_id"]: item for item in variants}
    assert by_external[f"{PHOTO_KEY}:poster:12x18"]["retail_price"] == "25.00"
    assert by_external[f"{PHOTO_KEY}:poster:8x20"]["retail_price"] == "25.00"
    assert by_external[f"{PHOTO_KEY}:framed:12x18"]["retail_price"] == "70.00"
    assert f"{PHOTO_KEY}:framed:8x20" not in by_external


def _printful_product():
    return {
        "sync_product": {"id": 7, "external_id": PHOTO_KEY, "name": "Orion"},
        "sync_variants": [
            {
                "id": 70,
                "external_id": f"{PHOTO_KEY}:poster:12x18",
                "retail_price": "10.00",
                "variant_id": 11,
                "product": {"variant_id": 11},
            },
            {
                "id": 71,
                "external_id": f"{PHOTO_KEY}:poster:8x10",
                "retail_price": "20.00",
                "variant_id": 12,
                "product": {"variant_id": 12},
            },
            {
                "id": 72,
                "external_id": f"{PHOTO_KEY}:framed:8x20",
                "retail_price": "15.00",
                "variant_id": 22,
                "product": {"variant_id": 22},
            },
        ],
    }


def _install_printful(monkeypatch, product, on_put=None):
    calls = []

    def request(method, path, payload=None, unwrap=True):
        calls.append((method, path, payload))
        if method == "GET" and path.startswith("/store/products?"):
            page = {"result": [{"id": 7, "external_id": PHOTO_KEY}], "paging": {"total": 1}}
            return page["result"] if unwrap else page
        if method == "GET" and path == "/store/products/7":
            return product
        if method == "PUT" and path.startswith("/store/variants/"):
            if on_put:
                return on_put(path, payload)
            return {"id": path.rsplit("/", 1)[-1], "retail_price": payload["retail_price"]}
        if method == "PUT" and path.startswith("/store/products/"):
            product["sync_variants"] = _materialize_variants(product, payload or {})
            return {"id": (product.get("sync_product") or {}).get("id")}
        raise AssertionError((method, path, payload))

    monkeypatch.setenv("PRINTFUL_API_TOKEN", "token")
    monkeypatch.setenv("PRINTFUL_STORE_ID", "1")
    monkeypatch.setattr(photo_index, "_printful_request", request)
    return calls


def _materialize_variants(product, payload):
    current = {variant["id"]: variant for variant in product.get("sync_variants") or []}
    updated = []
    next_id = 80
    for item in payload.get("sync_variants") or []:
        if item.get("id") in current:
            variant = dict(current[item["id"]])
            if item.get("retail_price") is not None:
                variant["retail_price"] = item["retail_price"]
            updated.append(variant)
            continue
        updated.append(
            {
                "id": next_id,
                "external_id": item.get("external_id"),
                "retail_price": item.get("retail_price"),
                "variant_id": item.get("variant_id"),
            }
        )
        next_id += 1
    return updated


def test_existing_printful_prices_stay_without_the_flag(bucket, monkeypatch):
    product = _printful_product()
    calls = _install_printful(monkeypatch, product)
    bucket.put_object(Bucket=BUCKET, Key=PHOTO_KEY, Body=_jpeg_bytes())

    photo_index.lambda_handler(_event(PHOTO_KEY), None)

    assert [call[0] for call in calls] == ["GET", "GET"]
    prices = {item["id"]: item["price"] for item in _index(bucket)[PHOTO_KEY]["prints"]}
    assert prices == {70: "10.00", 71: "20.00", 72: "15.00"}


def test_overwrite_prices_syncs_matching_variants(bucket, monkeypatch):
    # 2700×1800 is 2:3. At 150 DPI that keeps 8×12 and 12×18 and drops 20×30.
    product = {
        "sync_product": {"id": 7, "external_id": PHOTO_KEY, "name": "Orion"},
        "sync_variants": [
            {
                "id": 70,
                "external_id": f"{PHOTO_KEY}:poster:12x18",
                "retail_price": "10.00",
                "variant_id": 11,
                "product": {"variant_id": 11},
            },
            {
                "id": 71,
                "external_id": f"{PHOTO_KEY}:poster:8x10",
                "retail_price": "20.00",
                "variant_id": 12,
                "product": {"variant_id": 12},
            },
            {
                "id": 72,
                "external_id": f"{PHOTO_KEY}:framed:8x20",
                "retail_price": "15.00",
                "variant_id": 22,
                "product": {"variant_id": 22},
            },
            {
                "id": 73,
                "external_id": f"{PHOTO_KEY}:framed:12x18",
                "retail_price": "70.00",
                "variant_id": 21,
                "product": {"variant_id": 21},
            },
            {
                "id": 74,
                "external_id": f"{PHOTO_KEY}:framed:8x12",
                "retail_price": "15.00",
                "variant_id": 23,
                "product": {"variant_id": 23},
            },
        ],
    }
    calls = _install_printful(monkeypatch, product)
    photo_index._printful_catalog[1] = [
        {"id": 11, "size": "12″×18″", "price": "9.50", "in_stock": True},
        {"id": 13, "size": "8″×12″", "price": "8.00", "in_stock": True},
    ]
    photo_index._printful_catalog[2] = [
        {"id": 21, "size": "12″×18″", "color": "Black", "price": "30.00", "in_stock": True},
        {"id": 23, "size": "8″×12″", "color": "Black", "price": "18.00", "in_stock": True},
    ]
    bucket.put_object(Bucket=BUCKET, Key=PHOTO_KEY, Body=_jpeg_bytes((2700, 1800)))
    event = _event(PHOTO_KEY)
    event["overwrite_prices"] = True

    photo_index.lambda_handler(event, None)

    assert [call[0] for call in calls] == ["GET", "GET", "PUT", "GET"]
    assert calls[2][1] == "/store/products/7"
    assert calls[2][2] == {
        "sync_variants": [
            {
                "external_id": f"{PHOTO_KEY}:poster:8x12",
                "variant_id": 13,
                "retail_price": "20.00",
                "files": [{"type": "default", "url": "https://photos.example/photos/orion.jpg"}],
                "options": [{"id": "fill_mode", "value": "fit"}],
            },
            {
                "id": 70,
                "external_id": f"{PHOTO_KEY}:poster:12x18",
                "variant_id": 11,
                "retail_price": "25.00",
            },
            {
                "id": 74,
                "external_id": f"{PHOTO_KEY}:framed:8x12",
                "variant_id": 23,
                "retail_price": "15.00",
            },
            {
                "id": 73,
                "external_id": f"{PHOTO_KEY}:framed:12x18",
                "variant_id": 21,
                "retail_price": "70.00",
            },
        ]
    }
    prints = _index(bucket)[PHOTO_KEY]["prints"]
    assert [(item["id"], item["label"], item["price"]) for item in prints] == [
        (80, "Poster · 8x12", "20.00"),
        (70, "Poster · 12x18", "25.00"),
        (74, "Framed poster · 8x12", "15.00"),
        (73, "Framed poster · 12x18", "70.00"),
    ]


def test_overwrite_without_dimensions_keeps_variants(bucket, monkeypatch):
    product = _printful_product()
    calls = _install_printful(monkeypatch, product)

    photo_index._sync_existing_printful(PHOTO_KEY, {"width": 0, "height": 0}, product)

    assert [call[:2] for call in calls] == [("PUT", "/store/variants/70")]
    assert [variant["id"] for variant in product["sync_variants"]] == [70, 71, 72]


def test_overwrite_reads_pixels_when_the_header_has_no_size(bucket, monkeypatch):
    product = _printful_product()
    calls = _install_printful(monkeypatch, product)
    real = photo_index.extract_metadata

    def no_size(data):
        fields = real(data)
        fields.pop("width", None)
        fields.pop("height", None)
        return fields

    monkeypatch.setattr(photo_index, "extract_metadata", no_size)
    bucket.put_object(Bucket=BUCKET, Key=PHOTO_KEY, Body=_jpeg_bytes())
    event = _event(PHOTO_KEY)
    event["overwrite_prices"] = True

    photo_index.lambda_handler(event, None)

    # 64×48 is below 150 DPI for every print, so the sync drops them all.
    assert calls[2][:2] == ("PUT", "/store/products/7")
    assert calls[2][2] == {"sync_variants": []}
    assert "prints" not in _index(bucket)[PHOTO_KEY]


def test_catalog_failure_is_not_cached(bucket, monkeypatch):
    monkeypatch.setattr(photo_index, "_printful_request", lambda *args, **kwargs: None)

    assert photo_index._catalog_variants(1) == []
    assert 1 not in photo_index._printful_catalog


def test_printful_request_retries_rate_limit(bucket, monkeypatch):
    monkeypatch.setenv("PRINTFUL_API_TOKEN", "token")
    photo_index._printful_store_id = "1"
    calls = []

    class _Headers(dict):
        pass

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout=20):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=429,
                msg="too many",
                hdrs=_Headers({"Retry-After": "0"}),
                fp=io.BytesIO(b'{"code":429}'),
            )
        return _Response(b'{"result":{"id":1}}')

    monkeypatch.setattr(photo_index.urllib.request, "urlopen", opener)

    assert photo_index._printful_request("PUT", "/store/products/7", {"sync_variants": []}) == {"id": 1}
    assert len(calls) == 2
