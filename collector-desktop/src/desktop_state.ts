import { isTauriRuntime } from "./desktop_native.ts";
import { DEFAULT_API_BASE } from "./desktop_config.ts";
import type { CollectionRecord, CollectionRegion, CollectionStage } from "./desktop_collection_contract.ts";
export { DEFAULT_AUTH_CHALLENGE_URL } from "./desktop_auth_target.ts";

export function defaultBrowserApiBase(): string {
  if (!isTauriRuntime() && typeof window !== "undefined" && window.location && /^https?:$/.test(window.location.protocol) && window.location.origin) {
    return window.location.origin;
  }
  return DEFAULT_API_BASE;
}

interface DesktopState {
  apiBase: string;
  stage: CollectionStage;
  limit: number;
  offset: number;
  total: number;
  itemsRequestId: number;
  overviewRequestId: number;
  regionsRequestId: number;
  refreshRequestId: number;
  detailRequestId: number;
  selectedItemId: string | null;
  selectedAnalysisItemId: string | null;
  selectedAnalysisRecord: CollectionRecord | null;
  editingAnalysis: boolean;
  lastOverview: CollectionRecord | null;
  lastRefreshAt: Date | null;
  refreshInFlight: boolean;
  lastRegionRefreshAt: Date | null;
  regions: CollectionRegion[];
  selectedProvince: string;
  selectedCity: string;
  selectedLocationCode: string;
}

export const state: DesktopState = {
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
  lastRegionRefreshAt: null,
  regions: [],
  selectedProvince: "",
  selectedCity: "",
  selectedLocationCode: "",
};
