from pathlib import Path


SOURCE = Path(__file__).parents[2].joinpath("src", "data_fixer_app_part_04.py")


def test_next_task_legacy_route_is_post_only() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "@server.app.route('/api/next_task', methods=['POST'])" in source
    assert "@server.app.route('/api/next_task', methods=['GET'])" not in source
