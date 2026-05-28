from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from ispa_daily_workflow.compliance_history import (
    discover_compliance_history_by_slice_for_date,
    parse_slice_from_compliance_history,
)
from ispa_daily_workflow.diff import (
    run_adhoc_diff,
    run_adhoc_diff_from_compliance_history,
    run_daily_diff,
    run_daily_diff_from_compliance_history,
)
from ispa_daily_workflow.io.sharepoint_session import (
    upload_files_to_destination,
)
from ispa_daily_workflow.io.sharepoint_settings import load_sharepoint_settings
from ispa_daily_workflow.pipeline.workflow_config import load_workflow_config
from ispa_daily_workflow.validation import (
    RULE_PREVIOUS_SCOPE_DATA_ID,
    RuleResult,
    ValidationSummary,
    all_rule_ids,
    previous_scope_data_file_warning,
)
from ispa_daily_workflow.validation.scope import normalize_school_id_filter_values

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_sharepoint_diff_output(path: Path) -> Path:
    if path.suffix.lower() == ".xlsx":
        return path
    xlsx_candidate = path.with_suffix(".xlsx")
    if xlsx_candidate.exists():
        return xlsx_candidate
    if path.suffix.lower() == ".parquet":
        frame = pl.read_parquet(path)
        frame.write_excel(xlsx_candidate)
        return xlsx_candidate
    raise RuntimeError("SharePoint diff upload requires a parquet or XLSX output.")


def _load_sharepoint_settings(args: argparse.Namespace):
    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)
    return load_sharepoint_settings(runtime.config)


def _warn_previous_scope_data_uncertain(
    *,
    compliance_history_path: Path,
    previous_date: str,
    output_id: str,
    summary: ValidationSummary,
) -> None:
    try:
        slice_token = parse_slice_from_compliance_history(compliance_history_path)
    except ValueError:
        message = (
            "unable to infer compliance_history slice from input "
            f"{compliance_history_path.name}; day-over-business-day accuracy cannot be guaranteed."
        )
        summary.record_warning(
            RuleResult(
                rule_id=RULE_PREVIOUS_SCOPE_DATA_ID,
                code="previous_scope_slice_unresolved",
                severity="warning",
                message=message,
                context={"path": str(compliance_history_path)},
            ),
            log=print,
        )
        return

    previous_by_slice = discover_compliance_history_by_slice_for_date(
        compliance_history_path.parent,
        run_date=previous_date,
    )
    warning = previous_scope_data_file_warning(
        previous_date=previous_date,
        scope_label=f"slice={slice_token}",
        output_id=output_id,
        required_slices=[slice_token],
        available_slices=list(previous_by_slice),
    )
    if warning is not None:
        summary.record_warning(warning, log=print)
        return
    summary.record_pass(
        rule_id=RULE_PREVIOUS_SCOPE_DATA_ID,
        message=f"previous scope data files confirmed for {output_id}",
        log=print,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Daily and adhoc difference report generation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily = subparsers.add_parser(
        "daily",
        help="Run daily diff from combined files or compliance_history snapshot.",
    )
    daily.add_argument("--previous-file", type=Path)
    daily.add_argument("--current-file", type=Path)
    daily.add_argument("--compliance_history-file", type=Path)
    daily.add_argument(
        "--run-date", type=str, help="Required in compliance_history mode (YYYYMMDD)."
    )
    daily.add_argument(
        "--previous-date",
        type=str,
        help="Required in compliance_history mode (YYYYMMDD).",
    )
    daily.add_argument("--output-dir", type=Path, default=Path("output/diffs"))
    daily.add_argument("--schema-root", type=Path, default=Path("schema"))
    daily.add_argument(
        "--format", action="append", default=["parquet"], choices=("xlsx", "parquet")
    )
    daily.add_argument(
        "--sharepoint-upload",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Upload output diff file to io.sharepoint.outputs.list_difference.",
    )
    daily.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )

    adhoc = subparsers.add_parser(
        "adhoc",
        help="Run adhoc diff from delivery/baseline files or compliance_history snapshot.",
    )
    adhoc.add_argument("--baseline-file", type=Path)
    adhoc.add_argument("--delivery-file", type=Path)
    adhoc.add_argument("--compliance_history-file", type=Path)
    adhoc.add_argument(
        "--baseline-date",
        type=str,
        help="Required in compliance_history mode (YYYYMMDD).",
    )
    adhoc.add_argument(
        "--delivery-date",
        type=str,
        help="Required in compliance_history mode (YYYYMMDD).",
    )
    adhoc.add_argument("--output-dir", type=Path, default=Path("output/diffs"))
    adhoc.add_argument("--schema-root", type=Path, default=Path("schema"))
    adhoc.add_argument("--school-id", action="append", default=[])
    adhoc.add_argument(
        "--format", action="append", default=["parquet"], choices=("xlsx", "parquet")
    )
    adhoc.add_argument(
        "--sharepoint-upload",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Upload output diff file to io.sharepoint.outputs.list_difference.",
    )
    adhoc.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    validation_summary = ValidationSummary(tracked_rule_ids=all_rule_ids())

    if args.command == "daily":
        if args.compliance_history_file is not None:
            if args.run_date is None or args.previous_date is None:
                raise ValueError(
                    "Compliance History daily mode requires --run-date and --previous-date"
                )
            _warn_previous_scope_data_uncertain(
                compliance_history_path=args.compliance_history_file,
                previous_date=args.previous_date,
                output_id="diff_lists.daily",
                summary=validation_summary,
            )
            result = run_daily_diff_from_compliance_history(
                compliance_history_path=args.compliance_history_file,
                run_date=args.run_date,
                previous_date=args.previous_date,
                output_dir=args.output_dir,
                schema_root=args.schema_root,
                formats=tuple(args.format),
            )
        else:
            if args.previous_file is None or args.current_file is None:
                raise ValueError(
                    "Combined daily mode requires --previous-file and --current-file"
                )
            result = run_daily_diff(
                previous_path=args.previous_file,
                current_path=args.current_file,
                output_dir=args.output_dir,
                schema_root=args.schema_root,
                formats=tuple(args.format),
            )
        print(
            f"Daily diff complete: {result.output_path} "
            f"(became_compliant={result.became_compliant_rows}, current_only={result.current_only_rows})"
        )
        print(
            "Validation: "
            f"{validation_summary.status} "
            f"(applied={validation_summary.applied}, "
            f"pass={validation_summary.passed}, "
            f"warn={validation_summary.warned}, "
            f"fail={validation_summary.failed})"
        )
        rule_counts = validation_summary.rule_status_counts()
        print(
            "Validation rules: "
            f"PASS={rule_counts.get('PASS', 0)} "
            f"WARN={rule_counts.get('WARN', 0)} "
            f"FAIL={rule_counts.get('FAIL', 0)} "
            f"NONE={rule_counts.get('NONE', 0)}"
        )
        if args.sharepoint_upload:
            settings = _load_sharepoint_settings(args)
            sharepoint_output = _resolve_sharepoint_diff_output(result.output_path)
            uploaded = upload_files_to_destination(
                settings,
                destination_key="outputs.list_difference",
                paths=[sharepoint_output],
                overwrite=True,
            )
            print(f"Uploaded to SharePoint: {len(uploaded)}")
        return 0

    school_ids = normalize_school_id_filter_values(args.school_id)
    if args.compliance_history_file is not None:
        if args.baseline_date is None or args.delivery_date is None:
            raise ValueError(
                "Compliance History adhoc mode requires --baseline-date and --delivery-date"
            )
        _warn_previous_scope_data_uncertain(
            compliance_history_path=args.compliance_history_file,
            previous_date=args.baseline_date,
            output_id="diff_lists.adhoc",
            summary=validation_summary,
        )
        output = run_adhoc_diff_from_compliance_history(
            compliance_history_path=args.compliance_history_file,
            baseline_date=args.baseline_date,
            delivery_date=args.delivery_date,
            output_dir=args.output_dir,
            schema_root=args.schema_root,
            school_ids=school_ids,
            formats=tuple(args.format),
        )
    else:
        if args.baseline_file is None or args.delivery_file is None:
            raise ValueError(
                "Combined adhoc mode requires --baseline-file and --delivery-file"
            )
        output = run_adhoc_diff(
            baseline_path=args.baseline_file,
            delivery_path=args.delivery_file,
            output_dir=args.output_dir,
            schema_root=args.schema_root,
            school_ids=school_ids,
            formats=tuple(args.format),
        )
    print(f"Adhoc diff complete: {output}")
    print(
        "Validation: "
        f"{validation_summary.status} "
        f"(applied={validation_summary.applied}, "
        f"pass={validation_summary.passed}, "
        f"warn={validation_summary.warned}, "
        f"fail={validation_summary.failed})"
    )
    rule_counts = validation_summary.rule_status_counts()
    print(
        "Validation rules: "
        f"PASS={rule_counts.get('PASS', 0)} "
        f"WARN={rule_counts.get('WARN', 0)} "
        f"FAIL={rule_counts.get('FAIL', 0)} "
        f"NONE={rule_counts.get('NONE', 0)}"
    )
    if args.sharepoint_upload:
        settings = _load_sharepoint_settings(args)
        sharepoint_output = _resolve_sharepoint_diff_output(output)
        uploaded = upload_files_to_destination(
            settings,
            destination_key="outputs.list_difference",
            paths=[sharepoint_output],
            overwrite=True,
        )
        print(f"Uploaded to SharePoint: {len(uploaded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
