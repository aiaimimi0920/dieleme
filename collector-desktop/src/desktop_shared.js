import { AUTO_REFRESH_INTERVAL_MS, state } from "./desktop_state.js";

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

export function formatSigned(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number}`;
}

export function formatPercent(rate) {
  const number = Number(rate);
  if (!Number.isFinite(number)) {
    return "等待数据";
  }
  return `${(number * 100).toFixed(number > 0 && number < 0.1 ? 1 : 0)}%`;
}

export function formatDurationSeconds(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    return "等待数据";
  }
  if (number < 60) {
    return `${Math.round(number)} 秒`;
  }
  const minutes = Math.floor(number / 60);
  const seconds = Math.round(number % 60);
  if (minutes < 60) {
    return seconds > 0 ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`;
  }
  const hours = Math.floor(minutes / 60);
  const remainMinutes = minutes % 60;
  return remainMinutes > 0 ? `${hours} 小时 ${remainMinutes} 分` : `${hours} 小时`;
}

export function overviewMetric(data, path) {
  const parts = String(path || "").split(".");
  let current = data && data.modules;
  for (const part of parts) {
    if (!current || typeof current !== "object") {
      return 0;
    }
    current = current[part];
  }
  const number = Number(current || 0);
  return Number.isFinite(number) ? number : 0;
}

export function formatGrowthDelta(currentValue, previousValue, elapsedMs) {
  if (previousValue === null || previousValue === undefined || !Number.isFinite(Number(previousValue))) {
    return "近60秒增长：等待下一次刷新";
  }
  const delta = Number(currentValue || 0) - Number(previousValue || 0);
  const seconds = Math.max(Number(elapsedMs || AUTO_REFRESH_INTERVAL_MS) / 1000, 1);
  const perMinute = Math.round((delta * 60) / seconds);
  return `近60秒增长：${formatSigned(delta)}（约 ${formatSigned(perMinute)}/分钟）`;
}

export function renderGrowthLine(path) {
  const currentSample = state.currentOverviewSample;
  const previousSample = state.previousOverviewSample;
  const currentValue = currentSample ? overviewMetric(currentSample.overview, path) : null;
  const previousValue = previousSample ? overviewMetric(previousSample.overview, path) : null;
  const elapsedMs =
    currentSample && previousSample
      ? currentSample.capturedAt.getTime() - previousSample.capturedAt.getTime()
      : AUTO_REFRESH_INTERVAL_MS;
  return `<div class="growth-line">${esc(formatGrowthDelta(currentValue, previousValue, elapsedMs))}</div>`;
}

export function authWatcherStatusLabel(authWatcher) {
  const status = String((authWatcher && authWatcher.status) || "").trim().toLowerCase();
  if (!authWatcher || !authWatcher.available) {
    return "未启动";
  }
  if (status === "watching") {
    return "等待自动恢复";
  }
  if (status === "completed") {
    return "已自动恢复";
  }
  if (status === "timed_out") {
    return "自动恢复超时";
  }
  return status || "待机";
}

export function authWatcherStatusClass(authWatcher) {
  const status = String((authWatcher && authWatcher.status) || "").trim().toLowerCase();
  if (!authWatcher || !authWatcher.available) {
    return "warn";
  }
  if (status === "completed") {
    return "ok";
  }
  if (status === "timed_out") {
    return "bad";
  }
  return "warn";
}

export function authWatcherStatusMessage(authWatcher, runtimeState) {
  if (!authWatcher || !authWatcher.available) {
    return "";
  }
  const status = String(authWatcher.status || "").trim().toLowerCase();
  if (status === "watching") {
    return "正在等待当前 PC1 认证恢复，可先不用手动点击“我已完成认证，开始”。";
  }
  if (status === "completed" && runtimeState === "运行中") {
    return "已检测到 PC1 认证自动恢复完成，PC2 已继续运行。";
  }
  if (status === "timed_out") {
    return "后台自动恢复已超时；如果你已经完成认证，请点击“我已完成认证，开始”兜底恢复。";
  }
  return "";
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
