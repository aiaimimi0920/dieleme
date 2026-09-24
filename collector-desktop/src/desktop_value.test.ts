import test from "node:test";
import assert from "node:assert/strict";

import { safeExternalUrl } from "./desktop_value.ts";

test("safeExternalUrl only allows HTTP(S) links", () => {
  assert.equal(safeExternalUrl("https://example.test/item?id=1"), "https://example.test/item?id=1");
  assert.equal(safeExternalUrl("http://127.0.0.1:8001/item"), "http://127.0.0.1:8001/item");
  assert.equal(safeExternalUrl("javascript:alert(1)"), "#");
  assert.equal(safeExternalUrl("data:text/html,unsafe"), "#");
  assert.equal(safeExternalUrl("/relative/path"), "#");
  assert.equal(safeExternalUrl(null), "#");
});
