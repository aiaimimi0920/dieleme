import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_ROOT = path.join(
  REPO_ROOT,
  "tampermonkey_scripts",
  "src",
  "fapaifang_unified",
);
export const OUTPUT_PATH = path.join(
  REPO_ROOT,
  "tampermonkey_scripts",
  "fapaifang_unified.user.js",
);
export const PART_PATHS = [
  "00_bootstrap.js",
  "10_sniff_collection.js",
  "20_sniff_challenge.js",
  "30_sniff_dashboard.js",
  "40_fast_review_loop.js",
  "50_fast_review_item.js",
  "60_slow_review.js",
  "70_detail_worker.js",
  "80_detail_helper_context.js",
  "90_detail_helper_panel.js",
  "100_detail_helper_actions.js",
  "110_dispatch_and_captcha.js",
].map((name) => path.join(SOURCE_ROOT, name));


function normalizeLineEndings(content) {
  return content.replace(/\r\n?/g, "\n");
}


export function buildUserscriptSource() {
  return PART_PATHS.map((partPath) =>
    normalizeLineEndings(fs.readFileSync(partPath, "utf8")),
  ).join("");
}


export function checkUserscriptOutput() {
  const expected = buildUserscriptSource();
  const actual = normalizeLineEndings(fs.readFileSync(OUTPUT_PATH, "utf8"));
  assert.equal(
    actual,
    expected,
    "Tampermonkey output is stale; run node scripts/build-userscript.mjs --write",
  );
}


export function writeUserscriptOutput() {
  const output = buildUserscriptSource().replace(/\n/g, "\r\n");
  fs.writeFileSync(OUTPUT_PATH, output, "utf8");
}


const invokedDirectly =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  const mode = process.argv[2] || "--check";
  if (mode === "--check") checkUserscriptOutput();
  else if (mode === "--write") writeUserscriptOutput();
  else throw new Error(`Unknown mode: ${mode}`);
}
