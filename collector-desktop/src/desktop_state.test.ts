import test from "node:test";
import assert from "node:assert/strict";

test("desktop API fallback stays on loopback when no browser origin is available", async () => {
  const previousWindow = globalThis.window;
  Object.assign(globalThis, { window: { location: { protocol: "file:", origin: "null" } } });
  try {
    const module = await import(`./desktop_state.ts?test=${Date.now()}`);
    assert.equal(module.defaultBrowserApiBase(), "http://127.0.0.1:8001");
  } finally {
    if (previousWindow === undefined) delete (globalThis as { window?: unknown }).window;
    else Object.assign(globalThis, { window: previousWindow });
  }
});
