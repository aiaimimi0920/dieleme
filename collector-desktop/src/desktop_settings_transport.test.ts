import assert from "node:assert/strict";
import test from "node:test";
import { collectionWriteRequest, installedControlOrigin, installedRestartRequest, settingsRequest } from "./desktop_settings_transport.ts";

test("native settings uses the configured origin without forwarding the browser token", async () => {
  const calls: unknown[] = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: { __TAURI_INTERNALS__: {
    invoke: async (name: string, args: unknown) => {
      calls.push({ name, args });
      return { ok: true, configured: true, origin: "https://nas.example.invalid:18443", revision: 7 };
    },
  } } });
  assert.equal(await installedControlOrigin(), "https://nas.example.invalid:18443");
  assert.equal((await settingsRequest("https://nas.example.invalid:18443", "", "synthetic-browser-token")).revision, 7);
  assert.deepEqual(calls[1], { name: "desktop_settings_action", args: { request: {
    action: "get", origin: "https://nas.example.invalid:18443", body: null,
  } } });
  assert(!JSON.stringify(calls).includes("synthetic-browser-token"));
  await assert.rejects(settingsRequest("http://remote.invalid", "", "secret"));
  await assert.rejects(settingsRequest("https://nas.example.invalid", "/poll", "secret"));
  assert.equal(calls.length, 2);
});

test("browser fallback reports an uninstalled endpoint before parsing a non-JSON body", async () => {
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("not installed", { status: 404 });
  try {
    await assert.rejects(settingsRequest("http://127.0.0.1:1436", "", "synthetic-token"), /线上尚未启用/);
  } finally {
    globalThis.fetch = original;
    Reflect.deleteProperty(globalThis, "window");
  }
});

test("restart requests share the native queue with settings and never expose credentials", async () => {
  const calls: Record<string, unknown>[] = [];
  let active = 0;
  Object.defineProperty(globalThis, "window", { configurable: true, value: { __TAURI_INTERNALS__: {
    invoke: async (_: string, args: Record<string, unknown>) => {
      assert.equal(active++, 0);
      calls.push(args);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active--;
      return { ok: true };
    },
  } } });
  const origin = "https://nas.example.invalid:18443";
  await Promise.all([settingsRequest(origin, "", "private-browser-token"), installedRestartRequest(origin), installedRestartRequest(origin, "restart-fixture-001")]);
  assert.deepEqual(calls[2], { request: { action: "restart", origin, body: { request_id: "restart-fixture-001" } } });
  assert.equal((calls[1].request as Record<string, unknown>).action, "restart_status");
  assert(!JSON.stringify(calls).includes("private-browser-token"));
  Reflect.deleteProperty(globalThis, "window");
});

test("collection edits use the installed control origin and never forward a browser token", async () => {
  const calls: Record<string, unknown>[] = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: { __TAURI_INTERNALS__: {
    invoke: async (_: string, args: Record<string, unknown>) => {
      calls.push(args);
      return { ok: true, configured: true, origin: "https://configured.invalid:18443" };
    },
  } } });
  try {
    const body = { item_id: "fixture", updates: { phone: "0012345" } };
    await collectionWriteRequest("http://read-api.invalid:8001", "/api/collection/item/manual_update", body, "browser-private-token");
    assert.deepEqual(calls[1], { request: { action: "manual_update", origin: "https://configured.invalid:18443", body } });
    assert(!JSON.stringify(calls).includes("browser-private-token"));
    await assert.rejects(collectionWriteRequest("https://configured.invalid", "https://evil.invalid/write", {}));
    assert.equal(calls.length, 2);
  } finally { Reflect.deleteProperty(globalThis, "window"); }
});

test("browser collection writes fail before network I/O without credentials or over remote HTTP", async () => {
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  const original = globalThis.fetch;
  const calls: { url: string; options?: RequestInit }[] = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return new Response('{"ok":true}');
  };
  const path = "/api/collection/item/reanalyze";
  try {
    await assert.rejects(collectionWriteRequest("https://configured.invalid", path, {}));
    await assert.rejects(collectionWriteRequest("http://remote.invalid", path, {}, "fixture-token"));
    assert.equal(calls.length, 0);
    await collectionWriteRequest("http://127.0.0.1:1436", path, { item_id: "fixture" }, "fixture-token");
    assert.equal(calls[0].url, "http://127.0.0.1:1436" + path);
    assert.equal(calls[0].options?.redirect, "error");
    assert.equal(new Headers(calls[0].options?.headers).get("X-FAPAI-Control-Token"), "fixture-token");
    globalThis.fetch = async () => new Response("not JSON", { status: 403 });
    await assert.rejects(collectionWriteRequest("http://127.0.0.1:1436", path, {}, "fixture-token"), /HTTP 403/);
  } finally { globalThis.fetch = original; Reflect.deleteProperty(globalThis, "window"); }
});
