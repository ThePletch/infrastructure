import importlib

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

MESSAGE_ID = "msg-1"
RAW_EMAIL = (
    b"From: Ada <ada@example.com>\r\n"
    b"To: hello@example.test\r\n"
    b"Subject: Hi\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Hello there\r\n"
)


def _ses_event(spam="PASS", virus="PASS"):
    return {
        "Records": [
            {
                "eventSource": "aws:ses",
                "eventVersion": "1.0",
                "ses": {
                    "receipt": {
                        "timestamp": "2024-05-01T12:00:00.000Z",
                        "processingTimeMillis": 10,
                        "recipients": ["hello@example.test"],
                        "spamVerdict": {"status": spam},
                        "virusVerdict": {"status": virus},
                        "spfVerdict": {"status": "PASS"},
                        "dkimVerdict": {"status": "PASS"},
                        "dmarcVerdict": {"status": "PASS"},
                        "action": {"type": "Lambda", "invocationType": "Event"},
                    },
                    "mail": {
                        "timestamp": "2024-05-01T12:00:00.000Z",
                        "source": "ada@example.com",
                        "messageId": MESSAGE_ID,
                        "destination": ["hello@example.test"],
                        "headersTruncated": False,
                        "headers": [
                            {"name": "From", "value": "Ada <ada@example.com>"},
                            {"name": "To", "value": "hello@example.test"},
                            {"name": "Subject", "value": "Hi"},
                        ],
                        "commonHeaders": {
                            "from": ["Ada <ada@example.com>"],
                            "to": ["hello@example.test"],
                            "returnPath": "ada@example.com",
                            "messageId": "<msg-1@example.com>",
                            "date": "Wed, 01 May 2024 12:00:00 +0000",
                            "subject": "Hi",
                        },
                    },
                },
            }
        ]
    }


def _load(reject_spam="false", with_routes=True):
    import os

    os.environ["RejectSpam"] = reject_spam
    s3 = boto3.client("s3", region_name="us-east-1")
    ssm = boto3.client("ssm", region_name="us-east-1")
    s3.create_bucket(Bucket="mail-bucket")
    if with_routes:
        ssm.put_parameter(Name="/email/catch-all", Value="owner@example.com", Type="String")
        ssm.put_parameter(Name="/email/inboxes/hello", Value="owner@example.com", Type="String")
    import forward_emails

    module = importlib.reload(forward_emails)
    sent = []

    def send_email(**kwargs):
        sent.append(kwargs)
        content = kwargs.get("Content", {})
        if "Raw" in content:
            raise ClientError(
                {"Error": {"Code": "MessageRejected", "Message": "rejected by ses"}},
                "SendEmail",
            )
        return {"MessageId": "fallback-1"}

    module.client_ses.send_email = send_email
    return module, s3, sent


def _put_raw(s3):
    s3.put_object(Bucket="mail-bucket", Key=f"incoming/{MESSAGE_ID}", Body=RAW_EMAIL)


@pytest.fixture
def forwarder():
    with mock_aws():
        module, s3, sent = _load()

        def send_email(**kwargs):
            sent.append(kwargs)
            return {"MessageId": "sent-1"}

        module.client_ses.send_email = send_email
        yield module, s3, sent


def test_happy_path_forwards_and_deletes_the_raw_message(forwarder):
    module, s3, sent = forwarder
    _put_raw(s3)

    assert module.lambda_handler(_ses_event(), None) is None

    assert len(sent) == 1
    message = sent[0]
    assert message["FromEmailAddress"] == '"Ada" <forwarder@example.test>'
    assert message["Destination"]["ToAddresses"] == ["owner@example.com"]
    assert "Hello there" in message["Content"]["Raw"]["Data"]
    with pytest.raises(ClientError):
        s3.get_object(Bucket="mail-bucket", Key=f"incoming/{MESSAGE_ID}")


def test_spam_and_virus_are_rejected_without_forwarding_the_body():
    with mock_aws():
        module, s3, sent = _load(reject_spam="true")
        _put_raw(s3)

        assert module.lambda_handler(_ses_event(spam="FAIL"), None) is None

        stored = s3.get_object(Bucket="mail-bucket", Key=f"incoming/{MESSAGE_ID}")
        assert stored["Body"].read() == RAW_EMAIL

    assert sent
    assert all("Raw" not in message["Content"] for message in sent)
    subjects = [message["Content"]["Simple"]["Subject"]["Data"] for message in sent]
    assert any("spam" in subject.lower() for subject in subjects)


def test_missing_raw_message_sends_a_fallback_and_raises():
    with mock_aws():
        module, _s3, sent = _load()

        with pytest.raises(ClientError):
            module.lambda_handler(_ses_event(), None)

    assert len(sent) == 1
    assert sent[0]["Content"]["Simple"]["Subject"]["Data"].startswith("Rejected email")
    assert "forward error" in sent[0]["Content"]["Simple"]["Subject"]["Data"]
    assert sent[0]["Destination"]["ToAddresses"] == ["owner@example.com"]


def test_ses_rejection_sends_a_fallback_and_raises():
    with mock_aws():
        module, s3, sent = _load()
        _put_raw(s3)

        with pytest.raises(ClientError):
            module.lambda_handler(_ses_event(), None)

    assert any("Raw" in message["Content"] for message in sent)
    fallbacks = [message for message in sent if "Simple" in message["Content"]]
    assert len(fallbacks) == 1
    assert "forward error" in fallbacks[0]["Content"]["Simple"]["Subject"]["Data"]


def test_missing_forwarding_config_raises_before_sending():
    with mock_aws():
        module, _s3, sent = _load(with_routes=False)

        with pytest.raises(Exception):
            module.lambda_handler(_ses_event(), None)

    assert sent == []
