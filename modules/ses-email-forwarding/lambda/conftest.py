import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

# forward_emails reads configuration at import time.
os.environ.setdefault("Region", "us-east-1")
os.environ.setdefault("MailSender", "forwarder@example.test")
os.environ.setdefault("MailS3Bucket", "mail-bucket")
os.environ.setdefault("MailS3Prefix", "incoming")
os.environ.setdefault("ForwardingConfigPrefix", "/email")
