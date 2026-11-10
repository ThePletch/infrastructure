import importlib
import json
from datetime import timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

PHOTO_KEY = "photos/orion.jpg"
INDEX_KEY = "photos/_index.json"


class _ImmediatePool:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, *args, **kwargs):
        value = fn(*args, **kwargs)

        class _Done:
            def result(self):
                return value

        return _Done()


def _client_error(code, operation):
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


@pytest.fixture
def manifest():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="photo-bucket")
        import photo_manifest

        module = importlib.reload(photo_manifest)
        module.ThreadPoolExecutor = _ImmediatePool
        yield module, s3


def _published_index():
    return {
        PHOTO_KEY: {
            "title": "Orion",
            "description": "Night sky",
            "tags": ["sky", 7],
            "thumbnail": "photos/_thumbs/orion.jpg.jpg",
            "lightbox": "photos/_lightbox/orion.jpg.jpg",
            "prints": [
                {"id": 3, "label": "Framed poster · 12x18", "price": "70.00"},
                {"id": 9, "label": "Poster · 12x18", "price": "24.00"},
                {"id": 1, "label": "Poster · 8x12", "price": "20.00"},
                {"label": "missing id"},
            ],
        }
    }


def _put_photo(s3, key=PHOTO_KEY):
    s3.put_object(
        Bucket="photo-bucket",
        Key=key,
        Body=b"image",
    )


def test_happy_path_publishes_indexed_photo(manifest):
    module, s3 = manifest
    _put_photo(s3)
    s3.put_object(
        Bucket="photo-bucket",
        Key=INDEX_KEY,
        Body=json.dumps(_published_index()).encode(),
    )

    response = module.lambda_handler({}, None)

    modified = (
        s3.head_object(Bucket="photo-bucket", Key=PHOTO_KEY)["LastModified"]
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    assert response["statusCode"] == 200
    assert response["headers"]["cache-control"] == "public, max-age=60"
    assert json.loads(response["body"]) == {
        "photos": [
            {
                "thumbnail": "https://photos.example/photos/_thumbs/orion.jpg.jpg",
                "lightbox": "https://photos.example/photos/_lightbox/orion.jpg.jpg",
                "name": "orion.jpg",
                "title": "Orion",
                "description": "Night sky",
                "tags": ["sky", "7"],
                "prints": [
                    {"id": 1, "label": "Poster · 8x12", "price": "20.00"},
                    {"id": 9, "label": "Poster · 12x18", "price": "24.00"},
                    {"id": 3, "label": "Framed poster · 12x18", "price": "70.00"},
                ],
                "crops": [],
                "lastModified": modified,
            }
        ]
    }


def test_skips_unpublished_photos_and_non_images(manifest):
    module, s3 = manifest
    _put_photo(s3, "photos/bare.jpg")
    _put_photo(s3, "photos/notes.txt")
    _put_photo(s3, "photos/_thumbs/cached.jpg")
    s3.put_object(
        Bucket="photo-bucket",
        Key=INDEX_KEY,
        Body=json.dumps(_published_index()).encode(),
    )

    body = json.loads(module.lambda_handler({}, None)["body"])

    assert body["photos"] == []


def test_missing_index_returns_no_photos(manifest):
    module, s3 = manifest
    _put_photo(s3)

    response = module.lambda_handler({}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"photos": []}


def test_corrupt_index_returns_no_photos(manifest):
    module, s3 = manifest
    _put_photo(s3)
    s3.put_object(Bucket="photo-bucket", Key=INDEX_KEY, Body=b"{not json")

    response = module.lambda_handler({}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"photos": []}


def test_index_read_failure_propagates(manifest):
    module, s3 = manifest
    _put_photo(s3)

    def deny(**kwargs):
        raise _client_error("AccessDenied", "GetObject")

    module.s3.get_object = deny

    with pytest.raises(ClientError):
        module.lambda_handler({}, None)


def test_listing_failure_propagates(manifest):
    module, _s3 = manifest

    def deny(**kwargs):
        raise _client_error("AccessDenied", "ListObjectsV2")

    module.s3.list_objects_v2 = deny

    with pytest.raises(ClientError):
        module.lambda_handler({}, None)
