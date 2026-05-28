from __future__ import annotations

import argparse
from pathlib import Path

from ispa_daily_workflow.domain.pear.intake import (
    discover_input_files,
    extract_landing_report,
    validate_landing_schema,
)
from ispa_daily_workflow.schema import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate PEAR landing extraction against schemas for XLSX files in a folder. "
            "Outputs aggregate results only (no client-level rows)."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("input/pear_intake"),
        help="Directory containing PEAR XLSX files (default: input/pear_intake).",
    )
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=Path("schema"),
        help="Schema root directory (default: schema).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first file validation failure.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    files = discover_input_files(args.input_dir)
    if not files:
        print(f"No XLSX files found in {args.input_dir}")
        return 0

    failures = 0
    for path in files:
        try:
            landing = extract_landing_report(path)
            validate_landing_schema(landing, args.schema_root)
            warning_count = len(landing.warnings)
            print(
                "PASS landing "
                f"file={path.name!r} "
                f"type={landing.report_type} "
                f"rows={landing.landing_frame.height} "
                f"report_date={landing.footer.report_date.isoformat()} "
                f"canonical={landing.canonical_filename!r} "
                f"warnings={warning_count}"
            )
        except (ValidationError, FileNotFoundError, ValueError) as exc:
            failures += 1
            print(f"FAIL landing file={path.name!r} error={exc}")
            if args.fail_fast:
                break

    print(
        f"Landing validation complete: total_files={len(files)} failed={failures} passed={len(files) - failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
