from __future__ import annotations

import re
from pathlib import Path


_DOT_SOURCE_PATTERN = re.compile(
    r'''^\s*\.\s+\(Join-Path\s+\$([\w:]+)\s+["']([^"']+\.ps1)["']\)\s*$'''
)


def read_powershell_script_tree(entry_path: Path) -> str:
    """Return a facade and its dot-sourced sibling modules in execution order."""
    facade = entry_path.read_text(encoding="utf-8")
    module_dir = entry_path.with_suffix("")
    facade_lines = facade.splitlines()
    references = [
        (index, match.group(1), match.group(2))
        for index, line in enumerate(facade_lines)
        if (match := _DOT_SOURCE_PATTERN.match(line))
    ]
    if not references:
        return facade

    referenced_names = [name for _, base, name in references if base.lower() != "psscriptroot"]
    if referenced_names and not module_dir.is_dir():
        raise FileNotFoundError(
            f"PowerShell module directory does not exist: {module_dir}; "
            f"referenced modules: {', '.join(referenced_names)}"
        )

    modules: dict[str, str] = {}
    reference_by_line: dict[int, str] = {}
    for index, base, name in references:
        root = entry_path.parent if base.lower() == "psscriptroot" else module_dir
        module_path = root.joinpath(*re.split(r"[\\/]", name))
        if not module_path.is_file():
            raise FileNotFoundError(f"Dot-sourced PowerShell module does not exist: {module_path}")
        contents = module_path.read_text(encoding="utf-8")
        reference_by_line[index] = contents
        if base.lower() != "psscriptroot":
            modules[name] = contents

    unreferenced = sorted(
        path.name
        for path in module_dir.glob("*.ps1")
        if referenced_names and path.name not in modules
    )
    if unreferenced:
        raise ValueError(
            f"PowerShell module directory contains unreferenced files: {', '.join(unreferenced)}"
        )

    expanded_lines: list[str] = []
    for index, line in enumerate(facade_lines):
        expanded_lines.append(reference_by_line.get(index, line))
    return "\n".join(expanded_lines)
