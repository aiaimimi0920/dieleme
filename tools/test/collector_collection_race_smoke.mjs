// Playwright CLI run-code --filename contract. Offline fixture server only.
async (page) => {
  const origin = "http://127.0.0.1:1436";
  const checks = [];
  const check = (value, name) => { if (!value) throw new Error(name); checks.push(name); };
  await page.request.post(`${origin}/__preview/state`, { data: { scenario: "normal", growth: [0, 0, 0], challenge: true, restart: { available: true, request: null } } });
  await page.goto(origin);
  await page.locator("#items tr.item-row").first().waitFor();
  await page.locator('[data-stage="analysis"]').click();
  await page.locator("#items tr.item-row").first().filter({ hasText: "AI 已分析" }).waitFor();
  let releaseRegion;
  let regionEntered;
  const regionGate = new Promise((resolve) => { releaseRegion = resolve; });
  const regionReady = new Promise((resolve) => { regionEntered = resolve; });
  const regionRoute = async (route) => {
    regionEntered();
    await regionGate;
    await route.fulfill({ json: { regions: [{ province: "STALE_REGION", city: "old", district: "old", location_code: "999999" }] } });
  };
  await page.route("**/api/collection/regions?stage=links", regionRoute);
  await page.locator('[data-stage="links"]').click();
  await regionReady;
  await page.locator('[data-stage="details"]').click();
  await page.locator("#items tr.item-row").first().filter({ hasText: "详情已采集" }).waitFor();
  releaseRegion();
  await page.waitForTimeout(250);
  check(!(await page.locator("#provinceTabs").textContent()).includes("STALE_REGION"), "late links regions cannot replace current details regions");
  await page.unroute("**/api/collection/regions?stage=links", regionRoute);
  let releaseOverview;
  let overviewEntered;
  const overviewGate = new Promise((resolve) => { releaseOverview = resolve; });
  const overviewReady = new Promise((resolve) => { overviewEntered = resolve; });
  let first = true;
  const overviewRoute = async (route) => {
    if (!first) return route.continue();
    first = false;
    overviewEntered();
    await overviewGate;
    await route.fulfill({ json: { runtime_state: "STALE_OVERVIEW", modules: { links: { unique_items: 99999999 } } } });
  };
  await page.route("**/api/collection/overview", overviewRoute);
  await page.locator("#refresh").click();
  await overviewReady;
  await page.locator("#openSettings").click();
  await page.locator("#restartToken").fill("offline-fixture-operator-token-00001");
  await page.locator("#apiBase").fill(`${origin}/`);
  await page.locator("#applyApiBase").click();
  await page.locator("#connectionStatus").filter({ hasText: `已连接 ${origin}/` }).waitFor();
  releaseOverview();
  await page.waitForTimeout(250);
  check(await page.locator("#restartToken").inputValue() === "", "changing API clears restart credential");
  await page.locator("#openCollection").click();
  check(!(await page.locator("#cards").textContent()).includes("STALE_OVERVIEW"), "old API overview cannot overwrite fresh state");
  check((await page.locator(".metric-card .value").first().textContent()) === "3200", "old response cannot pollute unique counter snapshot");
  check(await page.locator("#refresh").isEnabled(), "superseded refresh does not strand refresh controls");
  await page.unroute("**/api/collection/overview", overviewRoute);
  return { checks };
}
