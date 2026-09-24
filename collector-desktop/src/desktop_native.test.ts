import assert from "node:assert/strict";
import test from "node:test";
import { isTauriRuntime, tryInvoke } from "./desktop_native.ts";

test("native bridge accepts either Tauri exposure and keeps the receiver", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  try {
    for (const exposure of ["core", "internal"]) {
      const bridge = {
        marker: exposure,
        async invoke(this: { marker: string }, command: string, args: Record<string, unknown>) {
          return { marker: this.marker, command, args };
        },
      };
      Object.defineProperty(globalThis, "window", { configurable: true, value: exposure === "core"
        ? { __TAURI__: { core: bridge } } : { __TAURI_INTERNALS__: bridge } });
      assert.equal(isTauriRuntime(), true);
      assert.deepEqual(await tryInvoke("desktop_auth_action", { request: { action: "status" } }), {
        marker: exposure, command: "desktop_auth_action", args: { request: { action: "status" } },
      });
    }
    Object.defineProperty(globalThis, "window", { configurable: true, value: { __TAURI_INTERNALS__: {} } });
    assert.equal(isTauriRuntime(), false);
    await assert.rejects(tryInvoke("desktop_auth_action"), /not running inside Tauri/);
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
