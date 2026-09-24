from pathlib import Path


def test_storage_timestamp_sources_use_utc_clock() -> None:
    root = Path(__file__).parents[2] / "src" / "storage"
    canonical = (root / "canonical_record.py").read_text(encoding="utf-8")
    repair = (root / "seed_collision_repair.py").read_text(encoding="utf-8")
    assert "datetime.now(timezone.utc)" in canonical
    assert "datetime.utcnow()" not in canonical
    assert "datetime.now(timezone.utc)" in repair
    assert "datetime.utcnow()" not in repair
