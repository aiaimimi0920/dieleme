from __future__ import annotations

from pathlib import Path

from tools import operator_surfaces


def test_first_party_package_script_manifests_match_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert [path.relative_to(repo_root) for path in operator_surfaces.first_party_package_script_manifests(repo_root)] == [
        Path("collector-desktop/package.json"),
        Path("game/web-app/package.json"),
    ]


def test_first_party_batch_files_match_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert [path.relative_to(repo_root) for path in operator_surfaces.first_party_batch_files(repo_root)] == [
        Path("auto/data_fixer.bat"),
        Path("auto/main.bat"),
        Path("auto/seed_hybrid_collector.bat"),
    ]


def test_first_party_html_surfaces_match_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert [path.relative_to(repo_root) for path in operator_surfaces.first_party_html_surfaces(repo_root)] == [
        Path("collector-desktop/index.html"),
        Path("game/web-app/index.html"),
        Path("tools/userscript_collection_harness.html"),
        Path("tools/userscript_detail_harness.html"),
        Path("tools/userscript_harness.html"),
    ]
