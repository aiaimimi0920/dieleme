import assert from "node:assert/strict";
import test from "node:test";
import { initializeRuntimeControls, refreshEngineRestartStatus, toggleRuntimePause } from "./desktop_runtime_controls.ts";

test("idle refreshes are throttled and pending operations reuse the cached native origin", async (context) => {
  context.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  const calls: string[] = [];
  let status = "succeeded";
  const node = { value: "", disabled: false, dataset: {}, textContent: "", addEventListener() {}, classList: { remove() {} } };
  Object.defineProperty(globalThis, "document", { configurable: true, value: { getElementById: () => node } });
  Object.defineProperty(globalThis, "window", { configurable: true, value: { __TAURI_INTERNALS__: {
    invoke: async (_name: string, args: { request: { action: string } }) => {
      calls.push(args.request.action);
      return { ok: true, configured: true, origin: "https://nas.example.invalid", available: true, request: { status } };
    },
  } } });
  try {
    initializeRuntimeControls({ apiBase: () => "https://nas.example.invalid", reload: async () => {}, showDialog: () => {} });
    await refreshEngineRestartStatus();
    for (let tick = 0; tick < 5; tick++) await refreshEngineRestartStatus();
    assert.deepEqual(calls, ["config", "restart_status"]);
    status = "requested";
    await refreshEngineRestartStatus(true);
    assert.deepEqual(calls, ["config", "restart_status", "restart_status"]);
    context.mock.timers.tick(5_000);
    await new Promise<void>((resolve) => setImmediate(resolve));
    assert.equal(calls.filter((action) => action === "restart_status").length, 3);
    assert.equal(calls.filter((action) => action === "config").length, 1);
  } finally {
    context.mock.timers.reset();
    Reflect.deleteProperty(globalThis, "window");
    Reflect.deleteProperty(globalThis, "document");
  }
});

test("runtime toggle uses the native configured origin without exposing credentials to fetch", async () => {
  const calls: Record<string, unknown>[] = [];
  let reloads = 0;
  const node = { value: "", disabled: false, dataset: { action: "pause" }, textContent: "",
    addEventListener() {}, classList: { remove() {} } };
  const oldFetch = globalThis.fetch;
  Object.defineProperty(globalThis, "document", { configurable: true, value: { getElementById: () => node } });
  Object.defineProperty(globalThis, "window", { configurable: true, value: { __TAURI_INTERNALS__: {
    invoke: async (_name: string, args: { request: Record<string, unknown> }) => {
      calls.push(args.request);
      return { ok: true, configured: true, origin: "https://control.example.invalid" };
    },
  } } });
  globalThis.fetch = async () => { throw new Error("Native operation must not use browser fetch"); };
  try {
    initializeRuntimeControls({ apiBase: () => "http://nas.example.invalid", reload: async () => { reloads++; }, showDialog: () => {} });
    await toggleRuntimePause();
    assert.deepEqual(calls, [{ action: "config" }, { action: "pause", origin: "https://control.example.invalid", body: {} }]);
    assert.equal(reloads, 1);
    node.dataset.action = "restart/poll";
    await toggleRuntimePause();
    assert.equal(calls.length, 2);
    assert.equal(reloads, 1);
  } finally {
    globalThis.fetch = oldFetch;
    Reflect.deleteProperty(globalThis, "window");
    Reflect.deleteProperty(globalThis, "document");
  }
});
