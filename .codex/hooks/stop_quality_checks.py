from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_CHARS = 6000


def _changed_python_files() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    paths: list[str] = []
    entries = [entry for entry in result.stdout.split("\0") if entry]
    index = 0
    while index < len(entries):
        entry = entries[index]
        status = entry[:2]
        path = entry[3:]
        if status.startswith(("R", "C")):
            index += 1
            if index < len(entries):
                path = entries[index]
        if path.endswith((".py", ".pyi")):
            paths.append(path)
        index += 1
    return sorted(set(paths))


def _run(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return result.returncode, output.strip()


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + "\n... output truncated ..."


def _block(message: str) -> None:
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": message,
            }
        )
    )


def main() -> int:
    try:
        _ = sys.stdin.read()

        prek_status, prek_output = _run(["uv", "run", "prek", "run", "--all-files"])
        if prek_status != 0:
            _block(
                "Stop hook blocked because `uv run prek run --all-files` failed.\n\n"
                + _truncate(prek_output)
            )
            return 0

        python_files = _changed_python_files()
        if python_files:
            ty_status, ty_output = _run(["uv", "run", "ty", "check"])
            if ty_status != 0:
                _block(
                    "Stop hook blocked because Python files changed and `uv run ty check` failed.\n\n"
                    + _truncate(ty_output)
                )
                return 0

        print(
            json.dumps(
                {
                    "systemMessage": (
                        "Stop hook passed: `uv run prek run --all-files` succeeded"
                        + (
                            " and `uv run ty check` succeeded."
                            if python_files
                            else ". No Python diff detected, so ty was skipped."
                        )
                    )
                }
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - stop-hook safety boundary
        _block(f"Stop hook failed unexpectedly: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
