from pathlib import Path


SOURCE = Path(__file__).parents[2].joinpath("tools", "pc2_solver_context.py")


def test_pc2_solver_does_not_embed_remote_api_topology() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "192.168.15.200:8001" not in source
    assert 'os.environ.get("FAPAI_API_BASE_URL"' in source
    assert '"http://127.0.0.1:8001/api"' in source
