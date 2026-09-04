import { callAction } from "./desktop_actions.js";
import { DEFAULT_AUTH_CHALLENGE_URL, state } from "./desktop_state.js";
import {
  $,
  authWatcherStatusClass,
  authWatcherStatusLabel,
  authWatcherStatusMessage,
  esc,
  fmt,
  formatDurationSeconds,
  formatPercent,
  getJson,
  postJson,
  renderGrowthLine,
  statusClass,
} from "./desktop_shared.js";
import { collectionStatusLabel, itemRegion } from "./desktop_regions.js";

export function hideDetailPanel() {
  $("detailPanel").classList.add("hidden");
  $("contentLayout").classList.add("detail-hidden");
  $("detailTitle").textContent = "已采集 HTML 文本";
  $("detailHint").textContent = "商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。";
  $("analysisActions").classList.add("hidden");
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  $("analysisAttemptCount").textContent = "AI 分析次数：-";
  $("detailPath").textContent = "";
  $("detailHtmlText").textContent = "点击“商品详情页采集”中的任一商品查看。";
  $("detailHtmlText").classList.remove("hidden");
  $("standardizedRows").classList.add("hidden");
  $("standardizedRows").innerHTML = "";
  state.selectedAnalysisItemId = null;
  state.selectedAnalysisRecord = null;
  state.editingAnalysis = false;
}

export function showDetailPanel() {
  $("detailPanel").classList.remove("hidden");
  $("contentLayout").classList.remove("detail-hidden");
}

export const STANDARDIZED_FIELD_LABELS = [
  ["商品唯一编号", ["item_id", "source_item_id", "id"]],
  ["标题", ["title", "source_title"]],
  ["商品直达链接", ["source_url", "url"]],
  ["交易时间", ["交易时间", "auction_date"]],
  ["成交价格", ["成交价格", "transaction_price"]],
  ["起拍价格", ["起拍价格", "starting_price"]],
  ["市场评估价", ["市场评估价", "evaluation_price"]],
  ["保证金", ["保证金", "deposit"]],
  ["竞拍人数", ["竞拍人数", "apply_count"]],
  ["出价次数", ["出价次数", "bid_count"]],
  ["完整地址", ["完整地址", "full_address", "地点"]],
  ["省份", ["省份", "province"]],
  ["城市", ["城市", "city"]],
  ["区", ["区", "district"]],
  ["最靠近商圈", ["最靠近商圈", "business_area"]],
  ["所属小区", ["所属小区", "community_name"]],
  ["建筑面积", ["建筑面积", "area_sqm"]],
  ["产权建筑面积", ["产权建筑面积", "gross_area_sqm"]],
  ["产权份额比例", ["产权份额比例", "ownership_share_ratio"]],
  ["户型", ["layout"]],
  ["建成年份", ["build_year"]],
  ["总楼层", ["total_floors"]],
  ["所在楼层", ["floor_level"]],
  ["是否有电梯", ["has_elevator"]],
  ["朝向", ["orientation"]],
  ["法院名称", ["法院名称", "court_name"]],
  ["案号", ["案号", "case_number"]],
  ["分析状态", ["analysis_status"]],
  ["分析模型版本", ["analysis_model_version"]],
];

export function isMeaningfulValue(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim() !== "";
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

export function displayValue(value) {
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

export function parseEditableValue(rawValue) {
  const value = String(rawValue ?? "").trim();
  if (value === "") {
    return null;
  }
  if (value === "true" || value === "是") {
    return true;
  }
  if (value === "false" || value === "否") {
    return false;
  }
  if (/^-?\d+(\.\d+)?$/.test(value)) {
    return Number(value);
  }
  if ((value.startsWith("{") && value.endsWith("}")) || (value.startsWith("[") && value.endsWith("]"))) {
    try {
      return JSON.parse(value);
    } catch (_error) {
      return value;
    }
  }
  return value;
}

export function firstExistingValue(record, keys) {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(record, key) && isMeaningfulValue(record[key])) {
      return record[key];
    }
  }
  return undefined;
}

export function editableKeyFor(keys) {
  return keys.find((key) => /^[a-z_][a-z0-9_]*$/i.test(key)) || keys[0];
}

export function renderStandardizedEntries(record, editable = false) {
  const source = record || {};
  const usedKeys = new Set();
  const rows = [];

  for (const [label, keys] of STANDARDIZED_FIELD_LABELS) {
    const value = firstExistingValue(source, keys);
    keys.forEach((key) => usedKeys.add(key));
    if (isMeaningfulValue(value)) {
      rows.push([label, editableKeyFor(keys), value]);
    }
  }

  Object.entries(source)
    .filter(([key, value]) => !usedKeys.has(key) && !key.startsWith("_") && isMeaningfulValue(value))
    .forEach(([key, value]) => rows.push([key, key, value]));

  if (rows.length === 0) {
    return '<p class="status-line">没有可展示的 AI 标准化数据。</p>';
  }

  return `<table class="standardized-table">
    <thead><tr><th>条目名称</th><th>数值内容</th></tr></thead>
    <tbody>${rows
      .map(([label, key, value]) => {
        const renderedValue = displayValue(value);
        const valueControl = editable
          ? `<textarea class="editable-field" data-field="${esc(key)}">${esc(renderedValue)}</textarea>`
          : `<pre class="value-cell">${esc(renderedValue)}</pre>`;
        return `<tr><td>${fmt(label)}</td><td>${valueControl}</td></tr>`;
      })
      .join("")}</tbody>
  </table>`;
}

export function analysisAttemptCount(data) {
  const payload = (data.item && data.item.source_payload) || {};
  const attempts = Number(payload._analysis_attempt_count || 0);
  return Number.isFinite(attempts) ? attempts : 0;
}

export function runtimeStateFromOverview(data) {
  if (typeof data.runtime_state === "string" && data.runtime_state.trim()) {
    return data.runtime_state;
  }
  const status = data.status || {};
  if (typeof status.runtime_state === "string" && status.runtime_state.trim()) {
    return status.runtime_state;
  }
  const solver = status.captcha_solver || {};
  const authRequired = Boolean(solver.manual_required || solver.force_unlock_flag_exists);
  if (authRequired) {
    const lastRequest = solver.last_request || {};
    const targetUrl = String(lastRequest.target_url || lastRequest.url || "").toLowerCase();
    const detailOnlyAuth =
      targetUrl.includes("sf-item.taobao.com") || targetUrl.includes("/sf_item/");
    const seedStageCanContinue =
      Number(status.seed_scan_job_pending || 0) > 0 ||
      Number(status.seed_scan_job_in_progress || 0) > 0 ||
      Number(status.seed_scan_progress_pending || 0) > 0 ||
      Number(status.seed_scan_progress_in_progress || 0) > 0;
    if (detailOnlyAuth && seedStageCanContinue) {
      return "运行中";
    }
    return "待认证";
  }
  if (status.paused) {
    return "暂停中";
  }
  const modules = data.modules || {};
  const links = modules.links || {};
  const details = modules.details || {};
  const analysis = modules.analysis || {};
  const hasItems = Number(links.unique_items || 0) > 0;
  const detailOpen =
    Number(details.pending || 0) + Number(details.failed || 0) + Number(details.blocked || 0);
  const analysisOpen =
    Number(analysis.ready || 0) +
    Number(analysis.pending || 0) +
    Number(analysis.failed || 0) +
    Number(analysis.blocked || 0);
  if (hasItems && detailOpen === 0 && analysisOpen === 0) {
    return "已完成";
  }
  return "运行中";
}

export function runtimeStateClass(label) {
  if (label === "运行中" || label === "已完成") {
    return "ok";
  }
  if (label === "待认证") {
    return "bad";
  }
  return "warn";
}

export function runtimeActionLabel(runtimeState) {
  return runtimeState === "运行中" ? "暂停" : "开始";
}

export function normalizeAuthChallengeUrl(url) {
  const rawUrl = String(url || "").trim();
  if (!rawUrl) {
    return DEFAULT_AUTH_CHALLENGE_URL;
  }

  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch (_error) {
    return DEFAULT_AUTH_CHALLENGE_URL;
  }

  const host = parsed.hostname.toLowerCase();
  const pathname = parsed.pathname || "";
  const loweredPath = pathname.toLowerCase();

  if (host.includes("sf-item.taobao.com") || loweredPath.includes("/sf_item/")) {
    return DEFAULT_AUTH_CHALLENGE_URL;
  }

  if (!host.includes("sf.taobao.com")) {
    return DEFAULT_AUTH_CHALLENGE_URL;
  }

  const buildListUrl = (pathValue, sourceParams) => {
    const normalizedPath = String(pathValue || "").replace(/\/{2,}/g, "/");
    if (!normalizedPath.toLowerCase().includes("/list/")) {
      return DEFAULT_AUTH_CHALLENGE_URL;
    }
    const next = new URL(`${parsed.origin}${normalizedPath}`);
    ["location_code", "st_param", "auction_start_seg", "page"].forEach((key) => {
      const value = sourceParams.get(key);
      if (value) {
        next.searchParams.set(key, value);
      }
    });
    next.searchParams.set("__captcha_solver_bg", "1");
    return next.toString();
  };

  if (loweredPath.includes("/_____tmd_____/punish")) {
    const cleanPath = pathname.split("/_____tmd_____/punish", 1)[0];
    return buildListUrl(cleanPath, parsed.searchParams);
  }

  if (loweredPath.includes("/list/")) {
    parsed.searchParams.delete("x5secdata");
    parsed.searchParams.delete("x5step");
    return buildListUrl(pathname, parsed.searchParams);
  }

  return DEFAULT_AUTH_CHALLENGE_URL;
}

export function defaultAuthChallengeUrl() {
  const solver = state.lastOverview && state.lastOverview.status && state.lastOverview.status.captcha_solver;
  const lastRequest = (solver && solver.last_request) || {};
  return normalizeAuthChallengeUrl(
    lastRequest.target_url ||
    lastRequest.url ||
    DEFAULT_AUTH_CHALLENGE_URL
  );
}

export async function loadOverview() {
  const data = await getJson("/api/collection/overview");
  const capturedAt = new Date();
  state.previousOverviewSample = state.currentOverviewSample;
  state.currentOverviewSample = { overview: data, capturedAt };
  state.lastOverview = data;
  const modules = data.modules || {};
  const runtimeState = runtimeStateFromOverview(data);
  const challengeMetrics = data.challenge_metrics || {};
  const authWatcher = data.auth_watcher || {};
  const recentChallengeRateText = formatPercent(challengeMetrics.recent_challenge_hit_rate);
  const currentChallengeRateText = formatPercent(challengeMetrics.current_challenge_hit_rate);
  const authWatcherStatusText = authWatcherStatusLabel(authWatcher);
  const authWatcherMessage = authWatcherStatusMessage(authWatcher, runtimeState);
  $("cards").innerHTML = `
    <div class="card runtime-card">
      <div class="label">运行状态</div>
      <div class="value"><span class="pill ${runtimeStateClass(runtimeState)}">${runtimeState}</span></div>
      <div class="hint">状态条目：暂停中 / 运行中 / 待认证 / 已完成；控制按钮按状态显示暂停/开始</div>
      <div class="card-actions">
        <button id="runtimePauseButton">${runtimeActionLabel(runtimeState)}</button>
        <button id="authButton">认证</button>
      </div>
    </div>
    <div class="card">
      <div class="label">Challenge 触发率</div>
      <div class="value">${fmt(recentChallengeRateText)}</div>
      <div class="hint">最近 ${fmt(challengeMetrics.recent_runs)} 轮：${fmt(challengeMetrics.recent_challenge_detected_count)} / ${fmt(challengeMetrics.recent_browserless_attempt_count)}；当前会话：${fmt(challengeMetrics.current_challenge_detected_count)} / ${fmt(challengeMetrics.current_browserless_attempt_count)}</div>
      <div class="growth-line">当前会话 ${esc(currentChallengeRateText)}；最近原因 ${fmt(challengeMetrics.recent_top_fallback_reason || challengeMetrics.top_fallback_reason || challengeMetrics.last_reason || "等待数据")}</div>
    </div>
    <div class="card">
      <div class="label">PC1 认证自动续跑</div>
      <div class="value"><span class="pill ${authWatcherStatusClass(authWatcher)}">${authWatcherStatusText}</span></div>
      <div class="hint">轮询 ${fmt(authWatcher.poll_seconds)} 秒 / 最长 ${fmt(authWatcher.max_wait_seconds)} 秒；累计等待 ${fmt(formatDurationSeconds(authWatcher.wait_elapsed_seconds))}</div>
      <div class="growth-line">${fmt(authWatcher.last_error || authWatcher.status || "等待认证任务")}</div>
    </div>
    <div class="card"><div class="label">商品链接采集</div><div class="value">${fmt(modules.links && modules.links.total)}</div><div class="hint">总链接出现次数；唯一商品 ${fmt(modules.links && modules.links.unique_items)}</div>${renderGrowthLine("links.total")}</div>
    <div class="card"><div class="label">商品详情页采集</div><div class="value">${fmt(modules.details && modules.details.captured)}</div><div class="hint">待抓 ${fmt(modules.details && modules.details.pending)} / 失败 ${fmt(modules.details && modules.details.failed)} / 阻塞 ${fmt(modules.details && modules.details.blocked)}</div>${renderGrowthLine("details.captured")}</div>
    <div class="card"><div class="label">商品详情页 AI 分析</div><div class="value">${fmt(modules.analysis && modules.analysis.finalized)}</div><div class="hint">待分析 ${fmt(modules.analysis && modules.analysis.pending)} / 失败 ${fmt(modules.analysis && modules.analysis.failed)} / 阻塞 ${fmt(modules.analysis && modules.analysis.blocked)}</div>${renderGrowthLine("analysis.finalized")}</div>
  `;
  $("runtimePauseButton").addEventListener("click", () => callAction("toggleRuntimePause"));
  $("authButton").addEventListener("click", () => callAction("openAuthChallenge"));
  $("connectionStatus").textContent = `已连接 ${state.apiBase}`;
  if (authWatcherMessage) {
    $("authChallengeStatus").textContent = authWatcherMessage;
  }
}

export function renderItems(data) {
  state.total = data.total || 0;
  $("listStatus").textContent = `阶段 ${state.stage}，总数 ${state.total}，当前 ${state.offset + 1}-${Math.min(state.offset + state.limit, state.total)}`;
  if (state.stage !== "details" && state.stage !== "analysis") {
    $("detailPanel").classList.add("hidden");
    $("contentLayout").classList.add("detail-hidden");
  }
  $("items").innerHTML = (data.items || [])
    .map((item) => {
      const currentStatus = collectionStatusLabel(item);
      return `<tr class="item-row" data-id="${esc(item.item_id)}">
        <td><strong>${fmt(item.item_id)}</strong></td>
        <td><a href="${esc(item.source_url || "#")}" target="_blank">${fmt(item.source_url)}</a></td>
        <td>${fmt(itemRegion(item))}</td>
        <td><span class="pill ${statusClass(currentStatus)}">${fmt(currentStatus)}</span></td>
      </tr>`;
    })
    .join("");
  document.querySelectorAll("tr.item-row").forEach((row) =>
    row.addEventListener("click", () => {
      if (state.stage === "details") {
        loadDetailHtml(row.dataset.id);
      } else if (state.stage === "analysis") {
        loadAnalysisData(row.dataset.id);
      }
    }),
  );
}

export async function loadItems() {
  $("listStatus").textContent = "加载中...";
  const regionParam = state.selectedLocationCode ? `&location_code=${encodeURIComponent(state.selectedLocationCode)}` : "";
  const data = await getJson(`/api/collection/items?stage=${encodeURIComponent(state.stage)}&limit=${state.limit}&offset=${state.offset}${regionParam}`);
  renderItems(data);
}

export async function loadDetailHtml(itemId) {
  if (state.stage !== "details") {
    return;
  }
  showDetailPanel();
  $("detailTitle").textContent = `已采集 HTML 文本 - ${itemId}`;
  $("detailHint").textContent = "商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。";
  $("analysisActions").classList.add("hidden");
  $("detailPath").textContent = "加载中...";
  $("standardizedRows").classList.add("hidden");
  $("detailHtmlText").classList.remove("hidden");
  $("detailHtmlText").textContent = "正在读取已采集的详情页 HTML/文本...";

  try {
    const data = await getJson(`/api/collection/item?item_id=${encodeURIComponent(itemId)}&max_chars=200000`);
    const artifact = data.artifacts && data.artifacts.detail_html;
    const content = artifact && (artifact.content || (artifact.json ? JSON.stringify(artifact.json, null, 2) : ""));
    $("detailPath").textContent = artifact && artifact.path ? artifact.path : "未返回详情文件路径";
    $("detailHtmlText").textContent = content || "未找到已采集的 HTML 文本。";
  } catch (error) {
    $("detailPath").textContent = "";
    $("detailHtmlText").textContent = `读取失败：${error.message}`;
  }
}

export async function loadAnalysisData(itemId) {
  if (state.stage !== "analysis") {
    return;
  }
  showDetailPanel();
  state.selectedAnalysisItemId = itemId;
  state.selectedAnalysisRecord = null;
  state.editingAnalysis = false;
  $("detailTitle").textContent = `AI 标准化数据 - ${itemId}`;
  $("detailHint").textContent = "经过 AI 分析调整后的标准化数据；每一行是一个条目名称和对应的数值内容。";
  $("detailPath").textContent = "加载中...";
  $("analysisActions").classList.remove("hidden");
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  $("detailHtmlText").classList.add("hidden");
  $("standardizedRows").classList.remove("hidden");
  $("standardizedRows").innerHTML = '<p class="status-line">正在读取 AI 标准化数据...</p>';

  try {
    const data = await getJson(`/api/collection/item?item_id=${encodeURIComponent(itemId)}&max_chars=200000`);
    const finalArtifact = data.artifacts && data.artifacts.final_json;
    const standardized = data.flat_item || (finalArtifact && finalArtifact.json) || {};
    state.selectedAnalysisRecord = standardized;
    $("analysisAttemptCount").textContent = `AI 分析次数：${analysisAttemptCount(data)}`;
    $("detailPath").textContent = finalArtifact && finalArtifact.path ? finalArtifact.path : "标准化数据来自数据库字段";
    $("standardizedRows").innerHTML = renderStandardizedEntries(standardized);
  } catch (error) {
    $("detailPath").textContent = "";
    $("standardizedRows").innerHTML = `<p class="error">读取失败：${esc(error.message)}</p>`;
  }
}

export function startManualEdit() {
  if (!state.selectedAnalysisItemId || !state.selectedAnalysisRecord) {
    return;
  }
  state.editingAnalysis = true;
  $("editButton").textContent = "取消编辑";
  $("manualUpdateButton").classList.remove("hidden");
  $("standardizedRows").innerHTML = renderStandardizedEntries(state.selectedAnalysisRecord, true);
}

export async function cancelManualEdit() {
  if (!state.selectedAnalysisItemId) {
    return;
  }
  state.editingAnalysis = false;
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  await loadAnalysisData(state.selectedAnalysisItemId);
}

export async function submitManualUpdate() {
  if (!state.selectedAnalysisItemId || !state.editingAnalysis) {
    return;
  }
  const updates = {};
  document.querySelectorAll(".editable-field").forEach((field) => {
    const key = field.dataset.field;
    if (key) {
      updates[key] = parseEditableValue(field.value);
    }
  });
  $("detailPath").textContent = "正在手动更新数据库...";
  const result = await postJson("/api/collection/item/manual_update", {
    item_id: state.selectedAnalysisItemId,
    updates,
  });
  state.selectedAnalysisRecord = result.flat_item || updates;
  state.editingAnalysis = false;
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  $("detailPath").textContent = `手动更新完成：${(result.updated_fields || []).length} 个字段`;
  $("standardizedRows").innerHTML = renderStandardizedEntries(state.selectedAnalysisRecord);
  await loadItems();
}

export async function requestReanalysis() {
  if (!state.selectedAnalysisItemId) {
    return;
  }
  $("detailPath").textContent = "正在提交 AI 再分析请求...";
  const result = await postJson("/api/collection/item/reanalyze", {
    item_id: state.selectedAnalysisItemId,
    reason: "operator_requested",
  });
  $("detailPath").textContent = `已加入 AI 再分析队列；当前分析次数：${result.analysis_attempt_count}`;
  await loadOverview();
  await loadItems();
}
