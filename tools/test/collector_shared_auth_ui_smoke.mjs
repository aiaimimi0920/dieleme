// Offline fixture bridge: no production requests, cookies, or human browser.
async (page) => {
  const origin = "http://127.0.0.1:1436";
  const errors = [];
  const checks = [];
  let overviewRequests = 0;
  const check = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  await page.request.post(`${origin}/__preview/state`, { data: { scenario: "normal", reset_events: true, challenge: false } });
  await page.route("**/api/collection/overview", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    overviewRequests += 1;
    payload.status.collection_scopes = {
      seed: { challenge_id: "seed", last_request: { target_url: "https://sf.taobao.com/list/50025969.htm"
        + (overviewRequests > 1 ? "?location_code=510302&st_param=5&auction_start_seg=-1&page=18" : "") } },
      detail: { challenge_id: "detail", last_request: { target_url: "https://sf-item.taobao.com/sf_item/123456.htm" } },
    };
    return route.fulfill({ json: payload });
  });
  await page.addInitScript((base) => {
    localStorage.setItem("crow.apiBase", base);
    const pending = { phase: "pending_pc2", code: "shared_receiving", shared: true, recovery_id: "shared-auth-" + "a".repeat(32) };
    window.__nativeCalls = [];
    window.__pending = pending;
    window.__nativeResult = localStorage.getItem("crow.sharedAuth") ? pending : { phase: "ready_for_human", target_id: "selected" };
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (command, args) => {
        if (command === "default_api_base") return base;
        if (command !== "desktop_auth_action") throw new Error("Unsupported fixture command");
        window.__nativeCalls.push(args.request);
        return JSON.parse(JSON.stringify(window.__nativeResult));
      },
    };
  }, origin);
  await page.clock.install();
  await page.goto(origin);
  await page.locator("#detailAuthButton").waitFor();
  await page.locator("#detailAuthButton").click();
  await page.locator("#authChallengeReload").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "挑战页面已打开" }).waitFor();
  await page.evaluate(() => { window.__nativeResult = window.__pending; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "同一份 Cookie" }).waitFor();
  const submitted = await page.evaluate(() => window.__nativeCalls.at(-1));
  check(submitted.scope === "detail" && submitted.peer_url.startsWith("https://sf.taobao.com/list/"), "one detail completion includes link destination");
  check(submitted.peer_url.includes("location_code=510302") && submitted.peer_url.includes("page=18")
    && submitted.peer_url.includes("st_param=5"), "completion refreshes stale overview and binds actual regional page and sort");
  check(submitted.challenge_id === "detail" && submitted.peer_challenge_id === "seed", "both stage challenge identities preserved");
  check(await page.locator("#authChallengeReload").isDisabled(), "no recapture while shared handoff pending");
  await page.keyboard.press("Escape");
  const before = await page.evaluate(() => window.__nativeCalls.length);
  await page.clock.runFor(3100);
  check(await page.evaluate(() => window.__nativeCalls.length) > before, "closing dialog keeps shared queue advancing");
  await page.locator("#seedAuthButton").click();
  await page.waitForFunction(() => window.__nativeCalls.at(-1).action === "status");
  check(await page.evaluate(() => window.__nativeCalls.filter((item) => item.action === "complete").length) === 1, "other stage joins same handoff without duplicate completion");
  await page.reload();
  await page.locator("#seedAuthButton").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "同一份 Cookie" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls[0].action) === "status", "reloaded desktop resumes persisted shared receipt");
  await page.evaluate(() => {
    window.__nativeResult = { ...window.__pending, phase: "failed", code: "shared_partial",
      stage_results: { seed: { phase: "failed", code: "stage_probe_failed" }, detail: { phase: "succeeded" } } };
  });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "详情：已恢复" }).waitFor();
  check(await page.locator("#authChallengeDialog").isVisible(), "partial success stays visible and never reports both stages restored");
  await page.screenshot({ path: "output/playwright/shared-auth-partial.png" });
  check(errors.length === 0, "no browser exceptions");
  return { checks, errors };
}
