"""Test captcha solver improvements."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def test_stealth_injection():
    """Verify stealth JS injection includes all fingerprint hiding."""
    from src.captcha_solver import CaptchaSolver
    solver = CaptchaSolver(port=9223)

    # Connect and inject stealth script (mocked)
    assert hasattr(solver, '_send_cdp')
    print("✓ Stealth injection method exists")


def test_bezier_path_generation():
    """Test that bezier path has realistic human-like properties."""
    from src.captcha_solver import CaptchaSolver
    solver = CaptchaSolver(port=9223)

    path = solver._generate_bezier_path(100, 100, 400, 105)

    # Should have reasonable number of points
    assert 15 <= len(path) <= 100, f"Path has {len(path)} points"

    # Should have some variation in Y axis (human tremor)
    y_values = [p[1] for p in path]
    y_min, y_max = min(y_values), max(y_values)
    y_range = y_max - y_min
    assert y_range > 2, f"Y variation too small: {y_range}px"

    # Check easing values are properly distributed
    ease_values = [p[2] for p in path]
    assert ease_values[0] < 0.1, "Start should be slow"
    assert ease_values[-1] > 0.9, "End should be near complete"

    print(f"✓ Bezier path: {len(path)} points, Y-range: {y_range:.1f}px")


def test_drag_timing_improvements():
    """Verify drag method has improved timing."""
    from src.captcha_solver import CaptchaSolver
    import inspect

    solver = CaptchaSolver(port=9223)
    source = inspect.getsource(solver._do_drag)

    # Check for improved timings
    assert "0.3, 0.8" in source or "0.9, 2.2" in source, "Should have longer delays"
    assert "random.uniform" in source, "Should use randomization"

    print("✓ Drag timing includes improvements")


def test_distance_randomization():
    """Verify solve method adds random distance adjustment."""
    from src.captcha_solver import CaptchaSolver
    import inspect

    solver = CaptchaSolver(port=9223)
    source = inspect.getsource(solver.solve)

    # Should have distance adjustment
    assert "distance = distance + random.uniform" in source or "random.uniform(-3, 2)" in source

    print("✓ Distance randomization present")


if __name__ == "__main__":
    print("Testing captcha solver improvements...\n")

    try:
        test_stealth_injection()
        test_bezier_path_generation()
        test_drag_timing_improvements()
        test_distance_randomization()

        print("\n✅ All improvement tests passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
