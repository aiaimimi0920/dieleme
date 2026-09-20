"""Canonical palette, compatibility and accessible observer UI contracts."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "collector-desktop" / "src"
DOCS = ROOT / "docs" / "design" / "neuro"


def read(path):
    return path.read_text(encoding="utf-8")


def test_canonical_snapshots_match_reviewed_manifest():
    manifest = json.loads(read(DOCS / "source-manifest.json"))
    assert len(manifest["sha256"]) == 4
    for name, expected in manifest["sha256"].items():
        raw = (DOCS / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        raw.decode("utf-8")
        assert hashlib.sha256(raw).hexdigest() == expected


def test_runtime_palette_uses_canonical_roles():
    colors = json.loads(read(DOCS / "tokens.json"))["colors"]
    theme = read(SOURCE / "styles" / "theme.css")
    values = dict(re.findall(r"--([\w-]+):\s*([^;]+);", theme))
    neutral_mapping = {
        "bg": "background", "surface": "surface", "panel": "panel", "rail": "rail",
        "control": "control", "control-hover": "controlHover", "text": "text",
        "muted": "textMuted", "line": "line", "focus-surface": "focusSurface",
        "focus-ink": "focusInk", "focus-muted": "focusMuted",
    }
    for variable, token in neutral_mapping.items():
        assert values[variable] == colors["neutral"][token]
    assert values["primary"] == colors["primary"]["signalYellow"]
    assert values["ok"] == colors["primary"]["signalGreen"]
    assert values["info"] == colors["semantic"]["infoBlue"]
    assert values["bad"] == colors["semantic"]["dangerRed"]
    assert values["warn"] == "var(--primary)"
    assert "color-scheme: dark" in theme
    assert "prefers-reduced-motion: reduce" in theme


def test_styles_are_scoped_and_all_variables_resolve():
    imports = re.findall(r'@import "\./([^"]+)"', read(SOURCE / "styles.css"))
    assert len(imports) == 7
    assert "desktop_settings.css" in imports
    css = "\n".join(read(SOURCE / name) for name in imports)
    definitions = set(re.findall(r"--([\w-]+)\s*:", css))
    references = set(re.findall(r"var\(--([\w-]+)", css))
    assert references <= definitions
    for retired in ("#2459d6", "#db2777", "#047857", "#f5f7fb"):
        assert retired not in css
    assert ":focus-visible" in css
    assert "var(--focus-surface)" in css
    assert "var(--focus-ink)" in css
    assert "#runtimeSettings label" in css


def test_standardized_schema_keeps_legacy_and_new_aliases():
    fields = json.loads(read(SOURCE / "desktop_standardized_fields.json"))
    assert len(fields) == 29
    labels = dict(fields)
    assert labels["商品唯一编号"] == ["item_id", "source_item_id", "id"]
    assert labels["成交价格"] == ["成交价格", "transaction_price"]
    assert labels["建筑面积"] == ["建筑面积", "area_sqm"]
    assert labels["完整地址"] == ["完整地址", "full_address", "地点"]


def test_keyboard_dialog_and_async_result_contracts():
    template = read(SOURCE / "desktop_template.js")
    shared = read(SOURCE / "desktop_shared.js")
    views = read(SOURCE / "desktop_collection_views.js")
    regions = read(SOURCE / "desktop_regions.js")
    assert template.count('data-stage="') == 3
    assert 'aria-label="人工认证"' in template
    assert 'id="authDialogTitle"' not in template
    assert 'id="authChallengeQueue"' not in template
    assert 'id="closeDetail"' in template
    assert 'event.key === "Escape"' in shared
    assert 'event.key !== "Tab"' in shared
    assert 'document.body.classList.remove("modal-open")' in shared
    assert '["Enter", " "].includes(event.key)' in views
    assert "当前阶段和地区没有商品" in views
    assert "requestId === state.itemsRequestId" in views
    assert 'state.selectedItemId !== String(itemId)' in views
    assert "await confirmRegionReset" in regions
    assert "window.confirm" not in regions


def test_initial_connection_failure_does_not_keep_loading_placeholders():
    main = read(SOURCE / "main.js")
    assert "if (!state.lastOverview)" in main
    assert "运行指标读取失败，等待重新连接。" in main
    assert "尚未读取商品列表，请恢复连接后刷新。" in main
    assert "运行指标保留上次快照，不代表当前实时状态。" in main


def test_board_always_shows_metrics_and_only_regions_can_fold():
    template = read(SOURCE / "desktop_template.js")
    css = read(SOURCE / "styles" / "overview.css")
    assert 'class="cards"' in template
    assert 'id="toggleOverview"' not in template
    assert 'id="toggleRegions" aria-expanded="false" aria-controls="regionFilters"' in template
    assert 'id="regionSelection" role="status"' in template
    assert 'id="connectionSettings"' in template
    assert re.search(r"grid-template-columns:\s*(?:[\d.]+fr\s+){2}repeat\(3, minmax\(0, 1fr\)\)", css)


def test_detail_generation_protects_revisiting_the_same_item_and_writes():
    views = read(SOURCE / "desktop_collection_views.js")
    state = read(SOURCE / "desktop_state.js")
    assert "detailRequestId: 0" in state
    assert "state.detailRequestId += 1" in views
    assert "return ++state.detailRequestId" in views
    assert views.count("requestId !== state.detailRequestId") == 6
    assert views.count('callAction("reloadAfterDetailAction"') == 2


def test_detail_actions_have_explicit_status_and_one_primary_action():
    template = read(SOURCE / "desktop_template.js")
    main = read(SOURCE / "main.js")
    views = read(SOURCE / "desktop_collection_views.js")
    shared = read(SOURCE / "desktop_shared.js")
    assert 'id="detailActionStatus" role="status" aria-live="polite"' in template
    assert '$("refresh").classList.remove("primary-button")' in views
    assert "setDetailBusy(true)" in main
    assert "requestId === state.detailRequestId" in main
    assert "操作已提交，但状态刷新失败" in main
    assert "不必重复提交" in main
    assert 'status.dataset.tone = tone' in shared
