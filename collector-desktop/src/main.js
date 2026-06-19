import { invoke } from "@tauri-apps/api/core";
import "./styles.css";

const app = document.querySelector("#app");
const AUTO_REFRESH_INTERVAL_MS = 60_000;
const REGION_REFRESH_INTERVAL_MS = 600_000;

function isTauriRuntime() {
  return Boolean(window.__TAURI_INTERNALS__);
}

async function tryInvoke(command, args) {
  if (!isTauriRuntime()) {
    throw new Error("not running inside Tauri");
  }
  return invoke(command, args);
}

function defaultBrowserApiBase() {
  if (window.location && /^https?:$/.test(window.location.protocol) && window.location.origin) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8001";
}

app.innerHTML = `
  <header>
    <h1>FapaiFang 采集观察台</h1>
    <p>Rust + Tauri 独立桌面应用。观察并控制采集三段流水：商品链接采集、商品详情页采集、商品详情页 AI 分析。</p>
  </header>
  <main>
    <section class="panel">
      <div class="toolbar">
        <label>API 地址 <input id="apiBase" class="api-base" value="http://127.0.0.1:8001" /></label>
        <button id="applyApiBase">应用地址</button>
        <span class="status-line" id="connectionStatus">读取默认 API 地址中...</span>
      </div>
    </section>
    <section class="cards" id="cards"></section>
    <section class="panel">
      <div class="toolbar">
        <div class="tabs">
          <button data-stage="links" class="active">商品链接采集</button>
          <button data-stage="details">商品详情页采集</button>
          <button data-stage="analysis">商品详情页 AI 分析</button>
        </div>
        <label>每页 <select id="limit"><option selected>10</option><option>20</option><option>50</option></select></label>
        <button id="refresh">刷新</button>
        <button id="prev">上一页</button>
        <button id="next">下一页</button>
        <span class="status-line" id="listStatus"></span>
        <span class="status-line auto-refresh-status" id="autoRefreshStatus">每 60 秒自动刷新</span>
      </div>
    </section>
    <section class="panel region-panel">
      <div class="region-header">
        <div>
          <strong>所在地</strong>
          <span class="status-line" id="regionStageHint">此地区的链接是否已经全部收集完毕</span>
        </div>
        <div class="region-actions">
          <button id="refreshRegions">刷新所在地</button>
          <button id="resetRegionLinks" class="hidden">重置本地区链接采集</button>
        </div>
      </div>
      <div class="status-line region-refresh-status" id="regionRefreshStatus">每 10 分钟自动刷新所在地状态</div>
      <div class="region-level">
        <div class="region-level-title">省份</div>
        <div class="region-tabs" id="provinceTabs"></div>
      </div>
      <div class="region-level">
        <div class="region-level-title">城市</div>
        <div class="region-tabs" id="cityTabs"></div>
      </div>
      <div class="region-level">
        <div class="region-level-title">地区</div>
        <div class="region-tabs" id="districtTabs"></div>
      </div>
    </section>
    <section class="layout detail-hidden" id="contentLayout">
      <div class="panel table-wrap">
        <table>
          <thead><tr><th>商品唯一编号</th><th>商品直达链接</th><th>商品采集地区</th><th>当前采集状态</th></tr></thead>
          <tbody id="items"></tbody>
        </table>
      </div>
      <aside class="panel detail hidden" id="detailPanel">
        <h2 id="detailTitle">已采集 HTML 文本</h2>
        <p class="status-line" id="detailHint">商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。</p>
        <div class="detail-actions hidden" id="analysisActions">
          <span class="analysis-count" id="analysisAttemptCount">AI 分析次数：-</span>
          <button id="reanalysisButton">AI 再分析</button>
          <button id="editButton">手动编辑</button>
          <button id="manualUpdateButton" class="hidden">手动更新</button>
        </div>
        <div class="status-line" id="detailPath"></div>
        <pre id="detailHtmlText">点击“商品详情页采集”中的任一商品查看。</pre>
        <div class="standardized-rows hidden" id="standardizedRows"></div>
      </aside>
    </section>
  </main>
  <dialog class="auth-dialog" id="authChallengeDialog">
    <div class="auth-dialog-header">
      <div>
        <h2>认证挑战</h2>
        <p>用于处理淘宝登录、验证码或安全验证。完成后点击“我已完成认证，开始”。</p>
      </div>
      <button id="authChallengeClose" aria-label="关闭认证框">关闭</button>
    </div>
    <div class="auth-dialog-toolbar">
      <label>挑战地址 <input id="authChallengeUrl" value="https://login.taobao.com/member/login.jhtml" /></label>
      <button id="authChallengeReload">打开/刷新认证挑战</button>
      <button id="authChallengeQueue">提交认证任务</button>
      <button id="authChallengeResume">我已完成认证，开始</button>
    </div>
    <div class="status-line" id="authChallengeStatus">等待打开认证挑战。</div>
    <div class="auth-instructions">
      <strong>认证窗口会在外部浏览器中打开。</strong>
      <p>淘宝登录和安全挑战通常会阻止被嵌入到桌面应用内。这里不再加载内嵌页面，避免“已阻止此内容”和界面卡顿。请在弹出的浏览器窗口完成认证，然后回到本窗口点击“我已完成认证，开始”。</p>
    </div>
  </dialog>
`;

const state = {
  apiBase: defaultBrowserApiBase(),
  stage: "links",
  limit: 10,
  offset: 0,
  total: 0,
  selectedAnalysisItemId: null,
  selectedAnalysisRecord: null,
  editingAnalysis: false,
  lastOverview: null,
  lastRefreshAt: null,
  previousOverviewSample: null,
  currentOverviewSample: null,
  refreshInFlight: false,
  regionRefreshInFlight: false,
  lastRegionRefreshAt: null,
  regions: [],
  selectedProvince: "",
  selectedCity: "",
  selectedLocationCode: "",
};

const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const fmt = (value) => (value === null || value === undefined || value === "" ? "-" : esc(value));
const statusClass = (status) =>
  status === "AI 已分析" || status === "详情已采集"
    ? "ok"
    : String(status || "").includes("失败") || String(status || "").includes("阻塞")
      ? "bad"
      : "warn";

function apiUrl(path) {
  return `${state.apiBase.replace(/\/+$/, "")}${path}`;
}

function formatRefreshTime(date) {
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function setAutoRefreshStatus(text) {
  $("autoRefreshStatus").textContent = text;
}

function setRegionRefreshStatus(text) {
  $("regionRefreshStatus").textContent = text;
}

function formatSigned(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number}`;
}

function overviewMetric(data, path) {
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

function formatGrowthDelta(currentValue, previousValue, elapsedMs) {
  if (previousValue === null || previousValue === undefined || !Number.isFinite(Number(previousValue))) {
    return "近60秒增长：等待下一次刷新";
  }
  const delta = Number(currentValue || 0) - Number(previousValue || 0);
  const seconds = Math.max(Number(elapsedMs || AUTO_REFRESH_INTERVAL_MS) / 1000, 1);
  const perMinute = Math.round((delta * 60) / seconds);
  return `近60秒增长：${formatSigned(delta)}（约 ${formatSigned(perMinute)}/分钟）`;
}

function renderGrowthLine(path) {
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

async function fetchWithTimeout(url, options = {}, timeoutMs = 30_000) {
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

async function getJson(path, options = {}) {
  const response = await fetchWithTimeout(apiUrl(path), { cache: "no-store" }, options.timeoutMs || 30_000);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function postJson(path, body, options = {}) {
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

function itemRegion(item) {
  const payload = item.source_payload || {};
  const occurrence = item.latest_occurrence || {};
  const code =
    payload.list_location_code ||
    occurrence.location_code ||
    String(occurrence.job_key || item.first_seen_job_key || "").split("-")[0];
  const name = [payload.city, payload.district].filter(Boolean).join(" ");
  return name || payload.location || payload.full_address || (code ? `地区代码 ${code}` : "-");
}

function collectionStatusLabel(item) {
  const artifacts = item.artifacts || {};
  if (item.final_json_path || artifacts.final_json_path) {
    return "AI 已分析";
  }
  if (item.detail_completed_at || artifacts.detail_html_path || item.status === "detail_completed") {
    return "详情已采集";
  }
  return "链接已采集";
}

function regionHintForStage() {
  if (state.stage === "links") {
    return "此地区的链接是否已经全部收集完毕";
  }
  return "此地区的商品是否已经完全完成了该阶段任务";
}

function regionStatusClass(region) {
  const label = String((region && region.status_label) || "");
  if (region && region.completed) {
    return "ok";
  }
  if (label.includes("失败") || label.includes("阻塞")) {
    return "bad";
  }
  return "warn";
}

function regionPart(value, fallback) {
  const text = String(value || "").trim();
  return text || fallback;
}

function buildRegionTree(regions) {
  const provinceMap = new Map();
  for (const region of regions || []) {
    const provinceName = regionPart(region.province, "未知省份");
    const cityName = regionPart(region.city, "未知城市");
    const districtName = regionPart(region.district || region.label || region.location_code, "未知地区");
    if (!provinceMap.has(provinceName)) {
      provinceMap.set(provinceName, { name: provinceName, regions: [], cityMap: new Map() });
    }
    const province = provinceMap.get(provinceName);
    province.regions.push(region);
    if (!province.cityMap.has(cityName)) {
      province.cityMap.set(cityName, { name: cityName, province: provinceName, regions: [], districts: [] });
    }
    const city = province.cityMap.get(cityName);
    city.regions.push(region);
    city.districts.push({ ...region, displayDistrict: districtName });
  }
  return Array.from(provinceMap.values()).map((province) => ({
    name: province.name,
    regions: province.regions,
    cities: Array.from(province.cityMap.values()),
  }));
}

function aggregateRegionStatus(regions) {
  const scopedRegions = regions || [];
  if (!scopedRegions.length) {
    return { completed: false, status_label: "待采集", className: "warn" };
  }
  if (scopedRegions.every((region) => region.completed)) {
    return { completed: true, status_label: "收集完成", className: "ok" };
  }
  const hasProblem = scopedRegions.some((region) => {
    const label = String(region.status_label || "");
    return label.includes("失败") || label.includes("阻塞");
  });
  if (hasProblem) {
    return { completed: false, status_label: "存在失败/阻塞", className: "bad" };
  }
  return { completed: false, status_label: "采集中", className: "warn" };
}

function regionStatusBadge(status) {
  return `<span class="region-status ${esc(status.className || "warn")}">${fmt(status.status_label)}</span>`;
}

function validateRegionSelection(regionTree) {
  const regions = state.regions || [];
  const selectedRegion = regions.find((region) => region.location_code === state.selectedLocationCode);
  if (state.selectedLocationCode && !selectedRegion) {
    state.selectedLocationCode = "";
  }
  if (selectedRegion) {
    state.selectedProvince = regionPart(selectedRegion.province, "未知省份");
    state.selectedCity = regionPart(selectedRegion.city, "未知城市");
    return;
  }
  const province = regionTree.find((candidate) => candidate.name === state.selectedProvince);
  if (!province) {
    state.selectedProvince = "";
    state.selectedCity = "";
    return;
  }
  const city = province.cities.find((candidate) => candidate.name === state.selectedCity);
  if (state.selectedCity && !city) {
    state.selectedCity = "";
  }
}

function selectedProvinceNode(regionTree) {
  return regionTree.find((province) => province.name === state.selectedProvince) || null;
}

function selectedCityNode(province) {
  if (!province) {
    return null;
  }
  return province.cities.find((city) => city.name === state.selectedCity) || null;
}

function renderProvinceTabs(regionTree) {
  const allActive = state.selectedProvince ? "" : "active";
  const allStatus = aggregateRegionStatus(state.regions || []);
  const chips = [
    `<button class="region-tab province-tab ${allActive}" data-province="">全部省份${regionStatusBadge(allStatus)}</button>`,
    ...regionTree.map((province) => {
      const active = province.name === state.selectedProvince ? "active" : "";
      const status = aggregateRegionStatus(province.regions);
      const completed = status.completed ? "completed" : "";
      return `<button class="region-tab province-tab ${active} ${completed}" data-province="${esc(province.name)}">
        <span>${fmt(province.name)}</span>${regionStatusBadge(status)}
      </button>`;
    }),
  ];
  $("provinceTabs").innerHTML = chips.join("");
  document.querySelectorAll(".province-tab").forEach((button) =>
    button.addEventListener("click", async () => {
      state.selectedProvince = button.dataset.province || "";
      state.selectedCity = "";
      state.selectedLocationCode = "";
      state.offset = 0;
      hideDetailPanel();
      renderRegionSelectors();
      await loadItems();
    }),
  );
}

function renderCityTabs(province) {
  if (!state.selectedProvince || !province) {
    $("cityTabs").innerHTML = '<span class="status-line">请先选择省份</span>';
    return;
  }
  const allActive = state.selectedCity ? "" : "active";
  const allStatus = aggregateRegionStatus(province.regions);
  const chips = [
    `<button class="region-tab city-tab ${allActive}" data-city="">全部城市${regionStatusBadge(allStatus)}</button>`,
    ...province.cities.map((city) => {
      const active = city.name === state.selectedCity ? "active" : "";
      const status = aggregateRegionStatus(city.regions);
      const completed = status.completed ? "completed" : "";
      return `<button class="region-tab city-tab ${active} ${completed}" data-city="${esc(city.name)}">
        <span>${fmt(city.name)}</span>${regionStatusBadge(status)}
      </button>`;
    }),
  ];
  $("cityTabs").innerHTML = chips.join("");
  document.querySelectorAll(".city-tab").forEach((button) =>
    button.addEventListener("click", async () => {
      state.selectedCity = button.dataset.city || "";
      state.selectedLocationCode = "";
      state.offset = 0;
      hideDetailPanel();
      renderRegionSelectors();
      await loadItems();
    }),
  );
}

function renderDistrictTabs(city) {
  if (!state.selectedProvince) {
    $("districtTabs").innerHTML = '<span class="status-line">请先选择省份</span>';
    return;
  }
  if (!state.selectedCity || !city) {
    $("districtTabs").innerHTML = '<span class="status-line">请先选择城市</span>';
    return;
  }
  const allActive = state.selectedLocationCode ? "" : "active";
  const allStatus = aggregateRegionStatus(city.regions);
  const chips = [
    `<button class="region-tab district-tab ${allActive}" data-location-code="">全部地区${regionStatusBadge(allStatus)}</button>`,
    ...city.districts.map((region) => {
      const active = region.location_code === state.selectedLocationCode ? "active" : "";
      const completed = region.completed ? "completed" : "";
      const badgeClass = regionStatusClass(region);
      return `<button class="region-tab district-tab ${active} ${completed}" data-location-code="${esc(region.location_code)}">
        <span>${fmt(region.displayDistrict || region.label || region.location_code)}</span>
        <span class="region-status ${badgeClass}">${fmt(region.status_label || "采集中")}</span>
      </button>`;
    }),
  ];
  $("districtTabs").innerHTML = chips.join("");
  document.querySelectorAll(".district-tab").forEach((button) =>
    button.addEventListener("click", async () => {
      state.selectedLocationCode = button.dataset.locationCode || "";
      state.offset = 0;
      hideDetailPanel();
      renderRegionSelectors();
      await loadItems();
    }),
  );
}

function renderRegionSelectors() {
  $("regionStageHint").textContent = regionHintForStage();
  const regionTree = buildRegionTree(state.regions || []);
  validateRegionSelection(regionTree);
  const province = selectedProvinceNode(regionTree);
  const city = selectedCityNode(province);
  renderProvinceTabs(regionTree);
  renderCityTabs(province);
  renderDistrictTabs(city);
  if (state.stage === "links" && state.selectedLocationCode) {
    $("resetRegionLinks").classList.remove("hidden");
  } else {
    $("resetRegionLinks").classList.add("hidden");
  }
}

async function loadRegions(options = {}) {
  const silent = Boolean(options && options.silent);
  if (state.regionRefreshInFlight) {
    if (!silent) {
      setRegionRefreshStatus("所在地刷新已在进行中");
    }
    return;
  }
  state.regionRefreshInFlight = true;
  if (!silent) {
    setRegionRefreshStatus("所在地刷新中...");
  }
  if (!silent || !(state.regions || []).length) {
    $("provinceTabs").innerHTML = '<span class="status-line">所在地加载中...</span>';
    $("cityTabs").innerHTML = "";
    $("districtTabs").innerHTML = "";
  }
  try {
    const payload = await getJson(`/api/collection/regions?stage=${encodeURIComponent(state.stage)}`);
    state.regions = Array.isArray(payload.regions) ? payload.regions : [];
    renderRegionSelectors();
    state.lastRegionRefreshAt = new Date();
    setRegionRefreshStatus(`最后刷新所在地 ${formatRefreshTime(state.lastRegionRefreshAt)}；每 10 分钟自动刷新所在地状态`);
  } catch (error) {
    setRegionRefreshStatus(`所在地刷新失败；每 10 分钟自动重试：${error.message}`);
    if (!(state.regions || []).length) {
      $("provinceTabs").innerHTML = `<span class="error">所在地加载失败：${esc(error.message)}</span>`;
    }
  } finally {
    state.regionRefreshInFlight = false;
  }
}

async function resetSelectedRegionLinks() {
  if (state.stage !== "links" || !state.selectedLocationCode) {
    return;
  }
  const selected = (state.regions || []).find((region) => region.location_code === state.selectedLocationCode);
  const label = (selected && selected.label) || state.selectedLocationCode;
  const confirmed = window.confirm(`确定要重置“${label}”的商品链接采集状态吗？已有商品、详情页文本和 AI 分析数据会保留，但该地区链接会从第一页重新扫描。`);
  if (!confirmed) {
    return;
  }
  $("listStatus").textContent = `正在重置 ${label} 的链接采集状态...`;
  try {
    await postJson("/api/collection/region/reset_links", {
      location_code: state.selectedLocationCode,
    });
    state.offset = 0;
    await loadOverview();
    await loadRegions();
    await loadItems();
  } catch (error) {
    $("listStatus").innerHTML = `<span class="error">重置失败：${esc(error.message)}</span>`;
  }
}

function hideDetailPanel() {
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

function showDetailPanel() {
  $("detailPanel").classList.remove("hidden");
  $("contentLayout").classList.remove("detail-hidden");
}

const STANDARDIZED_FIELD_LABELS = [
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

function isMeaningfulValue(value) {
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

function displayValue(value) {
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function parseEditableValue(rawValue) {
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

function firstExistingValue(record, keys) {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(record, key) && isMeaningfulValue(record[key])) {
      return record[key];
    }
  }
  return undefined;
}

function editableKeyFor(keys) {
  return keys.find((key) => /^[a-z_][a-z0-9_]*$/i.test(key)) || keys[0];
}

function renderStandardizedEntries(record, editable = false) {
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

function analysisAttemptCount(data) {
  const payload = (data.item && data.item.source_payload) || {};
  const attempts = Number(payload._analysis_attempt_count || 0);
  return Number.isFinite(attempts) ? attempts : 0;
}

function runtimeStateFromOverview(data) {
  const status = data.status || {};
  const solver = status.captcha_solver || {};
  const authRequired = Boolean(solver.manual_required || solver.force_unlock_flag_exists);
  if (authRequired) {
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

function runtimeStateClass(label) {
  if (label === "运行中" || label === "已完成") {
    return "ok";
  }
  if (label === "待认证") {
    return "bad";
  }
  return "warn";
}

function runtimeActionLabel(runtimeState) {
  return runtimeState === "运行中" ? "暂停" : "开始";
}

function defaultAuthChallengeUrl() {
  const solver = state.lastOverview && state.lastOverview.status && state.lastOverview.status.captcha_solver;
  const lastRequest = (solver && solver.last_request) || {};
  return (
    lastRequest.target_url ||
    lastRequest.url ||
    "https://login.taobao.com/member/login.jhtml"
  );
}

async function loadOverview() {
  const data = await getJson("/api/collection/overview");
  const capturedAt = new Date();
  state.previousOverviewSample = state.currentOverviewSample;
  state.currentOverviewSample = { overview: data, capturedAt };
  state.lastOverview = data;
  const modules = data.modules || {};
  const runtimeState = runtimeStateFromOverview(data);
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
    <div class="card"><div class="label">商品链接采集</div><div class="value">${fmt(modules.links && modules.links.total)}</div><div class="hint">总链接出现次数；唯一商品 ${fmt(modules.links && modules.links.unique_items)}</div>${renderGrowthLine("links.total")}</div>
    <div class="card"><div class="label">商品详情页采集</div><div class="value">${fmt(modules.details && modules.details.captured)}</div><div class="hint">待抓 ${fmt(modules.details && modules.details.pending)} / 失败 ${fmt(modules.details && modules.details.failed)} / 阻塞 ${fmt(modules.details && modules.details.blocked)}</div>${renderGrowthLine("details.captured")}</div>
    <div class="card"><div class="label">商品详情页 AI 分析</div><div class="value">${fmt(modules.analysis && modules.analysis.finalized)}</div><div class="hint">待分析 ${fmt(modules.analysis && modules.analysis.pending)} / 失败 ${fmt(modules.analysis && modules.analysis.failed)} / 阻塞 ${fmt(modules.analysis && modules.analysis.blocked)}</div>${renderGrowthLine("analysis.finalized")}</div>
  `;
  $("runtimePauseButton").addEventListener("click", toggleRuntimePause);
  $("authButton").addEventListener("click", openAuthChallenge);
  $("connectionStatus").textContent = `已连接 ${state.apiBase}`;
}

function renderItems(data) {
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

async function loadItems() {
  $("listStatus").textContent = "加载中...";
  const regionParam = state.selectedLocationCode ? `&location_code=${encodeURIComponent(state.selectedLocationCode)}` : "";
  const data = await getJson(`/api/collection/items?stage=${encodeURIComponent(state.stage)}&limit=${state.limit}&offset=${state.offset}${regionParam}`);
  renderItems(data);
}

async function loadDetailHtml(itemId) {
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

async function loadAnalysisData(itemId) {
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

function startManualEdit() {
  if (!state.selectedAnalysisItemId || !state.selectedAnalysisRecord) {
    return;
  }
  state.editingAnalysis = true;
  $("editButton").textContent = "取消编辑";
  $("manualUpdateButton").classList.remove("hidden");
  $("standardizedRows").innerHTML = renderStandardizedEntries(state.selectedAnalysisRecord, true);
}

async function cancelManualEdit() {
  if (!state.selectedAnalysisItemId) {
    return;
  }
  state.editingAnalysis = false;
  $("editButton").textContent = "手动编辑";
  $("manualUpdateButton").classList.add("hidden");
  await loadAnalysisData(state.selectedAnalysisItemId);
}

async function submitManualUpdate() {
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

async function requestReanalysis() {
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

async function toggleRuntimePause() {
  const runtimeState = state.lastOverview ? runtimeStateFromOverview(state.lastOverview) : "运行中";
  if (runtimeState === "运行中") {
    const endpoint = "/api/collection/control/pause";
    $("connectionStatus").textContent = "正在暂停采集...";
    try {
      await postJson(endpoint, {});
      await reloadAll();
    } catch (error) {
      $("connectionStatus").innerHTML = `<span class="error">切换运行状态失败：${esc(error.message)}</span>`;
    }
  } else {
    await forceStartCollection();
  }
}

async function forceStartCollection() {
  $("connectionStatus").textContent = "正在开始采集（清除待认证/暂停标记并重新尝试）...";
  try {
    await postJson("/api/collection/auth/complete", {
      source: "collector_desktop_force_start",
      refresh_cookie_snapshot: false,
    });
    await reloadAll();
  } catch (error) {
    $("connectionStatus").innerHTML = `<span class="error">强制开始采集失败：${esc(error.message)}</span>`;
  }
}

async function openAuthChallenge() {
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

async function openAndQueueAuthChallenge(url) {
  let output = "";
  try {
    output = await tryInvoke("open_auth_browser", { url });
  } catch (_error) {
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    output = opened
      ? `已在当前浏览器打开认证页面：${url}。请完成认证后回到控制台点击“我已完成认证，开始”。`
      : `当前浏览器阻止了弹窗。请手动打开认证地址：${url}`;
  }
  const messages = [
    output || "已打开外部认证浏览器。请在浏览器中完成认证，然后点击“我已完成认证，开始”。",
  ];
  try {
    const result = await postJson("/api/report_captcha", { target_url: url, force_retry: true }, { timeoutMs: 10_000 });
    messages.push(`自动认证任务状态：${result.status || "已提交"}`);
    await loadOverview();
  } catch (error) {
    messages.push(`自动提交认证任务失败：${error.message || error}；请在外部浏览器中手动完成认证。`);
  }
  return messages.join("\n");
}

function closeAuthChallenge() {
  const dialog = $("authChallengeDialog");
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.classList.remove("open");
  }
}

async function reloadAuthChallenge() {
  const url = $("authChallengeUrl").value.trim() || defaultAuthChallengeUrl();
  $("authChallengeUrl").value = url;
  $("authChallengeStatus").textContent = "正在打开/刷新外部认证浏览器...";
  try {
    $("authChallengeStatus").textContent = await openAndQueueAuthChallenge(url);
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">打开外部认证浏览器失败：${esc(error.message || error)}</span>`;
  }
}

async function queueAuthChallenge() {
  const targetUrl = $("authChallengeUrl").value.trim() || defaultAuthChallengeUrl();
  $("authChallengeStatus").textContent = "正在提交认证任务...";
  try {
    const result = await postJson("/api/report_captcha", { target_url: targetUrl, force_retry: true }, { timeoutMs: 10_000 });
    $("authChallengeStatus").textContent = `认证任务状态：${result.status || "已提交"}`;
    await loadOverview();
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">提交认证任务失败：${esc(error.message)}</span>`;
  }
}

async function resumeAfterAuthChallenge() {
  $("authChallengeStatus").textContent = "正在通知 API 清除待认证状态...";
  try {
    await postJson("/api/collection/auth/complete", {
      source: "collector_desktop",
      refresh_cookie_snapshot: false,
    }, { timeoutMs: 10_000 });
    $("authChallengeStatus").textContent = isTauriRuntime()
      ? "已通知 API 开始采集；cookie 快照将在后台刷新。"
      : "已通知 API 开始采集。当前为 HTML 控制台，cookie 快照需由采集节点本机维护。";
    if (isTauriRuntime()) {
      void tryInvoke("export_taobao_cookie_snapshot").catch((error) => {
        console.warn("后台刷新淘宝 cookie 快照失败", error);
      });
    }
    closeAuthChallenge();
    await reloadAll();
  } catch (error) {
    $("authChallengeStatus").innerHTML = `<span class="error">开始失败：${esc(error.message)}</span>`;
  }
}

async function reloadAll(options = {}) {
  const silent = Boolean(options && options.silent);
  if (state.refreshInFlight) {
    if (!silent) {
      setAutoRefreshStatus("刷新已在进行中");
    }
    return;
  }
  state.refreshInFlight = true;
  setAutoRefreshStatus(silent ? "自动刷新中..." : "刷新中...");
  try {
    await loadOverview();
    await loadItems();
    state.lastRefreshAt = new Date();
    setAutoRefreshStatus(`最后刷新 ${formatRefreshTime(state.lastRefreshAt)}；每 60 秒自动刷新`);
  } catch (error) {
    $("connectionStatus").innerHTML = `<span class="error">连接失败：${esc(error.message)}。请确认 fapaifang-api 在 ${esc(state.apiBase)} 运行。</span>`;
    $("listStatus").textContent = "";
    setAutoRefreshStatus(`刷新失败；每 60 秒自动重试`);
  } finally {
    state.refreshInFlight = false;
  }
}

document.querySelectorAll("button[data-stage]").forEach((button) =>
  button.addEventListener("click", async () => {
    document.querySelectorAll("button[data-stage]").forEach((candidate) => candidate.classList.remove("active"));
    button.classList.add("active");
    state.stage = button.dataset.stage;
    state.offset = 0;
    hideDetailPanel();
    await loadRegions();
    await loadItems();
  }),
);

$("limit").addEventListener("change", async (event) => {
  state.limit = Number(event.target.value || 100);
  state.offset = 0;
  await loadItems();
});
$("refresh").addEventListener("click", reloadAll);
$("prev").addEventListener("click", async () => {
  state.offset = Math.max(0, state.offset - state.limit);
  await loadItems();
});
$("next").addEventListener("click", async () => {
  if (state.offset + state.limit < state.total) {
    state.offset += state.limit;
  }
  await loadItems();
});
$("applyApiBase").addEventListener("click", async () => {
  state.apiBase = $("apiBase").value.trim() || "http://127.0.0.1:8001";
  state.offset = 0;
  state.selectedProvince = "";
  state.selectedCity = "";
  state.selectedLocationCode = "";
  state.regions = [];
  state.previousOverviewSample = null;
  state.currentOverviewSample = null;
  await loadRegions();
  await reloadAll();
});
$("reanalysisButton").addEventListener("click", requestReanalysis);
$("editButton").addEventListener("click", async () => {
  if (state.editingAnalysis) {
    await cancelManualEdit();
  } else {
    startManualEdit();
  }
});
$("manualUpdateButton").addEventListener("click", submitManualUpdate);
$("authChallengeClose").addEventListener("click", closeAuthChallenge);
$("authChallengeReload").addEventListener("click", reloadAuthChallenge);
$("authChallengeQueue").addEventListener("click", queueAuthChallenge);
$("authChallengeResume").addEventListener("click", resumeAfterAuthChallenge);
$("refreshRegions").addEventListener("click", () => loadRegions({ silent: false }));
$("resetRegionLinks").addEventListener("click", resetSelectedRegionLinks);

try {
  state.apiBase = await tryInvoke("default_api_base");
  $("apiBase").value = state.apiBase;
} catch (_error) {
  state.apiBase = $("apiBase").value.trim() || defaultBrowserApiBase();
  $("apiBase").value = state.apiBase;
}

await loadRegions();
await reloadAll();
setInterval(() => reloadAll({ silent: true }), AUTO_REFRESH_INTERVAL_MS);
setInterval(() => loadRegions({ silent: true }), REGION_REFRESH_INTERVAL_MS);
