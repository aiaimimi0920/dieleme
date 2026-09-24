from pathlib import Path


SOURCE = Path(__file__).parents[2].joinpath("src", "avm_config.py")


def test_avm_config_uses_structured_logging() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert "print(" not in source
    assert "logger.exception(\"[AVM-CONFIG] Startup load failed, using defaults\")" in source
    assert "logger.exception(\"[AVM-CONFIG] Hot-reload failed, fallback to defaults\")" in source
