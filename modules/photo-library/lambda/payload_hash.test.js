const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { handler } = require("./payload_hash");

function event(method, body) {
  return {
    Records: [
      {
        cf: {
          request: {
            method,
            headers: {},
            body,
          },
        },
      },
    ],
  };
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

test("leaves requests that have no body hash requirement unchanged", async () => {
  const incoming = event("GET");
  const request = incoming.Records[0].cf.request;
  const result = await handler(incoming);
  assert.equal(result, request);
  assert.equal(result.headers["x-amz-content-sha256"], undefined);
});

test("sets the raw-body hash for a utf8 POST", async () => {
  const result = await handler(
    event("POST", { data: "hello", encoding: "text", inputTruncated: false }),
  );
  assert.equal(result.headers["x-amz-content-sha256"][0].value, sha256(Buffer.from("hello")));
});

test("hashes a base64 body and an empty body", async () => {
  const encoded = await handler(
    event("PUT", {
      data: Buffer.from("hello").toString("base64"),
      encoding: "base64",
      inputTruncated: false,
    }),
  );
  assert.equal(encoded.headers["x-amz-content-sha256"][0].value, sha256(Buffer.from("hello")));

  const empty = await handler(event("PATCH", { inputTruncated: false }));
  assert.equal(empty.headers["x-amz-content-sha256"][0].value, sha256(Buffer.alloc(0)));
});

test("rejects a truncated body", async () => {
  const result = await handler(
    event("POST", { data: "partial", encoding: "text", inputTruncated: true }),
  );
  assert.equal(result.status, "413");
  assert.equal(result.statusDescription, "Payload Too Large");
  assert.deepEqual(JSON.parse(result.body), { error: "Request body is too large." });
  assert.equal(result.headers["cache-control"][0].value, "no-store");
});
