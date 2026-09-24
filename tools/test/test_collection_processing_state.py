"""The collection processing registry prevents duplicate work atomically."""

from concurrent.futures import ThreadPoolExecutor

from src.collection_processing_state import CollectionProcessingState


def test_claim_is_atomic_under_concurrent_workers():
    state = CollectionProcessingState()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: state.claim("item.html"), range(8)))

    assert claims.count(True) == 1
    assert state.snapshot() == frozenset({"item.html"})


def test_release_and_set_compatibility_are_idempotent():
    state = CollectionProcessingState()
    state.add("one")
    state.add("one")
    assert "one" in state
    state.release("one")
    state.release("one")
    assert len(state) == 0
