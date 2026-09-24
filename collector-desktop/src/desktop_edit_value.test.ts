import assert from "node:assert/strict";
import test from "node:test";
import { parseEditableValue } from "./desktop_edit_value.ts";

test("manual edits preserve phone numbers, long identifiers and text booleans", () => {
  for (const value of ["0012345678", "90071992547409931234", "true", "false", "{}", ""]) {
    assert.equal(parseEditableValue(value, "string"), value);
  }
});

test("typed values are converted only when safe for the original field", () => {
  assert.equal(parseEditableValue("12.5", "number"), 12.5);
  assert.equal(parseEditableValue("false", "boolean"), false);
  assert.deepEqual(parseEditableValue('{"value":1}', "object"), { value: 1 });
  for (const value of ["9007199254740993", "Infinity", "NaN", "invalid"]) {
    assert.throws(() => parseEditableValue(value, "number"));
  }
  assert.throws(() => parseEditableValue("yes", "boolean"));
  assert.throws(() => parseEditableValue('"text"', "object"));
});
