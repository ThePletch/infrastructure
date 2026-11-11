import hashlib
import hmac
import io
import json
import time
import urllib.error
from urllib.parse import parse_qs

import pytest

import photo_shop

SECRET = "whsec_test"
TOKEN = "printful-token"
STRIPE_KEY = "sk_test_123"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code, body=b"{}"):
    return urllib.error.HTTPError(
        url="https://api.printful.com/",
        code=code,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def _event(path, method, body="", headers=None, base64_body=False):
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": headers or {},
        "body": body,
        "isBase64Encoded": base64_body,
    }


def _stripe_header(payload, secret=SECRET, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    signed = str(timestamp).encode() + b"." + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


@pytest.fixture
def configured(monkeypatch):
    photo_shop._printful_store_id = None
    monkeypatch.setenv("SITE_ORIGIN", "https://photos.example")
    monkeypatch.setenv("SHIPPING_CENTS", "1200")
    monkeypatch.setenv("PRINTFUL_STORE_ID", "store-1")
    monkeypatch.setenv("PRINTFUL_API_TOKEN", TOKEN)
    monkeypatch.setenv("STRIPE_SECRET_KEY", STRIPE_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    yield
    photo_shop._printful_store_id = None


@pytest.fixture
def unconfigured(monkeypatch):
    photo_shop._printful_store_id = None
    for name in ("PRINTFUL_API_TOKEN", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)


def test_checkout_happy_path(configured, monkeypatch):
    calls = []

    def opener(request, timeout=20):
        calls.append(request)
        if request.full_url.endswith("/store/variants/42"):
            return _Response(
                json.dumps({"result": {"name": "Poster · 12x18", "retail_price": "24.00"}}).encode()
            )
        if request.full_url.endswith("/v1/checkout/sessions"):
            return _Response(json.dumps({"url": "https://checkout.stripe.test/c/cs_test"}).encode())
        raise AssertionError(request.full_url)

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", opener)

    response = photo_shop.lambda_handler(
        _event("/checkout", "POST", json.dumps({"variant_id": 42})),
        None,
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"url": "https://checkout.stripe.test/c/cs_test"}
    stripe = next(call for call in calls if "stripe.com" in call.full_url)
    form = parse_qs(stripe.data.decode())
    assert form["line_items[0][price_data][unit_amount]"] == ["2400"]
    assert form["metadata[printful_variant_id]"] == ["42"]
    assert stripe.headers["Authorization"] == f"Bearer {STRIPE_KEY}"


def test_options_and_unknown_routes(unconfigured):
    options = photo_shop.lambda_handler(_event("/checkout", "OPTIONS"), None)
    missing = photo_shop.lambda_handler(_event("/nope", "GET"), None)

    assert options["statusCode"] == 204
    assert missing["statusCode"] == 404
    assert json.loads(missing["body"])["error"] == "Not found"


def test_checkout_is_unavailable_until_configured(unconfigured):
    response = photo_shop.lambda_handler(
        _event("/checkout", "POST", json.dumps({"variant_id": 1})),
        None,
    )

    assert response["statusCode"] == 503


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("not-json", "Invalid JSON"),
        (json.dumps({}), "Missing print variant"),
        (json.dumps({"variant_id": True}), "Missing print variant"),
    ],
)
def test_checkout_rejects_bad_payloads(configured, body, message):
    response = photo_shop.lambda_handler(_event("/checkout", "POST", body), None)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == message


def test_checkout_rejects_unknown_or_unpriced_prints(configured, monkeypatch):
    def unknown(request, timeout=20):
        raise _http_error(404)

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", unknown)
    missing = photo_shop.lambda_handler(
        _event("/checkout", "POST", json.dumps({"variant_id": 7})),
        None,
    )

    def unpriced(request, timeout=20):
        return _Response(json.dumps({"result": {"name": "Poster", "retail_price": "0"}}).encode())

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", unpriced)
    free = photo_shop.lambda_handler(
        _event("/checkout", "POST", json.dumps({"variant_id": "7"})),
        None,
    )

    assert missing["statusCode"] == 400
    assert json.loads(missing["body"])["error"] == "Unknown print"
    assert free["statusCode"] == 400
    assert json.loads(free["body"])["error"] == "Print is missing a price"


def test_checkout_returns_502_when_stripe_fails(configured, monkeypatch):
    def opener(request, timeout=20):
        if "printful.com" in request.full_url:
            return _Response(json.dumps({"result": {"name": "Poster", "retail_price": "10.00"}}).encode())
        raise _http_error(500, b'{"error":{"message":"down"}}')

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", opener)

    response = photo_shop.lambda_handler(
        _event("/checkout", "POST", json.dumps({"variant_id": 7})),
        None,
    )

    assert response["statusCode"] == 502


def _completed_session():
    return {
        "id": "cs_test_1",
        "metadata": {"printful_variant_id": "42"},
        "customer_details": {"email": "ada@example.com", "name": "Ada"},
        "shipping_details": {
            "name": "Ada Lovelace",
            "address": {
                "line1": "1 Main St",
                "line2": "",
                "city": "Boston",
                "state": "MA",
                "country": "US",
                "postal_code": "02110",
            },
        },
    }


def test_webhook_creates_printful_order(configured, monkeypatch):
    posted = {}

    def opener(request, timeout=20):
        if request.method == "GET" and "/orders/" in request.full_url:
            raise _http_error(404)
        if request.method == "POST" and "/orders?" in request.full_url:
            posted["url"] = request.full_url
            posted["body"] = json.loads(request.data.decode())
            return _Response(json.dumps({"result": {"id": 99}}).encode())
        raise AssertionError(request.full_url)

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", opener)
    payload = json.dumps(
        {"type": "checkout.session.completed", "data": {"object": _completed_session()}}
    ).encode()

    response = photo_shop.lambda_handler(
        _event(
            "/webhooks/stripe",
            "POST",
            payload.decode(),
            {"stripe-signature": _stripe_header(payload)},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"received": True}
    assert posted["url"].endswith("/orders?confirm=true")
    assert posted["body"]["external_id"] == "cs_test_1"
    assert "confirm" not in posted["body"]
    assert posted["body"]["items"] == [{"sync_variant_id": 42, "quantity": 1}]
    assert posted["body"]["recipient"]["zip"] == "02110"


def test_webhook_hashes_long_session_ids(configured, monkeypatch):
    session = _completed_session()
    session["id"] = "cs_live_" + ("a" * 58)
    posted = {}
    looked_up = []

    def opener(request, timeout=20):
        if request.method == "GET" and "/orders/" in request.full_url:
            looked_up.append(request.full_url)
            raise _http_error(404)
        if request.method == "POST" and "/orders?" in request.full_url:
            posted["body"] = json.loads(request.data.decode())
            return _Response(json.dumps({"result": {"id": 99}}).encode())
        raise AssertionError(request.full_url)

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", opener)
    payload = json.dumps(
        {"type": "checkout.session.completed", "data": {"object": session}}
    ).encode()

    response = photo_shop.lambda_handler(
        _event(
            "/webhooks/stripe",
            "POST",
            payload.decode(),
            {"stripe-signature": _stripe_header(payload)},
        ),
        None,
    )

    external_id = hashlib.sha256(session["id"].encode()).hexdigest()[:32]
    assert response["statusCode"] == 200
    assert posted["body"]["external_id"] == external_id
    assert len(external_id) == 32
    assert looked_up[0].endswith("/orders/@" + external_id)


def test_webhook_ignores_unrelated_events(configured, monkeypatch):
    def opener(request, timeout=20):
        raise AssertionError(request.full_url)

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", opener)
    payload = json.dumps({"type": "invoice.paid"}).encode()

    response = photo_shop.lambda_handler(
        _event(
            "/webhooks/stripe",
            "POST",
            payload.decode(),
            {"stripe-signature": _stripe_header(payload)},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"received": True}


def test_webhook_rejects_bad_signatures(configured):
    payload = json.dumps({"type": "checkout.session.completed"}).encode()
    stale = _stripe_header(payload, timestamp=int(time.time()) - 600)
    cases = [
        {},
        {"stripe-signature": "t=1,v1=deadbeef"},
        {"stripe-signature": stale},
    ]

    for headers in cases:
        response = photo_shop.lambda_handler(
            _event("/webhooks/stripe", "POST", payload.decode(), headers),
            None,
        )
        assert response["statusCode"] == 400
        assert json.loads(response["body"])["error"] == "Invalid signature"


def test_webhook_is_unavailable_until_configured(unconfigured):
    response = photo_shop.lambda_handler(_event("/webhooks/stripe", "POST", "{}"), None)

    assert response["statusCode"] == 503


def test_webhook_returns_502_when_order_cannot_be_created(configured, monkeypatch):
    def opener(request, timeout=20):
        raise _http_error(500, b'{"error":"nope"}')

    monkeypatch.setattr(photo_shop.urllib.request, "urlopen", opener)
    payload = json.dumps(
        {"type": "checkout.session.completed", "data": {"object": _completed_session()}}
    ).encode()

    response = photo_shop.lambda_handler(
        _event(
            "/webhooks/stripe",
            "POST",
            payload.decode(),
            {"stripe-signature": _stripe_header(payload)},
        ),
        None,
    )

    assert response["statusCode"] == 502
