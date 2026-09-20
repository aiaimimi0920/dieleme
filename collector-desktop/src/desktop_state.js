import { invoke } from "@tauri-apps/api/core";
export { DEFAULT_AUTH_CHALLENGE_URL } from "./desktop_auth_target.ts";

export const AUTO_REFRESH_INTERVAL_MS = 60_000;
export const REGION_REFRESH_INTERVAL_MS = 600_000;

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
  if (!isTauriRuntime() && window.location && /^https?:$/.test(window.location.protocol) && window.location.origin) {
    return window.location.origin;
  }
  return "http://192.168.15.200:8001";
}

export const state = {
  apiBase: defaultBrowserApiBase(),
  stage: "links",
  limit: 10,
  offset: 0,
  total: 0,
  itemsRequestId: 0,
  overviewRequestId: 0,
  regionsRequestId: 0,
  refreshRequestId: 0,
  detailRequestId: 0,
  selectedItemId: null,
  selectedAnalysisItemId: null,
  selectedAnalysisRecord: null,
  editingAnalysis: false,
  lastOverview: null,
  lastRefreshAt: null,
  refreshInFlight: false,
  regionRefreshInFlight: false,
  lastRegionRefreshAt: null,
  regions: [],
  selectedProvince: "",
  selectedCity: "",
  selectedLocationCode: "",
};
