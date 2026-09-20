import { callAction } from "./desktop_actions.js";
import { isTauriRuntime, state, tryInvoke } from "./desktop_state.js";
import { $, showManagedDialog, closeManagedDialog, getJson } from "./desktop_shared.js";
import { authScopeState, authScopeTarget, scopeLabel } from "./desktop_auth_scope.ts";
import { authResult, authWaitState } from "./desktop_auth_contract.ts";

let session = null;
let phase = "";
let busy = false;
let generation = 0;
let timer;
let wired = false;
let waitStartedAt = null;
const sessions = new Map();
const sharedStorageKey = "crow.sharedAuth";

function rememberShared() {
  try {
    if (phase === "pending_pc2" && session?.recovery_id?.startsWith("shared-auth-")) {
      localStorage.setItem(sharedStorageKey, JSON.stringify({ session, waitStartedAt }));
    } else localStorage.removeItem(sharedStorageKey);
  } catch { /* Storage failure must not interrupt an acknowledged handoff. */ }
}

function statusText(message) {
  $("authChallengeStatus").textContent = `${session?.recovery_id?.startsWith("shared-auth-") ? "链接与详情采集" : scopeLabel(session?.scope || "seed")}：${message}`;
}

function controls() {
  $("authChallengeReload").disabled = busy || phase === "pending_pc2";
  $("authChallengeResume").disabled = busy;
}

export function resetAuthChallenge() {
  generation += 1;
  clearTimeout(timer);
  session = null;
  sessions.clear();
  phase = "";
  busy = false;
  waitStartedAt = null;
  if ($("authChallengeDialog").open) closeManagedDialog($("authChallengeDialog"));
}

export function openAuthChallenge(scope = "seed") {
  if (busy || !["seed", "detail"].includes(scope)) return;
  if (!session) {
    try {
      const saved = JSON.parse(localStorage.getItem(sharedStorageKey) || "null");
      if (saved?.session?.api_base === state.apiBase && /^shared-auth-[a-f0-9]{32}$/.test(saved.session.recovery_id)
          && ["seed", "detail"].includes(saved.session.scope)) {
        session = saved.session;
        phase = "pending_pc2";
        waitStartedAt = saved.waitStartedAt ?? Date.now();
      }
    } catch { /* Invalid local UI metadata is ignored. */ }
  }
  if (phase === "pending_pc2" && session?.recovery_id?.startsWith("shared-auth-")) scope = session.scope;
  if (session && session.scope !== scope) {
    sessions.set(session.scope, { session, phase, waitStartedAt });
    generation += 1;
    clearTimeout(timer);
    const saved = sessions.get(scope);
    session = saved?.session || null;
    phase = saved?.phase || "";
    waitStartedAt = saved?.waitStartedAt ?? null;
  }
  const dialog = $("authChallengeDialog");
  if (!wired) {
    dialog.addEventListener("close", () => {
      if (!session?.recovery_id?.startsWith("shared-auth-")) clearTimeout(timer);
    });
    dialog.addEventListener("click", (event) => {
      const box = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) closeManagedDialog(dialog);
    });
    wired = true;
  }
  if (!session || session.api_base !== state.apiBase || ["failed", "succeeded"].includes(phase)) {
    session = { api_base: state.apiBase, scope, target_url: authScopeTarget(state.lastOverview, scope, state.selectedItemId),
      challenge_id: String(authScopeState(state.lastOverview, scope)?.challenge_id || ""),
      target_id: "", recovery_id: "", request_id: crypto.randomUUID().replaceAll("-", "") };
    phase = "";
    waitStartedAt = null;
  }
  dialog.setAttribute("aria-label", `${scopeLabel(scope)}人工认证`);
  dialog.dataset.scope = scope;
  statusText(phase === "pending_pc2" ? "等待 PC2 验证此阶段。" : "请打开挑战页面，完成后提交。");
  controls();
  showManagedDialog(dialog);
  if (phase === "pending_pc2") void run("status");
}

async function run(action) {
  if (busy || !session) return;
  const id = generation;
  const current = session;
  busy = true;
  clearTimeout(timer);
  controls();
  // Background status checks must not replace the last acknowledged stage.
  if (action !== "status") statusText(action === "open" ? "正在打开挑战页面…" : "正在验证并同步认证会话…");
  try {
    if (action === "open" || (action === "complete" && !current.recovery_id)) {
      const overview = await getJson("/api/collection/overview");
      if (id !== generation || current !== session) return;
      state.lastOverview = overview;
      if (action === "open") {
        current.target_url = authScopeTarget(overview, current.scope, state.selectedItemId);
        current.challenge_id = String(authScopeState(overview, current.scope)?.challenge_id || "");
      }
    }
    if (action === "open" && current.scope === "detail" && !current.target_url) {
      const items = await getJson("/api/collection/items?stage=links&limit=1&offset=0");
      if (id !== generation || current !== session) return;
      const item = items.items?.[0];
      current.target_url = authScopeTarget(state.lastOverview, "detail", item?.item_id || item?.id);
      if (!current.target_url) { statusText("暂无可认证的商品详情，请先选择一个商品后重试。"); return; }
    }
    if (!isTauriRuntime()) {
      if (action === "open") window.open(current.target_url, "_blank", "noopener,noreferrer");
      $("authChallengeStatus").textContent = "请使用桌面版同步认证会话；普通浏览器无法读取挑战窗口的 cookie。";
      return;
    }
    if (action === "complete") {
      const peer = current.scope === "seed" ? "detail" : "seed";
      current.peer_url = authScopeTarget(state.lastOverview, peer, state.selectedItemId);
      current.peer_challenge_id = String(authScopeState(state.lastOverview, peer)?.challenge_id || "");
      if (!current.peer_url && peer === "detail") {
        const items = await getJson("/api/collection/items?stage=links&limit=1&offset=0");
        if (id !== generation || current !== session) return;
        current.peer_url = authScopeTarget(state.lastOverview, peer, items.items?.[0]?.item_id || items.items?.[0]?.id);
      }
      if (!current.peer_url) { statusText("暂无详情验证目标，请先选择一个商品后提交；已完成的浏览器认证仍可复用。"); return; }
    }
    const response = await tryInvoke("desktop_auth_action", { request: { ...current, action } });
    if (id !== generation || current !== session) return;
    const result = authResult(response);
    phase = result.phase;
    if (typeof response.target_id === "string") current.target_id = response.target_id;
    if (typeof response.recovery_id === "string") current.recovery_id = response.recovery_id;
    if (phase === "pending_pc2" && waitStartedAt === null) waitStartedAt = Date.now();
    if (phase !== "pending_pc2") waitStartedAt = null;
    rememberShared();
    const wait = authWaitState(waitStartedAt, Date.now());
    statusText(wait.poll ? result.message : `${result.message} ${wait.hint}`);
    if (result.completed) {
      closeManagedDialog($("authChallengeDialog"));
      await callAction("reloadAll");
    } else if (phase === "pending_pc2" && wait.poll && ($("authChallengeDialog").open || response.shared)) {
      timer = setTimeout(() => void run("status"), 3000);
    }
  } catch (error) {
    if (id === generation) $("authChallengeStatus").textContent = `认证同步未完成：${error.message || error}`;
  } finally {
    if (id === generation) { busy = false; controls(); }
  }
}

export function reloadAuthChallenge() {
  if (phase === "failed") {
    session.request_id = crypto.randomUUID().replaceAll("-", "");
    session.target_url = authScopeTarget(state.lastOverview, session.scope, state.selectedItemId);
    session.challenge_id = String(authScopeState(state.lastOverview, session.scope)?.challenge_id || "");
    session.target_id = "";
    session.recovery_id = "";
    waitStartedAt = null;
  }
  return run("open");
}

export function resumeAfterAuthChallenge() {
  return run(phase === "pending_pc2" ? "status" : "complete");
}
