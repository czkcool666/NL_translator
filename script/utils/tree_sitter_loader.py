"""Locate pre-built Tree-sitter language libraries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _candidate_directories(root_path: str | os.PathLike[str] | None) -> Iterable[Path]:
    """Yield likely dependency-library directories without relying on cwd."""
    if root_path is not None:
        root = Path(root_path).expanduser().resolve()
        yield root if root.name == "dependencyLib" else root / "dependencyLib"
        yield root / "Code_Package" / "dependencyLib"

    repository_root = Path(__file__).resolve().parents[2]
    yield repository_root / "dependencyLib"
    yield repository_root / "Code_Package" / "dependencyLib"

    # Keep command-line use from older layouts working when invoked somewhere
    # inside either the repository or its former Code_Package directory.
    for parent in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        yield parent / "dependencyLib"
        yield parent / "Code_Package" / "dependencyLib"


def find_parser_library(
    root_path: str | os.PathLike[str] | None,
    *library_names: str,
) -> str:
    """Return the first existing parser library from the requested names.

    ``root_path`` may be a repository root or a dependencyLib directory. When
    omitted, the repository containing this module is searched first.
    """
    if not library_names:
        raise ValueError("At least one parser library name must be provided")

    checked: list[Path] = []
    seen: set[Path] = set()
    for directory in _candidate_directories(root_path):
        for library_name in library_names:
            candidate = directory / library_name
            if candidate in seen:
                continue
            seen.add(candidate)
            checked.append(candidate)
            if candidate.is_file():
                return str(candidate)

    locations = "\n  - ".join(str(path) for path in checked)
    raise FileNotFoundError(
        "Tree-sitter parser library not found. Checked:\n  - " + locations
    )
