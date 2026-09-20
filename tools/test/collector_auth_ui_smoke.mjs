// Synthetic native bridge only; never opens production browser or sends cookies.
async (page) => {
  const origin = "http://127.0.0.1:1436";
  const checks = [];
  const errors = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  await page.request.post(`${origin}/__preview/state`, { data: { scenario: "normal", reset_events: true, challenge: false } });
  await page.route("**/api/collection/overview", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.status.captcha_solver.last_request = { target_url: "https://sf-item.taobao.com/sf_item/123456.htm" };
    return route.fulfill({ json: payload });
  });
  await page.addInitScript((base) => {
    localStorage.setItem("crow.apiBase", base);
    window.__nativeCalls = [];
    window.__nativeResult = { phase: "ready_for_human", target_id: "fixture-selected" };
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (command, args) => {
        if (command === "default_api_base") return base;
        if (command !== "desktop_auth_action") throw new Error(`Unexpected native command: ${command}`);
        window.__nativeCalls.push(args.request);
        if (window.__nativeReject) throw new Error("synthetic bridge unavailable");
        if (window.__nativeHold) await new Promise((resolve) => { window.__releaseNative = resolve; });
        return JSON.parse(JSON.stringify(window.__nativeResult));
      },
    };
  }, origin);
  await page.setViewportSize({ width: 1120, height: 760 });
  await page.clock.install();
  await page.goto(origin);
  await page.locator("#items tr.item-row").first().waitFor();
  check(await page.locator("#authButton").isEnabled(), "native auth can start without a reported PC2 challenge");
  await page.locator("#authButton").click();
  const dialog = page.locator("#authChallengeDialog");
  check((await dialog.locator("button").allTextContents()).map((text) => text.trim()).join() === "打开挑战页面,已完成挑战", "exactly two auth buttons");
  check(await dialog.locator("h1,h2,h3,input,iframe").count() === 0, "no secondary headings descriptions URL editor or embedded challenge");
  check(await page.evaluate(() => window.__nativeCalls.length) === 0, "dialog itself never opens browser or pauses collection");
  await page.screenshot({ path: "output/playwright/crow-auth-dialog.png" });
  await page.locator("#authChallengeReload").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "挑战页面已打开" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls[0].action) === "open", "explicit open reaches native bridge");
  check(await page.evaluate(() => window.__nativeCalls[0].target_url) === "https://sf-item.taobao.com/sf_item/123456.htm", "detail challenge opens its actual item, not an unrelated list");
  await page.evaluate(() => { window.__nativeResult = { phase: "pending_human", code: "session_not_reusable", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "尚未通过复用验证" }).waitFor();
  check(await dialog.isVisible(), "unverified session stays open without false start failure");
  check(await page.evaluate(() => window.__nativeCalls[1].target_id) === "fixture-selected", "completion binds browser target identity");
  await page.evaluate(() => { window.__nativeResult = { phase: "pending_pc2", code: "pc2_receiving", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "等待 PC2" }).waitFor();
  check(await dialog.isVisible() && await page.locator("#authChallengeReload").isDisabled(), "submitted snapshot waits for PC2, cannot reopen mid-transfer");
  const waitingText = await page.locator("#authChallengeStatus").textContent();
  await page.evaluate(() => { window.__nativeHold = true; });
  await page.locator("#authChallengeResume").click();
  check(await page.locator("#authChallengeStatus").textContent() === waitingText, "status query preserves acknowledged stage instead of flashing receiving text");
  await page.evaluate(() => { window.__nativeHold = false; window.__releaseNative(); });
  await page.waitForFunction(() => !document.getElementById("authChallengeResume").disabled);
  for (const [code, text] of [["pc2_importing", "正在导入会话"], ["pc2_restarting", "正在重启认证浏览器"]]) {
    await page.evaluate((code) => { window.__nativeResult = { phase: "pending_pc2", code, recovery_id: "fixture-recovery" }; }, code);
    await page.locator("#authChallengeResume").click();
    await page.locator("#authChallengeStatus").filter({ hasText: text }).waitFor();
    check(await dialog.isVisible(), `${code} is acknowledged without false completion`);
  }
  await page.evaluate(() => { window.__nativeReject = true; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "认证同步未完成" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).action) === "status", "pending retry polls status instead of recapturing");
  await page.evaluate(() => { window.__nativeReject = false; window.__nativeResult = { phase: "pending_pc2", code: "pc2_verifying", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "正在确认采集恢复" }).waitFor();
  check(await dialog.isVisible(), "PC2 imported cookies is not yet success");
  await page.screenshot({ path: "output/playwright/crow-auth-pending.png" });
  await page.keyboard.press("Escape");
  await page.locator("#authButton").click();
  await page.locator("#authChallengeStatus").filter({ hasText: "正在确认采集恢复" }).waitFor();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).action) === "status", "reopened dialog preserves recovery identity");
  const beforeLongWait = await page.evaluate(() => window.__nativeCalls.length);
  await page.clock.runFor(300_000);
  check(await page.evaluate(() => window.__nativeCalls.length) > beforeLongWait + 95, "long PC2 verification keeps polling instead of silently stopping after 90 attempts");
  await page.clock.runFor(610_000);
  await page.locator("#authChallengeStatus").filter({ hasText: "已停止自动查询" }).waitFor();
  const afterLimit = await page.evaluate(() => window.__nativeCalls.length);
  await page.clock.runFor(60_000);
  check(await page.evaluate(() => window.__nativeCalls.length) === afterLimit, "automatic polling stops at the wall-clock limit");
  await page.locator("#authChallengeResume").click();
  check(await page.evaluate(() => window.__nativeCalls.at(-1).action) === "status", "manual query after timeout never republishes cookies");
  check(await dialog.isVisible(), "polling timeout is neither server failure nor success");
  await page.evaluate(() => { window.__nativeResult = { phase: "succeeded", recovery_id: "fixture-recovery" }; });
  await page.locator("#authChallengeResume").click();
  await page.locator("#authChallengeDialog:not([open])").waitFor({ state: "attached" });
  check(!await dialog.isVisible(), "only confirmed recovery closes dialog");
  const events = (await (await page.request.get(`${origin}/__preview/state`)).json()).events;
  check(!events.some((event) => /control\/pause|auth\/complete|report_captcha/.test(event.path)), "no fake resume or background solver HTTP calls");
  check(errors.length === 0, `no browser exceptions: ${errors.join("; ")}`);
  return { checks, browserErrors: errors };
}
