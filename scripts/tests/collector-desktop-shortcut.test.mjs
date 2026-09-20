import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const script = fileURLToPath(new URL("../update-collector-desktop-shortcut.ps1", import.meta.url));
const windows = { skip: process.platform !== "win32" };
const bytes = Buffer.from("synthetic executable, never launched");
const expected = createHash("sha256").update(bytes).digest("hex");
const quote = (value) => `'${value.replaceAll("'", "''")}'`;
const powershell = (command) => execFileSync("powershell.exe", [
  "-NoProfile", "-NonInteractive", "-Command",
  `[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); $ErrorActionPreference = 'Stop'; ${command}`,
], { encoding: "utf8", timeout: 20000, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });

function fixture(t) {
  const root = mkdtempSync(path.join(tmpdir(), "crow-shortcut-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const install = path.join(root, "Crow install");
  const desktop = path.join(root, "desktop space");
  mkdirSync(install);
  mkdirSync(desktop);
  const executable = path.join(install, "fapaifang_collector_desktop.exe");
  const shortcut = path.join(desktop, "Crow.lnk");
  writeFileSync(executable, bytes);
  writeFileSync(path.join(install, "crow-desktop.runtime.json"), '{"version":1}');
  writeFileSync(path.join(install, "start-fapaifang-collector.ps1"), "legacy fixture, never execute");
  const run = (sha = expected) => JSON.parse(powershell(
    `& ${quote(script)} -InstallRoot ${quote(install)} -DesktopDirectory ${quote(desktop)} -ExpectedSha256 ${quote(sha)} | ConvertTo-Json -Compress`,
  ));
  const inspect = () => JSON.parse(powershell(
    `$s = (New-Object -ComObject WScript.Shell).CreateShortcut(${quote(shortcut)}); `
    + "[pscustomobject]@{target=$s.TargetPath;arguments=$s.Arguments;working_directory=$s.WorkingDirectory;icon=$s.IconLocation} | ConvertTo-Json -Compress",
  ));
  return { install, desktop, executable, shortcut, run, inspect };
}

test("creates a real desktop link to the verified exe with its icon and working directory", windows, (t) => {
  const f = fixture(t);
  const result = f.run();
  assert.equal(result.path, f.shortcut);
  assert.deepEqual(f.inspect(), {
    target: f.executable, arguments: "", working_directory: f.install, icon: `${f.executable},0`,
  });
});

test("refreshes one stable link and preserves unrelated desktop files", windows, (t) => {
  const f = fixture(t);
  f.run();
  powershell(`$s = (New-Object -ComObject WScript.Shell).CreateShortcut(${quote(f.shortcut)}); $s.TargetPath = 'C:\\obsolete.exe'; $s.Save()`);
  writeFileSync(path.join(f.desktop, "keep.txt"), "untouched");
  f.run();
  f.run();
  assert.equal(f.inspect().target, f.executable);
  assert.deepEqual(readdirSync(f.desktop).sort(), ["Crow.lnk", "keep.txt"]);
  assert.equal(readFileSync(path.join(f.desktop, "keep.txt"), "utf8"), "untouched");
});

test("old installations without runtime config retain their launcher", windows, (t) => {
  const f = fixture(t);
  rmSync(path.join(f.install, "crow-desktop.runtime.json"));
  f.run();
  const result = f.inspect();
  assert.match(result.target, /powershell\.exe$/i);
  assert.ok(result.arguments.includes(path.join(f.install, "start-fapaifang-collector.ps1")));
  assert.match(result.arguments, /-WindowStyle Hidden/);
});

test("a missing or unverified executable never replaces an existing shortcut", windows, (t) => {
  const f = fixture(t);
  f.run();
  const original = readFileSync(f.shortcut);
  assert.throws(() => f.run("0".repeat(64)), /SHA-256/);
  assert.deepEqual(readFileSync(f.shortcut), original);
  rmSync(f.executable);
  assert.throws(() => f.run(), /executable missing/i);
  assert.deepEqual(readFileSync(f.shortcut), original);
});

test("both update entrypoints refresh shortcuts after verifying the executable", () => {
  for (const name of ["deploy-collector-desktop-local.ps1", "update-collector-desktop-exe-only.ps1"]) {
    const source = readFileSync(fileURLToPath(new URL(`../${name}`, import.meta.url)), "utf8");
    assert.match(source, /update-collector-desktop-shortcut\.ps1/);
    assert.match(source, /-ExpectedSha256/);
  }
});
