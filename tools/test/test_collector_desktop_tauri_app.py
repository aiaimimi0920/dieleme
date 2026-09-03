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
    assert tauri_config["app"]["windows"][0]["title"] == "FapaiFang 运维观察台（PC2 采集）"
    assert tauri_config["build"]["frontendDist"] == "../dist"
    assert tauri_config["bundle"]["icon"] == ["icons/icon.ico"]
    assert 'name = "fapaifang_collector_desktop"' in cargo_toml
    assert 'tauri = { version = "2"' in cargo_toml


def test_collector_desktop_frontend_uses_collection_observer_api_not_browser_page() -> None:
    index_html = (APP_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "FapaiFang 运维观察台（PC2 采集）" in index_html
    assert "本机不运行采集 Worker" in main_js
    assert "Worker 均运行在 PC2" in main_js
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
    auth_resume_function = main_js[
        main_js.index("async function resumeAfterAuthChallenge"):
        main_js.index("async function reloadAll")
    ]
    assert 'refresh_cookie_snapshot: !tauriRuntime' in auth_resume_function
    assert 'tryInvoke("export_taobao_cookie_snapshot"' in auth_resume_function
    assert "open_auth_browser" in rust_lib
    assert "export_taobao_cookie_snapshot" in rust_lib
    assert '"-NoProfile"' in rust_lib
    assert "CREATE_NO_WINDOW" in rust_lib
    assert "Stdio::null()" in rust_lib
    assert "complete-pc1-inplace-auth.ps1" in rust_lib
    assert "open-remote-auth-browser.ps1" in rust_lib
    assert "std::env::current_exe" in rust_lib
    assert "std::env::current_dir" in rust_lib
    assert '.join("scripts")' in rust_lib
    assert "\\\\192.168.15.200\\home\\project\\project\\fapaifang" not in rust_lib
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
    assert "run_hidden_powershell" in cookie_export_function
    assert ".status()" in rust_lib
    assert "/api/collection/control/pause" in main_js
    assert "/api/collection/auth/complete" in main_js
    assert "/api/report_captcha" not in main_js
    assert "frame-src https://*.taobao.com" not in tauri_config["app"]["security"]["csp"]
    assert "Challenge 触发率" in main_js
    assert "PC1 认证自动续跑" in main_js
    assert "challenge_metrics" in main_js
    assert "auth_watcher" in main_js


def test_auth_challenge_open_buttons_pause_before_opening_browser() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "async function openAndQueueAuthChallenge" in main_js
    assert "function normalizeAuthChallengeUrl" in main_js
    assert "_____tmd_____/punish" in main_js
    assert "x5secdata" in main_js
    assert "sf-item.taobao.com" in main_js
    assert "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1" in main_js
    assert 'await tryInvoke("open_auth_browser", { url: targetUrl })' in main_js
    open_and_queue_function = main_js[
        main_js.index("async function openAndQueueAuthChallenge"):
        main_js.index("function closeAuthChallenge")
    ]
    pause_call = 'await postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 })'
    open_call = 'await tryInvoke("open_auth_browser", { url: targetUrl })'
    assert open_and_queue_function.index(pause_call) < open_and_queue_function.index(open_call)
    assert "/api/report_captcha" not in open_and_queue_function

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


def test_auth_challenge_default_url_is_sanitized_before_open_and_queue() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    default_function = main_js[
        main_js.index("function defaultAuthChallengeUrl"):
        main_js.index("async function loadOverview")
    ]
    assert "normalizeAuthChallengeUrl" in default_function

    open_and_queue_function = main_js[
        main_js.index("async function openAndQueueAuthChallenge"):
        main_js.index("function closeAuthChallenge")
    ]
    assert "const targetUrl = normalizeAuthChallengeUrl(url);" in open_and_queue_function
    assert 'await tryInvoke("open_auth_browser", { url: targetUrl })' in open_and_queue_function
    assert 'postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 })' in open_and_queue_function


def test_auth_challenge_manual_mode_never_submits_background_solver_request() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "function buildSolverReportPayload" not in main_js
    assert "/api/report_captcha" not in main_js

    open_and_queue_function = main_js[
        main_js.index("async function openAndQueueAuthChallenge"):
        main_js.index("function closeAuthChallenge")
    ]
    assert 'postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 })' in open_and_queue_function

    queue_function = main_js[
        main_js.index("async function queueAuthChallenge"):
        main_js.index("async function resumeAfterAuthChallenge")
    ]
    assert 'postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 })' in queue_function


def test_auth_challenge_network_calls_have_timeout_and_resume_does_not_wait_for_cookie_export() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "function fetchWithTimeout" in main_js
    assert "AbortController" in main_js
    assert "timeoutMs" in main_js
    assert 'postJson("/api/collection/control/pause", {}, { timeoutMs: 10_000 })' in main_js

    auth_resume_function = main_js[
        main_js.index("async function resumeAfterAuthChallenge"):
        main_js.index("async function reloadAll")
    ]
    assert 'postJson("/api/collection/auth/complete"' in auth_resume_function
    assert "{ timeoutMs: 10_000 }" in auth_resume_function
    assert 'refresh_cookie_snapshot: !tauriRuntime' in auth_resume_function
    assert 'tryInvoke("export_taobao_cookie_snapshot"' in auth_resume_function


def test_tauri_inplace_auth_uses_port_9225_without_browser_restart_switch() -> None:
    rust_lib = (APP_ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    cookie_export_function = rust_lib[rust_lib.index("fn export_taobao_cookie_snapshot") :]
    assert "complete-pc1-inplace-auth.ps1" in cookie_export_function
    assert 'unwrap_or_else(|| "9225".to_string())' in cookie_export_function
    assert '"-SkipBrowserStart"' not in cookie_export_function


def test_collector_desktop_frontend_can_run_as_plain_html_console() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert "function isTauriRuntime()" in main_js
    assert "function defaultBrowserApiBase()" in main_js
    assert "window.location.origin" in main_js
    assert 'value="${defaultBrowserApiBase()}"' in main_js
    assert "state.apiBase = defaultBrowserApiBase();" in main_js
    assert "not running inside Tauri" in main_js
    assert 'window.open(targetUrl, "_blank", "noopener,noreferrer")' in main_js
    assert "cookie 快照将由当前采集节点刷新" in main_js
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


def test_runtime_state_prefers_server_provided_runtime_state_before_solver_fallback() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    runtime_function = main_js[
        main_js.index("function runtimeStateFromOverview"):
        main_js.index("function runtimeStateClass")
    ]
    assert "data.runtime_state" in runtime_function
    assert 'return data.runtime_state;' in runtime_function
    assert "solver.manual_required" in runtime_function
    assert "solver.force_unlock_flag_exists" in runtime_function
    assert "solver.running || solver.manual_required" not in runtime_function


def test_runtime_state_fallback_keeps_running_for_detail_only_auth_when_seed_stage_can_continue() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    runtime_function = main_js[
        main_js.index("function runtimeStateFromOverview"):
        main_js.index("function runtimeStateClass")
    ]
    assert "last_request" in runtime_function
    assert "target_url" in runtime_function
    assert "sf-item.taobao.com" in runtime_function
    assert "seed_scan_job_pending" in runtime_function
    assert "seed_scan_progress_pending" in runtime_function
    assert 'return "运行中";' in runtime_function


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


def test_collector_desktop_runtime_cards_show_challenge_metrics_and_auth_watcher_status() -> None:
    main_js = (APP_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "function formatPercent" in main_js
    assert "function formatDurationSeconds" in main_js
    assert "function authWatcherStatusLabel" in main_js
    assert "function authWatcherStatusClass" in main_js
    assert "function authWatcherStatusMessage" in main_js
    assert "recent_challenge_hit_rate" in main_js
    assert "current_challenge_hit_rate" in main_js
    assert "recent_challenge_detected_count" in main_js
    assert "recent_browserless_attempt_count" in main_js
    assert "poll_seconds" in main_js
    assert "max_wait_seconds" in main_js
    assert "wait_elapsed_seconds" in main_js
    assert "等待自动恢复" in main_js
    assert "已自动恢复" in main_js
    assert "自动恢复超时" in main_js
    assert "后台 watcher 会自动检测恢复并让 PC2 续跑" in main_js


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


def test_collector_desktop_local_deploy_script_builds_to_temp_and_copies_local_runtime_bundle() -> None:
    script = REPO_ROOT.joinpath("scripts", "deploy-collector-desktop-local.ps1").read_text(encoding="utf-8")

    assert "FapaiFangCollectorDesktop" in script
    assert "LOCALAPPDATA" in script
    assert "fapaifang_collector_desktop.exe" in script
    assert "npm run tauri:build" in script
    assert "CARGO_TARGET_DIR" in script
    assert "pushd" in script
    assert "open-remote-auth-browser.ps1" in script
    assert "start-pc1-manual-auth-session.ps1" in script
    assert "start-pc1-auth-bridge.ps1" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "export-taobao-cookie-snapshot.ps1" in script
    assert "browserless_seed_probe.py" in script
    assert "taobao_login_health.py" in script
    assert "internal_api_http.py" in script
    assert "start-fapaifang-collector.ps1" in script
    assert "FAPAI_REMOTE_AUTH_HOST" in script
    assert "FAPAI_REMOTE_AUTH_KEY_PATH" in script
    assert "[AllowEmptyString()][string]$RemotePasswordValue" in script
    assert "[AllowEmptyString()][string]$RemoteKeyPath" in script
    assert "RemoteAuthKeyPath" in script
    assert "id_ed25519" in script
    assert "id_rsa" in script
    assert "Stop-Process" in script
    assert "Start-Process" in script
    assert "CreateShortcut" in script
    assert "WScript.Shell" in script
    assert "FapaiFang 运维观察台.lnk" in script
    assert "FapaiFang 采集观察台.lnk" in script
    assert "Remove-Item -LiteralPath $legacyDesktopShortcutPath -Force" in script
    assert "backup" in script.lower()
    assert "cmd /d /c" in script
    assert "Push-Location $env:SystemRoot" in script
    assert "& cmd /c $installCommand" not in script
    assert "& cmd /c $buildCommand" not in script


def test_remote_auth_browser_helper_can_use_ssh_key_without_password() -> None:
    script = REPO_ROOT.joinpath("scripts", "open-remote-auth-browser.ps1").read_text(encoding="utf-8")

    assert "FAPAI_REMOTE_AUTH_KEY_PATH" in script
    assert "key_filename" in script
    assert "\"allow_agent\": True" in script
    assert "\"look_for_keys\": True" in script
    assert "if (-not $resolvedRemotePassword -and -not $resolvedRemoteKeyPath)" in script
    assert "local-bridge" in script
    assert "watch-pc1-auth-auto-resume.ps1" in script
    assert "Start-LocalAuthAutoResumeWatcher" in script


def test_pc1_auth_bridge_uses_private_reverse_tunnel_and_human_browser_mode() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-pc1-auth-bridge.ps1").read_text(encoding="utf-8")

    assert "HumanAuthMode" in script
    assert "Get-CdpEndpointProbe" in script
    assert "127.0.0.1:{0}:127.0.0.1:{1}" in script
    assert '"ExitOnForwardFailure=yes"' in script
    assert '"ServerAliveInterval=15"' in script
    assert "FAPAI_AUTH_BROWSER_PROFILE_DIR" in script
    assert "FAPAI_AUTH_BROWSER_PATH" in script
    assert "report_cdp_endpoint" in script
    assert "report_cdp_websocket_url" in script
    assert "webSocketDebuggerUrl" in script
    assert "loopback_websocket_url" in script
    assert "remote_websocket_mismatch" in script
    assert "$request.Proxy = $null" in script
    assert "ConvertTo-Json" in script
    assert "if ($SkipBrowserStart)" in script
    assert "& powershell.exe" in script
    assert "-StartUrl $StartUrl" in script
    assert "-ForceNew" not in script


def test_collector_desktop_local_deploy_script_bundles_pc1_auth_auto_resume_watcher() -> None:
    script = REPO_ROOT.joinpath("scripts", "deploy-collector-desktop-local.ps1").read_text(encoding="utf-8")

    assert "scripts\\watch-pc1-auth-auto-resume.ps1" in script


def test_collector_desktop_bundles_pc1_analysis_proxy_bridge() -> None:
    deploy_script = REPO_ROOT.joinpath("scripts", "deploy-collector-desktop-local.ps1").read_text(encoding="utf-8")
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "start-pc1-analysis-proxy-bridge.ps1" in deploy_script
    assert "register-pc1-analysis-proxy-bridge-task.ps1" in deploy_script
    assert "start-pc1-analysis-proxy-bridge.ps1" in readme

def test_collector_desktop_readme_documents_local_deploy_workflow() -> None:
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "deploy-collector-desktop-local.ps1" in readme
    assert "FapaiFangCollectorDesktop" in readme
    assert "start-fapaifang-collector.ps1" in readme
    assert "open-remote-auth-browser.ps1" in readme
    assert "export-taobao-cookie-snapshot.ps1" in readme


def test_collector_desktop_gitignore_keeps_source_and_drops_generated_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!collector-desktop/index.html" in gitignore
    assert "collector-desktop/src-tauri/gen/" in gitignore
    assert "node_modules/" in gitignore
    assert "dist/" in gitignore
    assert "target/" in gitignore
