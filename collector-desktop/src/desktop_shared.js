import { state } from "./desktop_state.js";

export const $ = (id) => document.getElementById(id);
export const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
export const fmt = (value) => (value === null || value === undefined || value === "" ? "-" : esc(value));
export const statusClass = (status) =>
  status === "AI 已分析" || status === "详情已采集"
    ? "ok"
    : String(status || "").includes("失败") || String(status || "").includes("阻塞")
      ? "bad"
      : "warn";

const dialogFocus = new WeakMap();
const initializedDialogs = new WeakSet();

export function setDetailActionStatus(message, tone = "info") {
  const status = $("detailActionStatus");
  status.textContent = message;
  status.dataset.tone = tone;
  status.classList.toggle("hidden", !message);
}

export function setDetailBusy(busy) {
  $("analysisActions").setAttribute("aria-busy", String(busy));
  ["reanalysisButton", "editButton", "manualUpdateButton"].forEach((id) => {
    $(id).disabled = busy || (id === "editButton" && !state.selectedAnalysisRecord);
  });
}

export function showManagedDialog(dialog) {
  if (dialog.open || dialog.classList.contains("open")) return;
  dialogFocus.set(dialog, document.activeElement);
  if (!initializedDialogs.has(dialog)) {
    dialog.addEventListener("close", () => {
      dialog.classList.remove("open");
      if (!document.querySelector("dialog[open], dialog.open")) {
        document.body.classList.remove("modal-open");
        document.querySelector(".app-shell").inert = false;
      }
      const previous = dialogFocus.get(dialog);
      const fallback = dialog.id === "authChallengeDialog" ? $(`${dialog.dataset.scope || "seed"}AuthButton`)
        : dialog.id === "engineRestartDialog" ? $("engineRestartButton") : $("resetRegionLinks");
      (previous?.isConnected ? previous : fallback)?.focus();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeManagedDialog(dialog);
      }
      if (event.key !== "Tab") return;
      const controls = [...dialog.querySelectorAll("button, input, select, textarea, a[href]")]
        .filter((control) => !control.disabled && control.getClientRects().length);
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
  document.querySelector(".app-shell").inert = true;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.classList.add("open");
  (dialog.querySelector("[autofocus]") || dialog.querySelector("button"))?.focus();
}

export function closeManagedDialog(dialog) {
  if (typeof dialog.close === "function" && dialog.open) dialog.close();
  else {
    dialog.classList.remove("open");
    dialog.dispatchEvent(new Event("close"));
  }
}

export async function confirmRegionReset(message) {
  const dialog = $("regionResetDialog");
  if (dialog.open || dialog.classList.contains("open")) return false;
  $("regionResetDescription").textContent = message;
  dialog.returnValue = "cancel";
  const completed = new Promise((resolve) => dialog.addEventListener("close", () => {
    resolve(dialog.returnValue === "confirm");
  }, { once: true }));
  showManagedDialog(dialog);
  return completed;
}

export function apiUrl(path) {
  return `${state.apiBase.replace(/\/+$/, "")}${path}`;
}

export function formatRefreshTime(date) {
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function setAutoRefreshStatus(text) {
  $("autoRefreshStatus").textContent = text;
}

export function setRegionRefreshStatus(text) {
  $("regionRefreshStatus").textContent = text;
}

export async function fetchWithTimeout(url, options = {}, timeoutMs = 30_000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒）：${url}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function getJson(path, options = {}) {
  const response = await fetchWithTimeout(apiUrl(path), { cache: "no-store" }, options.timeoutMs || 30_000);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function postJson(path, body, options = {}) {
  const response = await fetchWithTimeout(
    apiUrl(path),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    },
    options.timeoutMs || 30_000,
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `${response.status} ${response.statusText}`);
  }
  return payload;
}
