"""Dependency-free model policy shared by runtime and operator configuration."""
import re


def require_non_gpt_analysis_model(model, *, setting):
    normalized = str(model or "").strip()
    lowered = normalized.casefold()
    reasoning = bool(re.search(r"(?:^|[/:._-])o\d+(?:[/:._-]|$)", lowered))
    if not normalized or "gpt" in lowered or "codex" in lowered or reasoning:
        raise ValueError(f"{setting} must use an explicit non-GPT analysis model route")
    return normalized
