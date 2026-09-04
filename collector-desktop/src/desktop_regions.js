import { callAction } from "./desktop_actions.js";
import { state } from "./desktop_state.js";
import { $, esc, fmt, formatRefreshTime, getJson, postJson, setRegionRefreshStatus } from "./desktop_shared.js";

export function itemRegion(item) {
  const payload = item.source_payload || {};
  const occurrence = item.latest_occurrence || {};
  const code =
    payload.list_location_code ||
    occurrence.location_code ||
    String(occurrence.job_key || item.first_seen_job_key || "").split("-")[0];
  const name = [payload.city, payload.district].filter(Boolean).join(" ");
  return name || payload.location || payload.full_address || (code ? `地区代码 ${code}` : "-");
}

export function collectionStatusLabel(item) {
  const artifacts = item.artifacts || {};
  if (item.final_json_path || artifacts.final_json_path) {
    return "AI 已分析";
  }
  if (item.detail_completed_at || artifacts.detail_html_path || item.status === "detail_completed") {
    return "详情已采集";
  }
  return "链接已采集";
}

export function regionHintForStage() {
  if (state.stage === "links") {
    return "此地区的链接是否已经全部收集完毕";
  }
  return "此地区的商品是否已经完全完成了该阶段任务";
}

export function regionStatusClass(region) {
  const label = String((region && region.status_label) || "");
  if (region && region.completed) {
    return "ok";
  }
  if (label.includes("失败") || label.includes("阻塞")) {
    return "bad";
  }
  return "warn";
}

export function regionPart(value, fallback) {
  const text = String(value || "").trim();
  return text || fallback;
}

export function buildRegionTree(regions) {
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

export function aggregateRegionStatus(regions) {
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

export function regionStatusBadge(status) {
  return `<span class="region-status ${esc(status.className || "warn")}">${fmt(status.status_label)}</span>`;
}

export function validateRegionSelection(regionTree) {
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

export function selectedProvinceNode(regionTree) {
  return regionTree.find((province) => province.name === state.selectedProvince) || null;
}

export function selectedCityNode(province) {
  if (!province) {
    return null;
  }
  return province.cities.find((city) => city.name === state.selectedCity) || null;
}

export function renderProvinceTabs(regionTree) {
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
      callAction("hideDetailPanel");
      renderRegionSelectors();
      await callAction("loadItems");
    }),
  );
}

export function renderCityTabs(province) {
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
      callAction("hideDetailPanel");
      renderRegionSelectors();
      await callAction("loadItems");
    }),
  );
}

export function renderDistrictTabs(city) {
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
      callAction("hideDetailPanel");
      renderRegionSelectors();
      await callAction("loadItems");
    }),
  );
}

export function renderRegionSelectors() {
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

export async function loadRegions(options = {}) {
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

export async function resetSelectedRegionLinks() {
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
    await callAction("loadOverview");
    await loadRegions();
    await callAction("loadItems");
  } catch (error) {
    $("listStatus").innerHTML = `<span class="error">重置失败：${esc(error.message)}</span>`;
  }
}
