from __future__ import annotations

import argparse
from pathlib import Path

from ispa_daily_workflow.domain.pear.intake import (
    discover_input_files,
    extract_landing_report,
    transform_report,
    validate_landing_schema,
    validate_processed_schema,
)
from ispa_daily_workflow.reference import load_school_reference
from ispa_daily_workflow.schema import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate PEAR transform logic against processed schemas for XLSX files. "
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
        "--reference-path",
        type=Path,
        default=Path("profile/school_reference.json"),
        help="School reference JSON path (default: profile/school_reference.json).",
    )
    parser.add_argument(
        "--write-processed",
        action="store_true",
        help="Write transformed parquet outputs for inspection.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/inspect/pear_validation"),
        help="Output folder for --write-processed (default: output/inspect/pear_validation).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first file failure.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    files = discover_input_files(args.input_dir)
    if not files:
        print(f"No XLSX files found in {args.input_dir}")
        return 0

    reference = load_school_reference(args.reference_path)
    if not reference.wave_windows:
        print(
            "FAIL config error='school_reference is missing required suspension "
            "window metadata'"
        )
        return 1
    wave_windows = reference.wave_windows
    failures = 0
    for path in files:
        try:
            landing = extract_landing_report(path)
            validate_landing_schema(landing, args.schema_root)
            processed = transform_report(
                landing,
                reference=reference,
                wave_windows=wave_windows,
            )
            validate_processed_schema(processed, args.schema_root)

            if args.write_processed:
                args.output_dir.mkdir(parents=True, exist_ok=True)
                output_path = args.output_dir / processed.canonical_filename.replace(
                    ".xlsx", ".parquet"
                )
                collision = output_path.exists()
                processed.processed_frame.write_parquet(output_path)
                if collision:
                    print(f"WARN overwrite processed_output={output_path}")

            warnings = list(processed.report_warnings)
            warning_count = len(warnings)
            print(
                "PASS transform "
                f"file={path.name!r} "
                f"type={landing.report_type} "
                f"landing_rows={landing.landing_frame.height} "
                f"processed_rows={processed.processed_frame.height} "
                f"no_action_rows={processed.no_action_count} "
                f"report_date={landing.footer.report_date.isoformat()} "
                f"canonical={processed.canonical_filename!r} "
                f"warnings={warning_count}"
            )
        except (ValidationError, FileNotFoundError, ValueError) as exc:
            failures += 1
            print(f"FAIL transform file={path.name!r} error={exc}")
            if args.fail_fast:
                break

    print(
        f"Transform validation complete: total_files={len(files)} failed={failures} passed={len(files) - failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
