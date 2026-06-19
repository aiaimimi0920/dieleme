from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "collector-desktop"


def test_collector_desktop_is_independent_tauri_application() -> None:
    package_json = json.loads((APP_ROOT / "package.json").read_text(encoding="utf-8"))
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo_toml = (APP_ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")

    assert package_json["name"] == "fapaifang-collector-desktop"
    assert package_json["private"] is True
    assert "tauri" in package_json["scripts"]
    assert "tauri:dev" in package_json["scripts"]
    assert "tauri:build" in package_json["scripts"]
    assert tauri_config["productName"] == "FapaiFang Collector Console"
    assert tauri_config["app"]["windows"][0]["title"] == "FapaiFang 采集观察台"
    assert tauri_config["build"]["frontendDist"] == "../dist"
    assert tauri_config["bundle"]["icon"] == ["icons/icon.ico"]
    assert 'name = "fapaifang_collector_desktop"' in cargo_toml
    assert 'tauri = { version = "2"' in cargo_toml


def test_collector_desktop_frontend_uses_collection_observer_api_not_browser_page() -> None:
    index_html = (APP_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "FapaiFang 采集观察台" in index_html
    assert "商品链接采集" in main_js
    assert "商品详情页采集" in main_js
    assert "商品详情页 AI 分析" in main_js
    assert "/api/collection/overview" in main_js
    assert "/api/collection/items" in main_js
    assert "window.location.href = '/collection'" not in main_js
    assert "http://127.0.0.1:8001" in main_js


def test_links_stage_is_operator_focused_and_paginated_to_ten_items() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert 'limit: 10' in main_js
    assert '<option selected>10</option>' in main_js
    assert "商品唯一编号" in main_js
    assert "商品直达链接" in main_js
    assert "商品采集地区" in main_js
    assert "当前采集状态" in main_js
    assert "链接已采集" in main_js
    assert "详情已采集" in main_js
    assert "AI 已分析" in main_js
    assert "列表来源" not in main_js
    assert "详情/AI文件" not in main_js


def test_details_stage_click_opens_right_side_collected_html_panel() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert '<aside class="panel detail hidden" id="detailPanel">' in main_js
    assert "已采集 HTML 文本" in main_js
    assert "用于后续 AI 分析" in main_js
    assert "loadDetailHtml" in main_js
    assert 'state.stage === "details"' in main_js
    assert 'detailPanel").classList.add("hidden")' in main_js
    assert "/api/collection/item?item_id=" in main_js
    assert "artifacts.detail_html" in main_js


def test_analysis_stage_click_opens_standardized_field_table() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "AI 标准化数据" in main_js
    assert "条目名称" in main_js
    assert "数值内容" in main_js
    assert "loadAnalysisData" in main_js
    assert "renderStandardizedEntries" in main_js
    assert 'state.stage === "analysis"' in main_js
    assert "flat_item" in main_js
    assert "standardizedRows" in main_js
    assert "成交价格" in main_js
    assert "完整地址" in main_js
    assert "建筑面积" in main_js


def test_analysis_stage_supports_reanalysis_and_manual_edit_update_controls() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "AI 分析次数" in main_js
    assert "AI 再分析" in main_js
    assert "手动编辑" in main_js
    assert "取消编辑" in main_js
    assert "手动更新" in main_js
    assert "startManualEdit" in main_js
    assert "cancelManualEdit" in main_js
    assert "submitManualUpdate" in main_js
    assert "requestReanalysis" in main_js
    assert "/api/collection/item/reanalyze" in main_js
    assert "/api/collection/item/manual_update" in main_js
    assert "editable-field" in main_js
    assert "analysisAttemptCount" in main_js


def test_runtime_status_card_exposes_operator_controls_and_auth_challenge_dialog() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    rust_lib = (APP_ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "暂停中" in main_js
    assert "运行中" in main_js
    assert "待认证" in main_js
    assert "已完成" in main_js
    assert "暂停/开始" in main_js
    assert "认证" in main_js
    assert "认证挑战" in main_js
    assert "authChallengeDialog" in main_js
    assert "authChallengeFrame" not in main_js
    assert "toggleRuntimePause" in main_js
    assert "openAuthChallenge" in main_js
    assert 'tryInvoke("open_auth_browser"' in main_js
    assert 'tryInvoke("export_taobao_cookie_snapshot"' in main_js
    auth_resume_function = main_js[
        main_js.index("async function resumeAfterAuthChallenge"):
        main_js.index("async function reloadAll")
    ]
    assert auth_resume_function.index("/api/collection/auth/complete") < auth_resume_function.index('tryInvoke("export_taobao_cookie_snapshot"')
    assert "open_auth_browser" in rust_lib
    assert "export_taobao_cookie_snapshot" in rust_lib
    assert '"-NoProfile"' in rust_lib
    assert "CREATE_NO_WINDOW" in rust_lib
    assert "Stdio::null()" in rust_lib
    assert "export-taobao-cookie-snapshot.ps1" in rust_lib
    assert "start-taobao-cdp-browser.ps1" in rust_lib
    open_auth_function = rust_lib[
        rust_lib.index("fn open_auth_browser"):
        rust_lib.index("#[tauri::command]\nfn export_taobao_cookie_snapshot")
    ]
    assert "spawn_hidden_powershell" in open_auth_function
    assert ".output()" not in open_auth_function
    assert "后台" in open_auth_function
    helper_function = rust_lib[
        rust_lib.index("fn spawn_hidden_powershell"):
        rust_lib.index("#[tauri::command]\nfn open_auth_browser")
    ]
    assert ".spawn()" in helper_function
    assert ".output()" not in helper_function
    assert "let mut command = Command::new(\"powershell\");" in helper_function
    assert "command.creation_flags(CREATE_NO_WINDOW);" in helper_function
    cookie_export_function = rust_lib[rust_lib.index("fn export_taobao_cookie_snapshot") :]
    assert "spawn_hidden_powershell" in cookie_export_function
    assert ".output()" not in cookie_export_function
    assert "/api/collection/control/pause" in main_js
    assert "/api/collection/auth/complete" in main_js
    assert "/api/report_captcha" in main_js
    assert "frame-src https://*.taobao.com" not in tauri_config["app"]["security"]["csp"]


def test_auth_challenge_open_buttons_submit_solver_after_browser_open() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "async function openAndQueueAuthChallenge" in main_js
    assert 'await tryInvoke("open_auth_browser", { url })' in main_js
    assert 'await postJson("/api/report_captcha", { target_url: url, force_retry: true }, { timeoutMs: 10_000 })' in main_js

    open_function = main_js[
        main_js.index("async function openAuthChallenge"):
        main_js.index("function closeAuthChallenge")
    ]
    assert "await openAndQueueAuthChallenge(url)" in open_function

    reload_function = main_js[
        main_js.index("async function reloadAuthChallenge"):
        main_js.index("async function queueAuthChallenge")
    ]
    assert "await openAndQueueAuthChallenge(url)" in reload_function


def test_auth_challenge_network_calls_have_timeout_and_resume_does_not_wait_for_cookie_export() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "function fetchWithTimeout" in main_js
    assert "AbortController" in main_js
    assert "timeoutMs" in main_js
    assert 'postJson("/api/report_captcha", { target_url: url, force_retry: true }, { timeoutMs: 10_000 })' in main_js
    assert 'postJson("/api/report_captcha", { target_url: targetUrl, force_retry: true }, { timeoutMs: 10_000 })' in main_js

    auth_resume_function = main_js[
        main_js.index("async function resumeAfterAuthChallenge"):
        main_js.index("async function reloadAll")
    ]
    assert auth_resume_function.index("/api/collection/auth/complete") < auth_resume_function.index('tryInvoke("export_taobao_cookie_snapshot"')
    assert 'postJson("/api/collection/auth/complete"' in auth_resume_function
    assert "{ timeoutMs: 10_000 }" in auth_resume_function
    assert 'void tryInvoke("export_taobao_cookie_snapshot")' in auth_resume_function


def test_collector_desktop_frontend_can_run_as_plain_html_console() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert "function isTauriRuntime()" in main_js
    assert "function defaultBrowserApiBase()" in main_js
    assert "window.location.origin" in main_js
    assert "not running inside Tauri" in main_js
    assert 'window.open(url, "_blank", "noopener,noreferrer")' in main_js
    assert "当前为 HTML 控制台，cookie 快照需由采集节点本机维护" in main_js
    assert "http://192.168.15.200:8001" in tauri_config["app"]["security"]["csp"]


def test_runtime_start_always_forces_auth_complete_without_cookie_refresh() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "runtimeActionLabel(runtimeState)" in main_js
    assert 'runtimeState === "运行中" ? "暂停" : "开始"' in main_js
    assert "forceStartCollection" in main_js
    toggle_function = main_js[
        main_js.index("async function toggleRuntimePause"):
        main_js.index("async function forceStartCollection")
    ]
    assert 'runtimeState === "运行中"' in toggle_function
    assert "/api/collection/control/pause" in toggle_function
    assert "await forceStartCollection()" in toggle_function
    assert "/api/collection/control/resume" not in toggle_function
    assert 'refresh_cookie_snapshot: false' in main_js
    assert 'source: "collector_desktop_force_start"' in main_js
    assert "正在开始采集（清除待认证/暂停标记并重新尝试）" in main_js


def test_runtime_state_only_reports_pending_auth_for_manual_required() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    runtime_function = main_js[
        main_js.index("function runtimeStateFromOverview"):
        main_js.index("function runtimeStateClass")
    ]
    assert "solver.manual_required" in runtime_function
    assert "solver.force_unlock_flag_exists" in runtime_function
    assert "solver.running || solver.manual_required" not in runtime_function


def test_collector_desktop_auto_refreshes_every_sixty_seconds() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "AUTO_REFRESH_INTERVAL_MS = 60_000" in main_js
    assert "setInterval" in main_js
    assert "AUTO_REFRESH_INTERVAL_MS" in main_js
    assert "refreshInFlight" in main_js
    assert "最后刷新" in main_js
    assert "autoRefreshStatus" in main_js
    assert 'reloadAll({ silent: true })' in main_js
    reload_all_function = main_js[
        main_js.index("async function reloadAll"):
        main_js.index('document.querySelectorAll("button[data-stage]")')
    ]
    assert "await loadOverview()" in reload_all_function
    assert "await loadItems()" in reload_all_function
    assert "await loadRegions()" not in reload_all_function


def test_collector_desktop_refreshes_region_status_separately_every_ten_minutes() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "REGION_REFRESH_INTERVAL_MS = 600_000" in main_js
    assert "refreshRegions" in main_js
    assert "刷新所在地" in main_js
    assert "regionRefreshStatus" in main_js
    assert "regionRefreshInFlight" in main_js
    assert "最后刷新所在地" in main_js
    assert 'setInterval(() => loadRegions({ silent: true }), REGION_REFRESH_INTERVAL_MS)' in main_js
    assert '$("refreshRegions").addEventListener("click", () => loadRegions({ silent: false }))' in main_js
    assert "每 10 分钟自动刷新所在地状态" in main_js


def test_collector_desktop_overview_cards_show_recent_sixty_second_growth() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "currentOverviewSample" in main_js
    assert "previousOverviewSample" in main_js
    assert "formatGrowthDelta" in main_js
    assert "renderGrowthLine" in main_js
    assert "近60秒增长" in main_js
    assert "约" in main_js
    assert "links.total" in main_js
    assert "details.captured" in main_js
    assert "analysis.finalized" in main_js


def test_collector_desktop_has_stage_specific_region_tabs_and_link_reset_control() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    styles = (APP_ROOT / "src" / "styles.css").read_text(encoding="utf-8")

    assert "所在地" in main_js
    assert "provinceTabs" in main_js
    assert "cityTabs" in main_js
    assert "districtTabs" in main_js
    assert "regionTabs" not in main_js
    assert "buildRegionTree" in main_js
    assert "aggregateRegionStatus" in main_js
    assert "renderProvinceTabs" in main_js
    assert "renderCityTabs" in main_js
    assert "renderDistrictTabs" in main_js
    assert "selectedProvince" in main_js
    assert "selectedCity" in main_js
    assert "selectedLocationCode" in main_js
    assert "loadRegions" in main_js
    assert "/api/collection/regions" in main_js
    assert "/api/collection/region/reset_links" in main_js
    assert "resetRegionLinks" in main_js
    assert "重置本地区链接采集" in main_js
    assert 'state.stage === "links"' in main_js
    assert "location_code=" in main_js
    assert "全部省份" in main_js
    assert "全部城市" in main_js
    assert "全部地区" in main_js
    assert "请先选择省份" in main_js
    assert "请先选择城市" in main_js
    assert "此地区的链接是否已经全部收集完毕" in main_js
    assert "此地区的商品是否已经完全完成了该阶段任务" in main_js
    assert "region-panel" in styles
    assert "region-level" in styles
    assert "region-level-title" in styles
    assert "region-tab" in styles
    assert "region-status" in styles


def test_collector_desktop_readme_documents_api_dependency_and_commands() -> None:
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Rust + Tauri" in readme
    assert "http://127.0.0.1:8001" in readme
    assert "npm run tauri:dev" in readme
    assert "npm run tauri:build" in readme
    assert "AI 再分析" in readme
    assert "手动更新" in readme
    assert "写入数据库" in readme


def test_collector_desktop_gitignore_keeps_source_and_drops_generated_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!collector-desktop/index.html" in gitignore
    assert "collector-desktop/src-tauri/gen/" in gitignore
    assert "node_modules/" in gitignore
    assert "dist/" in gitignore
    assert "target/" in gitignore
