import { installedControlOrigin, installedRestartRequest } from "./desktop_settings_transport.ts";
import { object } from "./desktop_overview.ts";

type Controls = {
  apiBase: () => string;
  reload: () => Promise<void>;
  showDialog: (dialog: HTMLDialogElement) => void;
};
let controls: Controls;
let busy = false;
let retryRequest: { base: string; id: string } | null = null;
let installedOrigin: string | null = null;
let statusBusy = false;
let statusTimer: ReturnType<typeof setTimeout> | undefined;

function element<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing control: ${id}`);
  return node as T;
}

function notice(message: string): void {
  const node = element("overviewNotice");
  node.textContent = message;
  node.classList.remove("hidden");
}

export function updateRuntimeControls(): void {
  const token = element<HTMLInputElement>("restartToken").value.trim();
  const button = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
  if (button) button.disabled = busy || button.dataset.available !== "true" || !(installedOrigin || token);
  const toggle = document.getElementById("runtimePauseButton") as HTMLButtonElement | null;
  if (toggle) toggle.disabled = busy;
}

export function initializeRuntimeControls(options: Controls): void {
  controls = options;
  element("restartToken").addEventListener("input", updateRuntimeControls);
}

export async function refreshEngineRestartStatus(): Promise<void> {
  if (statusBusy || !document.getElementById("engineRestartButton")) return;
  statusBusy = true;
  const base = controls.apiBase();
  try {
    installedOrigin = await installedControlOrigin();
    if (!installedOrigin) return;
    const status = await installedRestartRequest(installedOrigin);
    if (base !== controls.apiBase()) return;
    const request = object(status.request);
    const labels: Record<string, string> = {
      requested: "等待 PC2 接收", restarting: "PC2 正在重启", succeeded: "PC2 采集 Worker 已重启",
      failed: "重启失败，请检查 PC2", expired: "重启请求已过期", unknown: "重启结果未确认，请检查 PC2",
    };
    const blocked = ["requested", "restarting", "unknown"].includes(String(request.status));
    const button = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
    if (button) button.dataset.available = String(status.available === true && !blocked);
    const hint = document.getElementById("engineRestartStatus");
    if (hint) hint.textContent = labels[String(request.status)] || (status.available ? "PC2 控制器已连接" : "PC2 控制器未连接");
  } catch {
    if (base !== controls.apiBase()) return;
    installedOrigin = null;
    const button = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
    if (button) button.dataset.available = "false";
    const hint = document.getElementById("engineRestartStatus");
    if (hint) hint.textContent = "安全重启通道暂不可用，正在重新连接";
  } finally {
    statusBusy = false;
    updateRuntimeControls();
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => void refreshEngineRestartStatus(), 5_000);
  }
}

async function post(base: string, action: string, payload: object, token = ""): Promise<Record<string, unknown>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["X-FAPAI-Control-Token"] = token;
    const response = await fetch(`${base.replace(/\/$/, "")}/api/collection/control/${action}`, {
      method: "POST", headers, body: JSON.stringify(payload), signal: controller.signal, redirect: "error",
    });
    const result: unknown = await response.json();
    const record = result && typeof result === "object" ? result as Record<string, unknown> : {};
    if (!response.ok || record.ok === false) throw new Error(String(record.message || record.error || `HTTP ${response.status}`));
    return record;
  } finally { clearTimeout(timer); }
}

export async function toggleRuntimePause(): Promise<void> {
  if (busy) return;
  const action = element<HTMLButtonElement>("runtimePauseButton").dataset.action || "pause";
  const base = controls.apiBase();
  busy = true;
  updateRuntimeControls();
  try {
    await post(base, action, {});
    if (base === controls.apiBase()) await controls.reload();
  } catch (error) {
    if (base === controls.apiBase()) notice(`切换运行状态失败：${error instanceof Error ? error.message : String(error)}`);
  }
  finally { busy = false; updateRuntimeControls(); }
}

export async function requestEngineRestart(): Promise<void> {
  if (busy || element<HTMLButtonElement>("engineRestartButton").disabled) return;
  const base = controls.apiBase();
  const token = element<HTMLInputElement>("restartToken").value.trim();
  const origin = installedOrigin;
  const dialog = element<HTMLDialogElement>("engineRestartDialog");
  busy = true;
  updateRuntimeControls();
  dialog.returnValue = "cancel";
  const decision = new Promise<string>((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue), { once: true }));
  controls.showDialog(dialog);
  try {
    if (await decision !== "confirm" || base !== controls.apiBase()) return;
    retryRequest = retryRequest?.base === base ? retryRequest : { base, id: crypto.randomUUID() };
    const result = origin
      ? await installedRestartRequest(origin, retryRequest.id)
      : await post(base, "restart", { request_id: retryRequest.id }, token);
    retryRequest = null;
    if (base !== controls.apiBase()) return;
    await controls.reload();
    await refreshEngineRestartStatus();
    notice(result.warning ? String(result.warning) : "重启请求已提交 NAS，执行结果以状态栏中的 PC2 回执为准；提交不代表重启完成。");
  } catch (error) {
    if (base === controls.apiBase()) notice(`重启请求未确认：${error instanceof Error ? error.message : String(error)}。请先刷新状态；重试会复用请求编号。`);
  } finally {
    busy = false;
    updateRuntimeControls();
    const restart = document.getElementById("engineRestartButton") as HTMLButtonElement | null;
    if (base === controls.apiBase()) (restart?.disabled ? document.getElementById("runtimePauseButton") : restart)?.focus();
  }
}
