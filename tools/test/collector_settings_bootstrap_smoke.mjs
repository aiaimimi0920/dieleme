// Verify per-NAS drafts after the asynchronous native API configuration resolves.
async (page) => {
  const origin = "http://127.0.0.1:1436";
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  await page.addInitScript((base) => {
    const config = {
      workers: { links: 1, details: 2, analysis: 4 },
      intervals: { links: 30, details: 30, analysis: 5, links_idle: 60, details_idle: 60, analysis_idle: 60, success_delay: 6, failure_delay: 15 },
      retries: { detail_item_attempts: 3, analysis_item_attempts: 3, detail_batch_attempts: 30, analysis_batch_attempts: 20, ai_attempts: 2 },
      ai: { base_url: "https://ai.example.invalid/v1", model: "native-bootstrap-draft", timeout_seconds: 180 },
    };
    localStorage.clear();
    localStorage.setItem(`crow.collection-settings.draft.v1:${base}`, JSON.stringify({ version: 1, config, baseline: null }));
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (command) => {
        if (command === "default_api_base") return base;
        throw new Error("Unexpected native command");
      },
    };
  }, origin);
  await page.goto(origin);
  await page.locator("#items tr.item-row").first().waitFor();
  if (await page.locator('[id="setting-ai.model"]').inputValue() !== "native-bootstrap-draft") throw new Error("Native configured API did not restore its own draft");
  return { checks: ["native configured API restores its own draft after asynchronous boot"] };
}
