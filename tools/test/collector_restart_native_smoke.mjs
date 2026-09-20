// Playwright CLI run-code: offline native bridge fixture, no production calls.
async (page) => {
  const origin = "http://127.0.0.1:1436";
  const errors = [];
  const checks = [];
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().route("**/*", (route) => route.request().url().startsWith(origin + "/") ? route.continue() : route.abort());
  await page.addInitScript(() => {
    const fixture = { calls: [], request: null, failPost: false };
    window.restartFixture = fixture;
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      if (command !== "desktop_settings_action") throw new Error("Unexpected native command");
      fixture.calls.push(args.request);
      const { action, body } = args.request;
      if (action === "config") return { ok: true, configured: true, origin: "https://nas.example.invalid:18443" };
      if (action === "get") return { ok: true, available: false, effective: null };
      if (action === "restart") {
        fixture.request = { id: body.request_id, status: "requested" };
        if (fixture.failPost) throw new Error("Synthetic lost response");
        return { ok: true, request: fixture.request };
      }
      if (action === "restart_status") return { ok: true, available: true, request: fixture.request };
      throw new Error("Unexpected action");
    } } };
  });
  await page.request.post(origin + "/__preview/state", { data: { reset_events: true, scenario: "normal", restart: { available: false } } });
  await page.goto(origin);
  const button = page.locator("#engineRestartButton");
  await page.locator("#engineRestartButton:not([disabled])").waitFor();
  check(await button.textContent() === "重启 PC2 采集", "explicit PC2 restart button");
  check(await page.locator("#restartToken").inputValue() === "", "installed credentials require no manual token");
  await button.click();
  await page.locator('#engineRestartDialog button[value="cancel"]').click();
  check(await page.evaluate(() => !window.restartFixture.calls.some((r) => r.action === "restart")), "cancel never restarts");
  await button.click();
  await page.locator('#engineRestartDialog button[value="confirm"]').click();
  await page.locator("#engineRestartStatus").filter({ hasText: "等待 PC2 接收" }).waitFor();
  check(await button.isDisabled(), "pending receipt disables duplicate submission");
  check(await page.evaluate(() => window.restartFixture.calls.filter((r) => r.action === "restart").length === 1), "one native restart");
  const events = await (await page.request.get(origin + "/__preview/state")).json();
  check(!events.events.some((r) => r.path.endsWith("/restart")), "restart never uses plaintext data API");
  await page.evaluate(() => { window.restartFixture.request.status = "succeeded"; });
  await page.locator("#engineRestartStatus").filter({ hasText: "PC2 采集 Worker 已重启" }).waitFor({ timeout: 10000 });
  check(await button.isEnabled(), "success requires controller receipt");
  await page.evaluate(() => { window.restartFixture.failPost = true; });
  await button.click();
  await page.locator('#engineRestartDialog button[value="confirm"]').click();
  await page.locator("#overviewNotice").filter({ hasText: "重启请求未确认" }).waitFor();
  await page.locator("#engineRestartStatus").filter({ hasText: "等待 PC2 接收" }).waitFor({ timeout: 10000 });
  check(await button.isDisabled(), "lost POST response is recovered by status polling");
  await page.setViewportSize({ width: 1120, height: 760 });
  await page.screenshot({ path: "output/playwright/crow-pc2-restart/desktop.png", fullPage: true });
  await page.setViewportSize({ width: 720, height: 760 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "narrow viewport has no horizontal overflow");
  check(errors.length === 0, "no browser errors");
  return { checks, errors };
}
