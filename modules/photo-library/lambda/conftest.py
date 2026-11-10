import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

# photo_manifest reads configuration at import time.
os.environ.setdefault("PHOTO_BUCKET", "photo-bucket")
os.environ.setdefault("PHOTO_PREFIX", "photos/")
os.environ.setdefault("INDEX_KEY", "photos/_index.json")
os.environ.setdefault("CACHE_TTL_SECONDS", "60")
os.environ.setdefault("SITE_ORIGIN", "https://photos.example")
