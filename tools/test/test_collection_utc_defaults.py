from pathlib import Path


def test_collection_default_timestamps_use_utc() -> None:
    stage = Path(__file__).parents[2].joinpath("src", "collection", "stage_state.py").read_text(encoding="utf-8")
    adapter = Path(__file__).parents[2].joinpath("src", "collection", "adapters", "generic_product.py").read_text(encoding="utf-8")
    assert "datetime.now(timezone.utc)" in stage
    assert "datetime.datetime.now(datetime.timezone.utc)" in adapter
    assert "datetime.datetime.now()" not in adapter
    assert "datetime.date.today()" not in adapter
