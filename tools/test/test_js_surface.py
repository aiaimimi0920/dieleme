from __future__ import annotations

from pathlib import Path

from tools import js_surface


def test_repo_js_syntax_check_files_inventory_matches_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert [path.relative_to(repo_root) for path in js_surface.repo_js_syntax_check_files(repo_root)] == [
        Path("collector-desktop/src/desktop_actions.js"),
        Path("collector-desktop/src/desktop_auth.js"),
        Path("collector-desktop/src/desktop_collection_views.js"),
        Path("collector-desktop/src/desktop_regions.js"),
        Path("collector-desktop/src/desktop_shared.js"),
        Path("collector-desktop/src/desktop_state.js"),
        Path("collector-desktop/src/desktop_template.js"),
        Path("collector-desktop/src/main.js"),
        Path("game/web-app/src/composables/useGameState.js"),
        Path("game/web-app/src/main.js"),
        Path("game/web-app/tailwind.config.js"),
        Path("game/web-app/vite.config.js"),
        Path("tampermonkey_scripts/fapaifang_unified.user.js"),
        Path("userscripts/nc_captcha_solver.user.js"),
    ]


def test_repo_js_syntax_check_files_ignore_operator_output_tree(tmp_path: Path):
    tracked_script = tmp_path / "tampermonkey_scripts" / "fapaifang_unified.user.js"
    tracked_script.parent.mkdir(parents=True)
    tracked_script.write_text("const tracked = true;\n", encoding="utf-8")
    generated_script = tmp_path / "output" / "taobao-auth-profile" / "extension.js"
    generated_script.parent.mkdir(parents=True)
    generated_script.write_text("this file is generated operator output\n", encoding="utf-8")

    assert js_surface.repo_js_syntax_check_files(tmp_path) == [tracked_script]


def test_repo_js_syntax_check_files_ignore_userscript_build_fragments(tmp_path: Path):
    built_script = tmp_path / "tampermonkey_scripts" / "fapaifang_unified.user.js"
    built_script.parent.mkdir(parents=True)
    built_script.write_text("const built = true;\n", encoding="utf-8")
    fragment = (
        tmp_path
        / "tampermonkey_scripts"
        / "src"
        / "fapaifang_unified"
        / "00_bootstrap.js"
    )
    fragment.parent.mkdir(parents=True)
    fragment.write_text("(() => {\n", encoding="utf-8")
    independent_source = tmp_path / "tampermonkey_scripts" / "src" / "independent.js"
    independent_source.write_text("const independent = true;\n", encoding="utf-8")

    assert js_surface.repo_js_syntax_check_files(tmp_path) == [
        built_script,
        independent_source,
    ]


def test_repo_js_syntax_check_files_pass_node_check():
    repo_root = Path(__file__).resolve().parents[2]

    failures = js_surface.node_check_repo_js_surface(repo_root)

    assert failures == []
