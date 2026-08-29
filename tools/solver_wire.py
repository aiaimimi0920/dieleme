"""Deprecated CAPTCHA helper.

This module intentionally does not intercept or rewrite verification traffic.
Use ``tools/pc2_local_solver.py`` for supported local solver orchestration and
complete any official verification in the browser when required.
"""

from __future__ import annotations

import argparse


def solve_with_wire(target_url: str) -> bool:
    """Refuse the retired response-rewriting workflow.

    The return type is kept for callers that imported the old helper, but no
    network request, browser launch, or response mutation is performed.
    """
    del target_url
    raise RuntimeError(
        "solver_wire is retired: CAPTCHA responses must not be rewritten; "
        "use tools/pc2_local_solver.py and official browser verification"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the supported CAPTCHA solver entrypoint")
    parser.add_argument("target_url", nargs="?", help="retained for CLI compatibility")
    parser.parse_args()
    print(
        "solver_wire is retired; use tools/pc2_local_solver.py and complete "
        "official verification in the browser."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
