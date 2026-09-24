import assert from "node:assert/strict";
import test from "node:test";
import { fetchWithTimeout, readJson } from "./desktop_http.ts";

test("HTTP errors are reported before decoding a non-JSON response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("<h1>Unavailable</h1>", { status: 503 }));
  await assert.rejects(readJson("https://api.example.invalid/status"), /^Error: 503/);
});

test("readJson narrows external arrays and scalar values at the response boundary", async (t) => {
  for (const payload of [null, [1, 2], "unexpected", { status: "ready" }]) {
    t.mock.method(globalThis, "fetch", async () => Response.json(payload));
    assert.deepEqual(await readJson("https://api.example.invalid/status"),
      payload && !Array.isArray(payload) && typeof payload === "object" ? payload : {});
  }
});

test("caller cancellation reaches fetch without being relabeled as a timeout", async (t) => {
  const caller = new AbortController();
  const reason = new Error("caller changed API origin");
  t.mock.method(globalThis, "fetch", (_url: string, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
    assert.ok(options.signal);
    options.signal.addEventListener("abort", () => reject(options.signal?.reason), { once: true });
  }));
  const pending = fetchWithTimeout("https://api.example.invalid/status", { signal: caller.signal });
  caller.abort(reason);
  await assert.rejects(pending, (error) => error === reason);
});

test("a deadline aborts the request and reports its configured duration", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(globalThis, "fetch", (_url: string, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options.signal?.addEventListener("abort", () => reject(options.signal?.reason), { once: true });
  }));
  const pending = fetchWithTimeout("https://api.example.invalid/status", {}, 2_000);
  const rejected = assert.rejects(pending, /2.*https:\/\/api\.example\.invalid\/status/);
  t.mock.timers.tick(2_000);
  await rejected;
});

test("completed requests release their deadline and caller-abort listener", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const caller = new AbortController();
  const signals: AbortSignal[] = [];
  t.mock.method(globalThis, "fetch", async (_url: string, options: RequestInit) => {
    if (options.signal) signals.push(options.signal);
    return Response.json({ ok: true });
  });
  await fetchWithTimeout("https://api.example.invalid/status", { signal: caller.signal }, 2_000);
  caller.abort();
  t.mock.timers.tick(2_000);
  assert.equal(signals.length, 1);
  assert.equal(signals[0].aborted, false);
});
