from __future__ import annotations

from pathlib import Path


SUPPORTED_INPUT_SUFFIXES = {".xls", ".xlsx", ".csv", ".tsv", ".json"}


def _within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def discover_input_files(
    input_root: Path,
    *,
    input_files: list[Path] | None = None,
    allowed_suffixes: set[str] | None = None,
) -> list[Path]:
    suffixes = allowed_suffixes or SUPPORTED_INPUT_SUFFIXES

    if input_files:
        results: list[Path] = []
        for path in input_files:
            resolved = path.resolve()
            if not resolved.exists() or not resolved.is_file():
                continue
            if not _within_root(resolved, input_root):
                raise ValueError(
                    f"Input file is outside configured input_root: {resolved}"
                )
            if resolved.suffix.lower() in suffixes:
                results.append(resolved)
        return sorted(results)

    if not input_root.exists():
        raise FileNotFoundError(f"Input root not found: {input_root}")

    return sorted(
        [
            path.resolve()
            for path in input_root.iterdir()
            if path.is_file()
            and path.suffix.lower() in suffixes
            and not path.name.startswith(".")
        ]
    )
