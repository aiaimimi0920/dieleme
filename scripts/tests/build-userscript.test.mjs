import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  OUTPUT_PATH,
  PART_PATHS,
  buildUserscriptSource,
  checkUserscriptOutput,
} from "../build-userscript.mjs";


const REVIEWED_PRE_SPLIT_SHA256 =
  "145ef726b10d4b5d91a40a73237be5c191dcb3b5209aab4022cd06cf6ba12dac";


test("userscript parts deterministically reproduce the installable script", () => {
  assert.equal(new Set(PART_PATHS).size, PART_PATHS.length);
  for (const partPath of PART_PATHS) {
    assert.equal(path.extname(partPath), ".js");
    assert.ok(fs.statSync(partPath).isFile());
  }
  checkUserscriptOutput();
});


test("userscript build keeps metadata first and one shared IIFE", () => {
  const source = buildUserscriptSource();
  assert.ok(source.startsWith("// ==UserScript==\n"));
  assert.ok(source.includes("// ==/UserScript==\n"));
  assert.equal((source.match(/\(function\(\) \{/g) || []).length, 1);
  assert.ok(source.trimEnd().endsWith("})();"));
  assert.ok(fs.readFileSync(OUTPUT_PATH, "utf8").length > 0);
});


test("initial source split preserves the reviewed legacy script", () => {
  const digest = crypto
    .createHash("sha256")
    .update(buildUserscriptSource(), "utf8")
    .digest("hex");
  assert.equal(digest, REVIEWED_PRE_SPLIT_SHA256);
});
