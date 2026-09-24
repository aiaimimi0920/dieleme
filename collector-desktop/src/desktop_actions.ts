import type { AuthScope } from "./desktop_auth_scope.ts";
import type { RefreshOptions } from "./desktop_collection_contract.ts";

interface DesktopActions {
  hideDetailPanel: () => void;
  loadItems: () => Promise<void>;
  loadOverview: () => Promise<boolean>;
  openAuthChallenge: (scope?: AuthScope) => void;
  reloadAll: (options?: RefreshOptions) => Promise<void>;
  reloadAfterDetailAction: (options: { requestId: number; includeOverview?: boolean }) => Promise<void>;
  toggleRuntimePause: () => Promise<void>;
  requestEngineRestart: () => Promise<void>;
}

let actions: DesktopActions | undefined;

export function registerActions(nextActions: DesktopActions): void {
  actions = nextActions;
}

export function callAction<K extends keyof DesktopActions>(name: K, ...args: Parameters<DesktopActions[K]>): ReturnType<DesktopActions[K]> {
  const action = actions?.[name];
  if (typeof action !== "function") {
    throw new Error(`desktop action is not registered: ${name}`);
  }
  const invoke = action as (...values: Parameters<DesktopActions[K]>) => ReturnType<DesktopActions[K]>;
  return invoke(...args);
}
