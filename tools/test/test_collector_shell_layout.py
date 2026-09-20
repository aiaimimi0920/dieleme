"""Crow shell matches Loom dimensions without changing collection contracts."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "collector-desktop"
SOURCE = APP / "src"


def read(name):
    return (SOURCE / name).read_text(encoding="utf-8")


def test_shell_uses_loom_window_and_navigation_dimensions():
    config = json.loads((APP / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    window = config["app"]["windows"][0]
    assert (window["width"], window["height"]) == (1120, 760)
    assert window["decorations"] is False
    assert window["minWidth"] <= window["width"]
    assert window["minHeight"] <= window["height"]
    css = read("styles/shell.css")
    assert "--shell-rail-width: 186px" in css
    assert "--shell-titlebar-height: 50px" in css
    assert ".app-shell.rail-collapsed { --shell-rail-width: 52px; }" in css
    assert "height: 100dvh" in css
    assert "margin: auto 8px 9px" in css
    assert ".rail-footer, " not in css


def test_settings_is_a_separate_page_and_keeps_api_controls():
    template = read("desktop_template.js")
    settings = template[template.index('<section class="settings-page'):]
    for control in ("settingsTitle", "connectionSettings", "apiBase", "applyApiBase", "connectionStatus"):
        assert f'id="{control}"' in settings
    shell = read("desktop_shell.ts")
    assert 'collection.classList.toggle("hidden", show)' in shell
    assert 'settings.classList.toggle("hidden", !show)' in shell
    assert 'event.key === "Escape"' in shell
    assert 'element("settingsTitle").focus()' in shell
    assert "settingsButton.focus()" in shell
    assert "collectionScroll" in shell
    main = read("main.js")
    assert main.index("initializeShell(reloadAll)") < main.index('document.querySelectorAll("button[data-stage]")')


def test_shell_removes_redundant_labels_not_business_controls():
    template = read("desktop_template.js")
    for retired in ("COLLECTION CONSOLE", "COLLECTION /", "TOPOLOGY", "stageIndex", "采集运行总览", "regionStageHint"):
        assert retired not in template
    for control in ("openCollection", "toggleRegions", "resetRegionLinks", "items", "analysisActions", "detailActionStatus"):
        assert f'id="{control}"' in template
    ids = re.findall(r'\bid="([^"]+)"', template)
    assert len(ids) == len(set(ids))
    assert template.count('data-stage="') == 3
    assert 'data-stage=' not in template[:template.index('class="app-workspace"')]
    assert 'id="toggleOverview"' not in template
    assert template.index('id="openSettings"') < template.index('class="app-workspace"')


def test_frameless_controls_have_scoped_permissions_and_browser_fallback():
    capability = json.loads((APP / "src-tauri/capabilities/default.json").read_text(encoding="utf-8"))
    assert capability["windows"] == ["main"]
    assert set(capability["permissions"]) == {
        "core:default", "core:window:allow-minimize", "core:window:allow-toggle-maximize",
        "core:window:allow-close", "core:window:allow-start-dragging",
    }
    shell = read("desktop_shell.ts")
    assert "if (!isTauri()) return;" in shell
    assert "await appWindow.minimize()" in shell
    assert "await appWindow.toggleMaximize()" in shell
    assert "await appWindow.close()" in shell
    assert "await appWindow.startDragging()" in shell
    assert 'event.target.closest("button")' in shell
    assert 'element("shellNotice")' in shell


def test_five_column_board_keeps_challenge_and_restart_results_visible():
    css = read("styles/overview.css")
    views = read("desktop_overview.ts")
    assert re.search(r"grid-template-columns:\s*(?:[\d.]+fr\s+){2}repeat\(3, minmax\(0, 1fr\)\)", css)
    assert ".cards.compact" not in css
    assert 'class="card challenge-card"' in views
    assert 'class="growth-line restart-status" role="status"' in views
    assert "重启失败" in views
