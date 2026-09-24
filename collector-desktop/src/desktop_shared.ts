import { state } from "./desktop_state.ts";
import { element as $, escapeHtml as esc } from "./desktop_dom.ts";
import { collectionWriteRequest } from "./desktop_settings_transport.ts";
import { readJson } from "./desktop_http.ts";

export { $ };
export const fmt = (value: unknown): string => (value === null || value === undefined || value === "" ? "-" : esc(value));
export const statusClass = (status: unknown): string =>
  status === "AI 已分析" || status === "详情已采集"
    ? "ok"
    : String(status || "").includes("失败") || String(status || "").includes("阻塞")
      ? "bad"
      : "warn";

const dialogFocus = new WeakMap<HTMLDialogElement, HTMLElement | null>();
const initializedDialogs = new WeakSet<HTMLDialogElement>();

export function setDetailActionStatus(message: string, tone = "info"): void {
  const status = $("detailActionStatus");
  status.textContent = message;
  status.dataset.tone = tone;
  status.classList.toggle("hidden", !message);
}

export function setDetailBusy(busy: boolean): void {
  $("analysisActions").setAttribute("aria-busy", String(busy));
  ["reanalysisButton", "editButton", "manualUpdateButton"].forEach((id) => {
    $<HTMLButtonElement>(id).disabled = busy || (id === "editButton" && !state.selectedAnalysisRecord);
  });
}

export function showManagedDialog(dialog: HTMLDialogElement): void {
  if (dialog.open || dialog.classList.contains("open")) return;
  dialogFocus.set(dialog, document.activeElement instanceof HTMLElement ? document.activeElement : null);
  if (!initializedDialogs.has(dialog)) {
    dialog.addEventListener("close", () => {
      dialog.classList.remove("open");
      if (!document.querySelector("dialog[open], dialog.open")) {
        document.body.classList.remove("modal-open");
        $("appShell").inert = false;
      }
      const previous = dialogFocus.get(dialog);
      const fallback = dialog.id === "authChallengeDialog" ? document.getElementById(`${dialog.dataset.scope || "seed"}AuthButton`)
        : document.getElementById(dialog.id === "engineRestartDialog" ? "engineRestartButton" : "resetRegionLinks");
      (previous?.isConnected ? previous : fallback)?.focus();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeManagedDialog(dialog);
      }
      if (event.key !== "Tab") return;
      const controls = [...dialog.querySelectorAll<HTMLElement>("button, input, select, textarea, a[href]")]
        .filter((control) => !control.matches(":disabled") && control.getClientRects().length);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    });
    initializedDialogs.add(dialog);
  }
  document.body.classList.add("modal-open");
  $("appShell").inert = true;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.classList.add("open");
  (dialog.querySelector<HTMLElement>("[autofocus]") || dialog.querySelector("button"))?.focus();
}

export function closeManagedDialog(dialog: HTMLDialogElement): void {
  if (typeof dialog.close === "function" && dialog.open) dialog.close();
  else {
    dialog.classList.remove("open");
    dialog.dispatchEvent(new Event("close"));
  }
}

export async function confirmRegionReset(message: string): Promise<boolean> {
  const dialog = $<HTMLDialogElement>("regionResetDialog");
  if (dialog.open || dialog.classList.contains("open")) return false;
  $("regionResetDescription").textContent = message;
  dialog.returnValue = "cancel";
  const completed = new Promise<boolean>((resolve) => dialog.addEventListener("close", () => {
    resolve(dialog.returnValue === "confirm");
  }, { once: true }));
  showManagedDialog(dialog);
  return completed;
}

export function apiUrl(path: string): string {
  return `${state.apiBase.replace(/\/+$/, "")}${path}`;
}

export function formatRefreshTime(date: Date): string {
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function setAutoRefreshStatus(text: string): void {
  $("autoRefreshStatus").textContent = text;
}

export function setRegionRefreshStatus(text: string): void {
  $("regionRefreshStatus").textContent = text;
}

export function getJson(path: string, options: { timeoutMs?: number } = {}): Promise<Record<string, unknown>> {
  return readJson(apiUrl(path), options.timeoutMs);
}

export async function postJson(path: string, body: unknown): Promise<Record<string, unknown>> {
  const token = $<HTMLInputElement>("restartToken").value.trim();
  return collectionWriteRequest(state.apiBase, path, body || {}, token);
}
