import { invoke } from "@tauri-apps/api/core";

export const AUTO_REFRESH_INTERVAL_MS = 60_000;
export const REGION_REFRESH_INTERVAL_MS = 600_000;
export const DEFAULT_AUTH_CHALLENGE_URL = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1";

export function isTauriRuntime() {
  return Boolean(window.__TAURI_INTERNALS__);
}

export async function tryInvoke(command, args) {
  if (!isTauriRuntime()) {
    throw new Error("not running inside Tauri");
  }
  return invoke(command, args);
}

export function defaultBrowserApiBase() {
  if (window.location && /^https?:$/.test(window.location.protocol) && window.location.origin) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8001";
}

export const state = {
  apiBase: defaultBrowserApiBase(),
  stage: "links",
  limit: 10,
  offset: 0,
  total: 0,
  selectedAnalysisItemId: null,
  selectedAnalysisRecord: null,
  editingAnalysis: false,
  lastOverview: null,
  lastRefreshAt: null,
  previousOverviewSample: null,
  currentOverviewSample: null,
  refreshInFlight: false,
  regionRefreshInFlight: false,
  lastRegionRefreshAt: null,
  regions: [],
  selectedProvince: "",
  selectedCity: "",
  selectedLocationCode: "",
};
