import "./styles.css";
import { registerActions } from "./desktop_actions.js";
import {
  AUTO_REFRESH_INTERVAL_MS,
  REGION_REFRESH_INTERVAL_MS,
  defaultBrowserApiBase,
  state,
  tryInvoke,
} from "./desktop_state.js";
import { mountTemplate } from "./desktop_template.js";
import { $, esc, formatRefreshTime, setAutoRefreshStatus } from "./desktop_shared.js";
import { hideDetailPanel, loadItems, loadOverview, requestReanalysis, startManualEdit, cancelManualEdit, submitManualUpdate } from "./desktop_collection_views.js";
import { loadRegions, resetSelectedRegionLinks } from "./desktop_regions.js";
import { closeAuthChallenge, openAuthChallenge, queueAuthChallenge, reloadAuthChallenge, resumeAfterAuthChallenge, toggleRuntimePause } from "./desktop_auth.js";

mountTemplate();

export async function reloadAll(options = {}) {
  const silent = Boolean(options && options.silent);
  if (state.refreshInFlight) {
    if (!silent) {
      setAutoRefreshStatus("刷新已在进行中");
    }
    return;
  }
  state.refreshInFlight = true;
  setAutoRefreshStatus(silent ? "自动刷新中..." : "刷新中...");
  try {
    await loadOverview();
    await loadItems();
    state.lastRefreshAt = new Date();
    setAutoRefreshStatus(`最后刷新 ${formatRefreshTime(state.lastRefreshAt)}；每 60 秒自动刷新`);
  } catch (error) {
    $("connectionStatus").innerHTML = `<span class="error">连接失败：${esc(error.message)}。请确认 fapaifang-api 在 ${esc(state.apiBase)} 运行。</span>`;
    $("listStatus").textContent = "";
    setAutoRefreshStatus(`刷新失败；每 60 秒自动重试`);
  } finally {
    state.refreshInFlight = false;
  }
}

registerActions({
  hideDetailPanel,
  loadItems,
  loadOverview,
  openAuthChallenge,
  reloadAll,
  toggleRuntimePause,
});

document.querySelectorAll("button[data-stage]").forEach((button) =>
  button.addEventListener("click", async () => {
    document.querySelectorAll("button[data-stage]").forEach((candidate) => candidate.classList.remove("active"));
    button.classList.add("active");
    state.stage = button.dataset.stage;
    state.offset = 0;
    hideDetailPanel();
    await loadRegions();
    await loadItems();
  }),
);

$("limit").addEventListener("change", async (event) => {
  state.limit = Number(event.target.value || 100);
  state.offset = 0;
  await loadItems();
});
$("refresh").addEventListener("click", reloadAll);
$("prev").addEventListener("click", async () => {
  state.offset = Math.max(0, state.offset - state.limit);
  await loadItems();
});
$("next").addEventListener("click", async () => {
  if (state.offset + state.limit < state.total) {
    state.offset += state.limit;
  }
  await loadItems();
});
$("applyApiBase").addEventListener("click", async () => {
  state.apiBase = $("apiBase").value.trim() || defaultBrowserApiBase();
  state.offset = 0;
  state.selectedProvince = "";
  state.selectedCity = "";
  state.selectedLocationCode = "";
  state.regions = [];
  state.previousOverviewSample = null;
  state.currentOverviewSample = null;
  await loadRegions();
  await reloadAll();
});
$("reanalysisButton").addEventListener("click", requestReanalysis);
$("editButton").addEventListener("click", async () => {
  if (state.editingAnalysis) {
    await cancelManualEdit();
  } else {
    startManualEdit();
  }
});
$("manualUpdateButton").addEventListener("click", submitManualUpdate);
$("authChallengeClose").addEventListener("click", closeAuthChallenge);
$("authChallengeReload").addEventListener("click", reloadAuthChallenge);
$("authChallengeQueue").addEventListener("click", queueAuthChallenge);
$("authChallengeResume").addEventListener("click", resumeAfterAuthChallenge);
$("refreshRegions").addEventListener("click", () => loadRegions({ silent: false }));
$("resetRegionLinks").addEventListener("click", resetSelectedRegionLinks);

try {
  state.apiBase = await tryInvoke("default_api_base");
  $("apiBase").value = state.apiBase;
} catch (_error) {
  state.apiBase = defaultBrowserApiBase();
  $("apiBase").value = state.apiBase;
}

await loadRegions();
await reloadAll();
setInterval(() => reloadAll({ silent: true }), AUTO_REFRESH_INTERVAL_MS);
setInterval(() => loadRegions({ silent: true }), REGION_REFRESH_INTERVAL_MS);
