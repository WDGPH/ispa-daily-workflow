from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-local-data",
        action="store_true",
        default=False,
        help="Run tests marked local_data that require private local runtime files.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    run_local_data = bool(config.getoption("--run-local-data"))
    skip_local_data = pytest.mark.skip(
        reason="requires --run-local-data and private local runtime files"
    )

    for item in items:
        path = Path(str(item.path))
        name = path.name
        if name.startswith("test_validation_") or name.startswith("test_schema_"):
            item.add_marker(pytest.mark.validation)
        if "e2e" in path.parts:
            item.add_marker(pytest.mark.e2e)
        if "local_data" in item.keywords and not run_local_data:
            item.add_marker(skip_local_data)
