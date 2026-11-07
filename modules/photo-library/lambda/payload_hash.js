"use strict";

const crypto = require("crypto");

// Lambda function URLs reject CloudFront OAC-signed POST/PUT/PATCH requests
// unless x-amz-content-sha256 is the hex SHA-256 of the raw body. Browsers
// and Stripe do not send that header, so the shop origin never runs.
const HASHED_METHODS = new Set(["POST", "PUT", "PATCH"]);

exports.handler = async (event) => {
  const request = event.Records[0].cf.request;
  if (!HASHED_METHODS.has(request.method)) {
    return request;
  }

  const body = request.body || {};
  if (body.inputTruncated) {
    return {
      status: "413",
      statusDescription: "Payload Too Large",
      headers: {
        "content-type": [
          { key: "Content-Type", value: "application/json; charset=utf-8" },
        ],
        "cache-control": [{ key: "Cache-Control", value: "no-store" }],
      },
      body: JSON.stringify({ error: "Request body is too large." }),
    };
  }

  const raw = body.data
    ? body.encoding === "base64"
      ? Buffer.from(body.data, "base64")
      : Buffer.from(body.data, "utf8")
    : Buffer.alloc(0);
  request.headers["x-amz-content-sha256"] = [
    {
      key: "x-amz-content-sha256",
      value: crypto.createHash("sha256").update(raw).digest("hex"),
    },
  ];
  return request;
};
