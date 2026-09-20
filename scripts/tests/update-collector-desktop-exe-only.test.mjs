import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const script = fileURLToPath(new URL("../update-collector-desktop-exe-only.ps1", import.meta.url));
const filename = "fapaifang_collector_desktop.exe";
const hash = (value) => createHash("sha256").update(value).digest("hex");
const oldBytes = Buffer.from("synthetic old executable - never launched");
const newBytes = Buffer.from("synthetic new executable - never launched");
const windows = { skip: process.platform !== "win32" };

function fixture(t, running = false) {
  const root = mkdtempSync(path.join(tmpdir(), "crow-exe-update-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const install = path.join(root, "install");
  mkdirSync(install);
  const desktop = path.join(root, "desktop");
  mkdirSync(desktop);
  const source = path.join(root, "build.exe");
  const installed = path.join(install, filename);
  writeFileSync(source, newBytes);
  writeFileSync(installed, oldBytes);
  writeFileSync(path.join(install, "start-fapaifang-collector.ps1"), "fixture launcher");
  writeFileSync(path.join(install, "database.sqlite"), "fixture data must stay");
  writeFileSync(path.join(install, "crow-desktop.runtime.json"), "fixture runtime configuration");
  const quote = (value) => `'${value.replaceAll("'", "''")}'`;
  // Use fixture process inventory, never inspect/stop the user's real observer.
  const run = (...args) => execFileSync("powershell.exe", [
    "-NoProfile", "-NonInteractive", "-Command",
    `function Get-Process { [CmdletBinding()] param([string]$Name) ${running ? "[pscustomobject]@{ Id = 123 }" : "@()"} }; & ${quote(script)} -SourceExecutable ${quote(source)} -InstallRoot ${quote(install)} -DesktopDirectory ${quote(desktop)} ${args.map((arg) => arg.startsWith("-") ? arg : quote(arg)).join(" ")}`,
  ], { encoding: "utf8", timeout: 20000, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  return { install, installed, source, desktop, run };
}

test("check-only does not write files", windows, (t) => {
  const f = fixture(t);
  assert.match(f.run(), /CHECK ONLY/);
  assert.deepEqual(readFileSync(f.installed), oldBytes);
  assert.equal(readdirSync(f.install).length, 4);
  assert.deepEqual(readdirSync(f.desktop), []);
});

test("apply backs up old exe and preserves sibling data and launcher", windows, (t) => {
  const f = fixture(t);
  assert.match(f.run("-Apply", "-ExpectedSha256", hash(newBytes)), /UPDATED AND HASH VERIFIED/);
  assert.deepEqual(readFileSync(f.installed), newBytes);
  const backups = readdirSync(path.join(f.install, "backup"));
  assert.equal(backups.length, 1);
  assert.deepEqual(readFileSync(path.join(f.install, "backup", backups[0], filename)), oldBytes);
  assert.equal(readFileSync(path.join(f.install, "database.sqlite"), "utf8"), "fixture data must stay");
  assert.equal(readFileSync(path.join(f.install, "start-fapaifang-collector.ps1"), "utf8"), "fixture launcher");
  assert.equal(readFileSync(path.join(f.install, "crow-desktop.runtime.json"), "utf8"), "fixture runtime configuration");
  assert.equal(readdirSync(f.install).filter((name) => name.startsWith(".observer-update-")).length, 0);
  assert.deepEqual(readdirSync(f.desktop), ["Crow.lnk"]);
  rmSync(path.join(f.desktop, "Crow.lnk"));
  assert.match(f.run("-Apply", "-ExpectedSha256", hash(newBytes)), /Already current/);
  assert.deepEqual(readdirSync(f.desktop), ["Crow.lnk"]);
  assert.equal(readdirSync(path.join(f.install, "backup")).length, 1);
});

test("wrong source hash refuses before backup or replacement", windows, (t) => {
  const f = fixture(t);
  assert.throws(() => f.run("-Apply", "-ExpectedSha256", "0".repeat(64)), /SHA-256 does not match/);
  assert.deepEqual(readFileSync(f.installed), oldBytes);
  assert.equal(readdirSync(f.install).length, 4);
  assert.deepEqual(readdirSync(f.desktop), []);
});

test("apply requires the expected hash", windows, (t) => {
  const f = fixture(t);
  assert.throws(() => f.run("-Apply"), /requires -ExpectedSha256/);
  assert.deepEqual(readFileSync(f.installed), oldBytes);
});

test("a running observer refuses replacement without stopping it", windows, (t) => {
  const f = fixture(t, true);
  assert.throws(() => f.run("-Apply", "-ExpectedSha256", hash(newBytes)), /Close the observer normally/);
  assert.deepEqual(readFileSync(f.installed), oldBytes);
});

test("missing installed exe refuses instead of creating a fresh installation", windows, (t) => {
  const f = fixture(t);
  rmSync(f.installed);
  assert.throws(() => f.run("-Apply", "-ExpectedSha256", hash(newBytes)), /Existing installation missing/);
  assert.equal(readdirSync(f.install).length, 3);
});

test("the updater has no launch, process termination, deployment or recursive deletion", () => {
  const source = readFileSync(script, "utf8");
  assert.doesNotMatch(source, /Start-Process|Stop-Process|ExecutionPolicy|Invoke-Command|\bssh\b|-Recurse/i);
  assert.match(source, /Get-Process -Name 'fapaifang_collector_desktop'/);
  assert.match(source, /ReparsePoint/);
  assert.match(source, /DriveType.*Fixed/);
  assert.match(source, /\[IO\.File\]::Replace/);
});
