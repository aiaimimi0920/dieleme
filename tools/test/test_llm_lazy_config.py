"""Importing collection LLM modules must not open credential files."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

from src import llm_config, llm_model_selector


def test_backend_import_never_reads_legacy_secrets(tmp_path):
    code = '''
import sys
def deny_credentials(event, args):
    if event == "open" and str(args[0]).replace("\\\\", "/").endswith("secrets.json"):
        raise AssertionError("credentials read during import")
sys.addaudithook(deny_credentials)
from src import llm_helper, llm_config, llm_qualification_pool
assert llm_config._model_pool is None
assert not hasattr(llm_helper, "API_KEY")
assert not hasattr(llm_helper, "API_SECRET")
'''
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": str(root)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_configuration_and_selector_are_loaded_once_on_first_use(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm_config, "_model_pool", None)
    monkeypatch.setattr(llm_model_selector, "_selector", None)
    monkeypatch.setattr(llm_config, "CONFIG_FILE", str(tmp_path / "missing.json"))

    def load():
        calls.append(1)
        return {"api_key": "synthetic", "models": [{"name": "test", "model_id": "test"}]}

    monkeypatch.setattr(llm_config, "_load_secrets", load)
    with ThreadPoolExecutor(max_workers=4) as executor:
        selectors = list(executor.map(lambda _: llm_model_selector.get_model_selector(), range(10)))
    assert calls == [1]
    assert all(value is selectors[0] for value in selectors)
    assert selectors[0].pool[0]["api_key"] == "synthetic"
