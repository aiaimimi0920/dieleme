from pathlib import Path


SOURCE = Path(__file__).parents[2].joinpath("src", "data_fixer_app_part_03.py")


def test_data_fixer_does_not_construct_shell_command_for_stored_url() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "cmd = f'start" not in source
    assert "webbrowser.open(url" in source


def test_data_fixer_validates_browser_url_before_appending_parameters() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "parsed_url.scheme.lower() not in {\"http\", \"https\"}" in source
    assert "ord(char) < 0x20" in source
    assert "'\"' in str(url)" in source
