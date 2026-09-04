import { callAction } from "./desktop_actions.js";
import { isTauriRuntime, state, tryInvoke } from "./desktop_state.js";
import { $, esc, postJson } from "./desktop_shared.js";
import {
  defaultAuthChallengeUrl,
  loadOverview,
  normalizeAuthChallengeUrl,
  runtimeStateFromOverview,
} from "./desktop_collection_views.js";

export async function toggleRuntimePause() {
  const runtimeState = state.lastOverview ? runtimeStateFromOverview(state.lastOverview) : "运行中";
  if (runtimeState === "运行中") {
    const endpoint = "/api/collection/control/pause";
    $("connectionStatus").textContent = "正在暂停采集...";
    try {
      await postJson(endpoint, {});
      await callAction("reloadAll");
    } catch (error) {
      $("connectionStatus").innerHTML = `<span class="error">切换运行状态失败：${esc(error.message)}</span>`;
    }
  } else {
    await forceStartCollection();
  }
}

export async function forceStartCollection() {
  $("connectionStatus").textContent = "正在开始采集（清除待认证/暂停标记并重新尝试）...";
  try {
    await postJson("/api/collection/auth/complete", {
      source: "collector_desktop_force_start",
      refresh_cookie_snapshot: false,
    });
    await callAction("reloadAll");
  } catch (error) {
    $("connectionStatus").innerHTML = `<span class="error">强制开始采集失败：${esc(error.message)}</span>`;
  }
}

export async function openAuthChallenge() {
  const dialog = $("authChallengeDialog");
  const url = defaultAuthChallengeUrl();
  $("authChallengeUrl").value = url;
  $("authChallengeStatus").textContent = "正在打开外部认证浏览器...";
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.classList.add("open");
  }
  try {
    $("authChallengeStatus").textContent = await openAndQueueAuthChallenge(url);
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">打开外部认证浏览器失败：${esc(error.message || error)}</span>`;
  }
}

export async function openAndQueueAuthChallenge(url) {
  const targetUrl = normalizeAuthChallengeUrl(url);
  const pauseResult = await postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 });
  await loadOverview();
  let output = "";
  try {
    output = await tryInvoke("open_auth_browser", { url: targetUrl });
  } catch (_error) {
    const opened = window.open(targetUrl, "_blank", "noopener,noreferrer");
    output = opened
      ? `已在当前浏览器打开认证页面：${targetUrl}。请完成认证后回到控制台点击“我已完成认证，开始”。`
      : `当前浏览器阻止了弹窗。请手动打开认证地址：${targetUrl}`;
  }
  return [
    `采集已暂停，当前浏览器完全由人工控制：${pauseResult.runtime_state || "暂停中"}`,
    output || "已打开外部认证浏览器。请在当前详情页完成认证，不要关闭、刷新或重新导航，然后点击“我已完成认证，开始”。",
  ].join("\n");
}

export function closeAuthChallenge() {
  const dialog = $("authChallengeDialog");
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.classList.remove("open");
  }
}

export async function reloadAuthChallenge() {
  const url = normalizeAuthChallengeUrl($("authChallengeUrl").value.trim() || defaultAuthChallengeUrl());
  $("authChallengeUrl").value = url;
  $("authChallengeStatus").textContent = "正在暂停采集并打开外部认证浏览器...";
  try {
    $("authChallengeStatus").textContent = await openAndQueueAuthChallenge(url);
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">打开外部认证浏览器失败：${esc(error.message || error)}</span>`;
  }
}

export async function queueAuthChallenge() {
  const targetUrl = normalizeAuthChallengeUrl($("authChallengeUrl").value.trim() || defaultAuthChallengeUrl());
  $("authChallengeUrl").value = targetUrl;
  $("authChallengeStatus").textContent = "正在提交认证任务...";
  try {
    const result = await postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 });
    $("authChallengeStatus").textContent = `已保持人工认证模式：${result.runtime_state || "暂停中"}`;
    await loadOverview();
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">提交认证任务失败：${esc(error.message)}</span>`;
  }
}

export async function resumeAfterAuthChallenge() {
  const tauriRuntime = isTauriRuntime();
  $("authChallengeStatus").textContent = tauriRuntime
    ? "正在原地检查当前详情页并验证可复用 cookie；浏览器不会关闭或刷新..."
    : "正在通知 API 清除待认证状态...";
  try {
    if (tauriRuntime) {
      await tryInvoke("export_taobao_cookie_snapshot");
    }
    await postJson("/api/collection/auth/complete", {
      source: "collector_desktop",
      refresh_cookie_snapshot: !tauriRuntime,
    }, { timeoutMs: 10_000 });
    $("authChallengeStatus").textContent = tauriRuntime
      ? "当前详情页和可复用 cookie 均已验证，已通知 API 让 PC2 worker 继续。"
      : "已通知 API 开始采集；cookie 快照将由当前采集节点刷新。";
    closeAuthChallenge();
    await callAction("reloadAll");
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">开始失败：${esc(error.message)}</span>`;
  }
}
