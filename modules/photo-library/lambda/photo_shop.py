import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

PRINTFUL_API = "https://api.printful.com"
STRIPE_API = "https://api.stripe.com"
SHIPPING_DEFAULT_CENTS = "1200"

_printful_store_id = None


def lambda_handler(event, context):
    path = event.get("rawPath") or ""
    method = (
        event.get("requestContext", {}).get("http", {}).get("method") or "GET"
    ).upper()
    if method == "OPTIONS":
        return _json(204, {})
    if path.endswith("/checkout") and method == "POST":
        return _checkout(event)
    if path.endswith("/webhooks/stripe") and method == "POST":
        return _stripe_webhook(event)
    return _json(404, {"error": "Not found"})


def _checkout(event):
    if not _stripe_secret() or not _printful_token():
        return _json(503, {"error": "Checkout is not configured yet."})
    try:
        payload = json.loads(_raw_body(event).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _json(400, {"error": "Invalid JSON"})
    variant_id = _intish(payload.get("variant_id"))
    if variant_id is None:
        return _json(400, {"error": "Missing print variant"})
    variant = _printful_request("GET", f"/store/variants/{variant_id}")
    if not variant:
        return _json(400, {"error": "Unknown print"})
    try:
        cents = int(round(float(variant.get("retail_price") or 0) * 100))
    except (TypeError, ValueError):
        cents = 0
    if cents < 50:
        return _json(400, {"error": "Print is missing a price"})
    name = variant.get("name") or "Print"
    origin = os.environ.get("SITE_ORIGIN", "").rstrip("/")
    shipping_cents = os.environ.get("SHIPPING_CENTS", SHIPPING_DEFAULT_CENTS)
    session = _stripe_post(
        "/v1/checkout/sessions",
        [
            ("mode", "payment"),
            ("success_url", f"{origin}/?checkout=success"),
            ("cancel_url", f"{origin}/"),
            ("shipping_address_collection[allowed_countries][0]", "US"),
            ("shipping_address_collection[allowed_countries][1]", "CA"),
            ("shipping_options[0][shipping_rate_data][type]", "fixed_amount"),
            (
                "shipping_options[0][shipping_rate_data][fixed_amount][amount]",
                shipping_cents,
            ),
            (
                "shipping_options[0][shipping_rate_data][fixed_amount][currency]",
                "usd",
            ),
            (
                "shipping_options[0][shipping_rate_data][display_name]",
                "Standard shipping",
            ),
            ("line_items[0][quantity]", "1"),
            ("line_items[0][price_data][currency]", "usd"),
            ("line_items[0][price_data][unit_amount]", str(cents)),
            ("line_items[0][price_data][product_data][name]", name),
            ("metadata[printful_variant_id]", str(variant_id)),
        ],
    )
    url = session.get("url") if isinstance(session, dict) else None
    if not url:
        return _json(502, {"error": "Could not start checkout"})
    return _json(200, {"url": url})


def _stripe_webhook(event):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret or not _printful_token():
        return _json(503, {"error": "Webhook is not configured yet."})
    payload = _raw_body(event)
    signature = (event.get("headers") or {}).get("stripe-signature", "")
    if not _verify_stripe(payload, signature, secret):
        return _json(400, {"error": "Invalid signature"})
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _json(400, {"error": "Invalid JSON"})
    if body.get("type") != "checkout.session.completed":
        return _json(200, {"received": True})
    session = body.get("data", {}).get("object") or {}
    if not _create_printful_order(session):
        return _json(502, {"error": "Could not create Printful order"})
    return _json(200, {"received": True})


def _create_printful_order(session):
    metadata = session.get("metadata") or {}
    variant_id = _intish(metadata.get("printful_variant_id"))
    if variant_id is None:
        print("stripe session missing printful_variant_id")
        return None
    recipient = _recipient(session)
    if not recipient:
        print("stripe session missing shipping address")
        return None
    external_id = session.get("id") or ""
    if external_id:
        existing = _printful_request(
            "GET", f"/orders/@{urllib.parse.quote(external_id, safe='')}"
        )
        if existing:
            return existing
    payload = {
        "external_id": external_id,
        "confirm": True,
        "recipient": recipient,
        "items": [{"sync_variant_id": variant_id, "quantity": 1}],
    }
    return _printful_request("POST", "/orders", payload)


def _recipient(session):
    shipping = (
        session.get("shipping_details")
        or (session.get("collected_information") or {}).get("shipping_details")
        or {}
    )
    address = shipping.get("address") or {}
    customer = session.get("customer_details") or {}
    name = shipping.get("name") or customer.get("name") or ""
    line1 = address.get("line1") or ""
    country = address.get("country") or ""
    zip_code = address.get("postal_code") or ""
    if not name or not line1 or not country or not zip_code:
        return None
    return {
        "name": name,
        "address1": line1,
        "address2": address.get("line2") or "",
        "city": address.get("city") or "",
        "state_code": address.get("state") or "",
        "country_code": country,
        "zip": zip_code,
        "email": customer.get("email") or "",
    }


def _verify_stripe(payload, header, secret):
    if not header:
        return False
    timestamp = ""
    signatures = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    signed = timestamp.encode("utf-8") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def _stripe_post(path, fields):
    secret = _stripe_secret()
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        STRIPE_API + path,
        data=body,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": "2024-06-20",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        print(f"stripe POST {path} failed: {err.code} {detail}")
        return None
    except urllib.error.URLError as err:
        print(f"stripe POST {path} failed: {err}")
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _printful_request(method, path, payload=None):
    token = _printful_token()
    if not token:
        return None
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "space.shay.zone-shop",
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
    _printful_store_id = stores[0].get("id") if stores else ""
    return _printful_store_id


def _raw_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8")


def _intish(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _json(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
        },
        "body": json.dumps(payload),
    }


def _stripe_secret():
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def _printful_token():
    return os.environ.get("PRINTFUL_API_TOKEN", "").strip()
