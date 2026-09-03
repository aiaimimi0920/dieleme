from __future__ import annotations

from pathlib import Path

import pytest

from tools import build_web_app


def test_parse_net_use_mappings_extracts_drive_and_unc_root():
    output = """
Status       Local     Remote                    Network

-------------------------------------------------------------------------------
OK           Z:        \\\\192.168.15.200\\home     Microsoft Windows Network
Disconnected Y:        \\\\192.168.15.200\\home\\project     Microsoft Windows Network
The command completed successfully.
"""

    assert build_web_app._parse_net_use_mappings(output) == [
        ("Z:", r"\\192.168.15.200\home"),
        ("Y:", r"\\192.168.15.200\home\project"),
    ]


def test_remap_unc_path_prefers_longest_matching_mapped_root():
    mappings = [
        ("Z:", r"\\192.168.15.200\home"),
        ("Y:", r"\\192.168.15.200\home\project"),
    ]

    remapped = build_web_app._remap_unc_path(
        Path(r"\\192.168.15.200\home\project\project\fapaifang\game\web-app"),
        mappings,
    )

    assert remapped == Path(r"Y:\project\fapaifang\game\web-app")


def test_resolve_local_workdir_raises_for_unc_path_without_mapping():
    with pytest.raises(RuntimeError, match="No mapped drive alias found"):
        build_web_app.resolve_local_workdir(
            Path(r"\\192.168.15.200\home\project\project\fapaifang\game\web-app"),
            net_use_output="Status Local Remote\n",
        )


def test_resolve_local_workdirs_returns_all_matching_mapped_aliases():
    output = """
Status       Local     Remote                    Network

-------------------------------------------------------------------------------
OK           Y:        \\\\192.168.15.200\\home     Microsoft Windows Network
OK           Z:        \\\\192.168.15.200\\home     Microsoft Windows Network
The command completed successfully.
"""

    assert build_web_app.resolve_local_workdirs(
        Path(r"\\192.168.15.200\home\project\project\fapaifang\game\web-app"),
        net_use_output=output,
    ) == [
        Path(r"Y:\project\project\fapaifang\game\web-app"),
        Path(r"Z:\project\project\fapaifang\game\web-app"),
    ]


def test_npm_build_command_uses_npm_cmd_on_windows(monkeypatch):
    monkeypatch.setattr(build_web_app.os, "name", "nt")

    assert build_web_app._npm_build_command() == ["npm.cmd", "run", "build"]


def test_repo_web_build_dirs_detect_build_script_package_json(tmp_path: Path):
    app_dir = tmp_path / "game" / "web-app"
    app_dir.mkdir(parents=True)
    (app_dir / "package.json").write_text(
        '{"scripts":{"build":"vite build","dev":"vite"}}',
        encoding="utf-8",
    )
    no_build_dir = tmp_path / "docs" / "demo"
    no_build_dir.mkdir(parents=True)
    (no_build_dir / "package.json").write_text(
        '{"scripts":{"dev":"vite"}}',
        encoding="utf-8",
    )

    assert build_web_app.repo_web_build_dirs(tmp_path) == [app_dir]


def test_repo_web_build_dirs_ignores_pytest_temp_package_json(tmp_path: Path):
    app_dir = tmp_path / "game" / "web-app"
    app_dir.mkdir(parents=True)
    (app_dir / "package.json").write_text(
        '{"scripts":{"build":"vite build"}}',
        encoding="utf-8",
    )
    temp_app_dir = tmp_path / ".pytest-tmp-web-runtime" / "case0" / "game" / "web-app"
    temp_app_dir.mkdir(parents=True)
    (temp_app_dir / "package.json").write_text(
        '{"scripts":{"build":"should not be inventoried"}}',
        encoding="utf-8",
    )

    assert build_web_app.repo_web_build_dirs(tmp_path) == [app_dir]


def test_repo_web_build_inventory_matches_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert build_web_app.repo_web_build_dirs(repo_root) == [
        repo_root / "collector-desktop",
        repo_root / "game" / "web-app",
    ]


def test_repo_web_app_build_helper_succeeds_for_current_repo():
    repo_root = Path(__file__).resolve().parents[2]
    web_app_dir = repo_root / "game" / "web-app"

    assert build_web_app.build_web_app(web_app_dir) == 0
