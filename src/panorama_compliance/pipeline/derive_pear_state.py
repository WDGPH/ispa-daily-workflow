from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from panorama_compliance.config import ensure_dir
from panorama_compliance.io.workdays import load_workdays, parse_run_date
from panorama_compliance.domain.pear.state import (
    derive_pear_state,
    discover_latest_pear_processed_inputs,
    write_pear_authoritative_suspension_outputs,
    write_pear_state_outputs,
)
from panorama_compliance.pear_state import REPORT_SUSPENSION_OPERATIONAL
from panorama_compliance.pipeline.workflow_config import load_workflow_config
from panorama_compliance.pipeline.pear_state_runtime import (
    record_pear_state_validation,
)
from panorama_compliance.quality import write_manifest
from panorama_compliance.reference import load_school_reference
from panorama_compliance.schema import ValidationError
from panorama_compliance.validation import (
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
    ValidationSummary,
    all_rule_ids,
    require_wave_window_authority,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Derive PEAR state artifacts (suspension_active, overdue_active, "
            "suspension_vs_overdue, suspension_operational) from processed PEAR inputs."
        )
    )
    parser.add_argument(
        "--run-date",
        type=str,
        default=datetime.now().strftime("%Y%m%d"),
        help="Run date in YYYYMMDD format (default: today).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=None,
        help="Schema root override (default: config validation.schemas).",
    )
    parser.add_argument(
        "--reference-path",
        type=Path,
        default=None,
        help="School reference override (default: config paths.reference).",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=None,
        help="PEAR processed input folder (default: <paths.output_root>/pear_processed).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output folder for PEAR state files (default: <paths.output_root>/pear_state).",
    )
    parser.add_argument(
        "--authoritative-output-dir",
        type=Path,
        default=None,
        help=(
            "Output folder for official PEAR suspension_operational baseline files "
            "(default: <paths.output_root>/pear_processed)."
        ),
    )
    parser.add_argument(
        "--quality-dir",
        type=Path,
        default=None,
        help="Data-quality manifest folder (default: <paths.artifacts_root>/data_quality).",
    )
    parser.add_argument(
        "--format",
        action="append",
        default=["parquet"],
        choices=("parquet", "xlsx", "csv"),
        help="Output format(s) for state files (default: parquet).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Derive and validate frames without writing state files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed per-warning lines (default: summary-only warning output).",
    )
    return parser.parse_args(argv)


def _disappearance_client_ids_text(
    *,
    disappearance_evidence: pl.DataFrame,
    verbose: bool,
) -> str | None:
    if not verbose or disappearance_evidence.is_empty():
        return None
    disappearance_ids = disappearance_evidence.select("client_id").to_series().to_list()
    return "  disappearance_client_ids=" + ", ".join(
        str(value) for value in disappearance_ids
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_day = parse_run_date(args.run_date)
    run_date = run_day.strftime("%Y%m%d")

    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)

    schema_root = args.schema_root or runtime.validation_path("schemas")
    reference_path = args.reference_path or runtime.required_path("reference")
    output_root = runtime.required_path("output_root")
    artifacts_root = runtime.required_path("artifacts_root")
    workdays_path = runtime.run_path("workdays_csv")

    processed_dir = args.processed_dir or (output_root / "pear_processed")
    output_dir = args.output_dir or (output_root / "pear_state")
    authoritative_output_dir = args.authoritative_output_dir or (
        output_root / "pear_processed"
    )
    quality_dir = args.quality_dir or (artifacts_root / "data_quality")

    runtime.validate_files(
        reference_path=reference_path,
        workdays_path=workdays_path,
        require_workdays=True,
    )
    validation_summary = ValidationSummary(tracked_rule_ids=all_rule_ids())
    pass_log = print if args.verbose else None
    reference = load_school_reference(reference_path)
    try:
        require_wave_window_authority(
            reference=reference,
            context="derive_pear_state",
            rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
        )
    except ValidationError as exc:
        validation_summary.record_failure(
            rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
            message=str(exc),
            log=print,
        )
        print(
            "FAIL config error='school_reference is missing required suspension window metadata'"
        )
        return 1
    validation_summary.record_pass(
        rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
        message="school_reference wave-window metadata resolved for PEAR state derivation",
        log=pass_log,
    )
    workdays = load_workdays(workdays_path)

    selection = discover_latest_pear_processed_inputs(
        processed_dir=processed_dir,
        run_date=run_date,
    )
    result = derive_pear_state(
        selection=selection,
        schema_root=schema_root,
        reference=reference,
        authoritative_dir=authoritative_output_dir,
        workdays=workdays,
        strict_headers=runtime.strict_headers,
    )
    warning_log = print if args.verbose else None
    validation_counts = record_pear_state_validation(
        result=result,
        validation_summary=validation_summary,
        pass_log=pass_log,
        warning_log=warning_log,
    )
    delete_match_ids = validation_counts.delete_match_ids

    written_paths: list[Path] = []
    authoritative_paths: list[Path] = []
    disappearance_evidence_path: Path | None = None
    if not args.dry_run:
        output_dir = ensure_dir(output_dir)
        authoritative_output_dir = ensure_dir(authoritative_output_dir)
        written_paths = write_pear_state_outputs(
            frames=result.frames,
            run_date=run_date,
            output_dir=output_dir,
            formats=tuple(args.format),
        )
        authoritative_paths = write_pear_authoritative_suspension_outputs(
            suspension_operational=result.frames[REPORT_SUSPENSION_OPERATIONAL],
            run_date=run_date,
            output_dir=authoritative_output_dir,
        )
        written_paths.extend(authoritative_paths)
        if not result.disappearance_evidence.is_empty():
            disappearance_evidence_path = (
                output_dir / f"{run_date}_pear_disappearance_evidence.parquet"
            )
            result.disappearance_evidence.write_parquet(disappearance_evidence_path)
            written_paths.append(disappearance_evidence_path)

    datasets_for_manifest = dict(result.frames)
    datasets_for_manifest["disappearance_evidence"] = result.disappearance_evidence

    manifest_path = write_manifest(
        quality_dir=ensure_dir(quality_dir),
        timestamp=datetime.now().strftime("%Y%m%dT%H%M%S"),
        run_date=run_day,
        mode="derive_pear_state",
        datasets=datasets_for_manifest,
        file_outputs=written_paths,
        extra={
            "status": "success",
            "dry_run": args.dry_run,
            "processed_dir": str(processed_dir),
            "output_dir": str(output_dir),
            "authoritative_output_dir": str(authoritative_output_dir),
            "selected_dates": selection.selected_dates,
            "selected_suspension_files": [
                str(path) for path in selection.suspension_paths
            ],
            "selected_previous_suspension_files": [
                str(path) for path in selection.previous_suspension_paths
            ],
            "selected_previous_suspension_date": selection.previous_suspension_date,
            "selected_overdue_file": str(selection.overdue_path),
            "selected_suspension_vs_overdue_file": str(
                selection.suspension_vs_overdue_path
            ),
            "disappearance_summary": result.disappearance_summary,
            "rescind_patch_summary": result.rescind_patch_summary,
            "prior_suspension_source": result.prior_suspension_source,
            "disappearance_warning_count": result.disappearance_summary[
                "rehydrated_count"
            ],
            "delete_action_match_count": len(delete_match_ids),
            "delete_action_match_client_ids": delete_match_ids,
            "critical_message_count": len(result.critical_messages),
            "warning_message_count": len(result.warning_messages),
            "warning_messages": list(result.warning_messages),
            "overdue_day_over_day_summary": result.overdue_day_over_day_summary,
            "validation": validation_summary.as_dict(),
            "disappearance_evidence_path": (
                str(disappearance_evidence_path)
                if disappearance_evidence_path is not None
                else None
            ),
            "written_authoritative_count": len(authoritative_paths),
            "written_authoritative_files": [str(path) for path in authoritative_paths],
            "written_count": len(written_paths),
        },
    )

    continuity_warning_count = validation_counts.continuity_warning_count
    overdue_warning_count = validation_counts.overdue_warning_count
    disappearance_warning_count = validation_counts.disappearance_warning_count
    print("PEAR state derivation complete")
    print("Summary:")
    if args.verbose:
        print(f"  run_date={run_date}")
        print(f"  suspension_rows={result.frames['suspension_active'].height}")
        print(
            "  suspension_operational_rows="
            f"{result.frames[REPORT_SUSPENSION_OPERATIONAL].height}"
        )
        print(f"  prior_suspension_source={result.prior_suspension_source}")
        print(f"  overdue_rows={result.frames['overdue_active'].height}")
        print(
            "  overdue_day_over_day_status="
            f"{result.overdue_day_over_day_summary.get('status')}"
        )
        print(
            "  overdue_introduced_client_count="
            f"{result.overdue_day_over_day_summary.get('introduced_client_count', 0)}"
        )
        print(
            f"  suspension_vs_overdue_rows={result.frames['suspension_vs_overdue'].height}"
        )
        print(f"  disappeared_rows={result.disappearance_summary['disappeared_count']}")
        print(
            f"  resolved_disappearances={result.disappearance_summary['resolved_count']}"
        )
        print(
            "  unresolved_disappearances="
            f"{result.disappearance_summary['unresolved_count']}"
        )
        print(
            "  rescind_patch_summary="
            f"action_rows={result.rescind_patch_summary.get('rescind_action_rows', 0)} "
            f"matched_rescind_rows={result.rescind_patch_summary.get('matched_rescind_rows', 0)} "
            f"patched_rescind_rows={result.rescind_patch_summary.get('patched_rescind_rows', 0)} "
            "preserved_existing_rescind_rows="
            f"{result.rescind_patch_summary.get('preserved_existing_rescind_rows', 0)} "
            "unmatched_rescind_action_rows="
            f"{result.rescind_patch_summary.get('unmatched_rescind_action_rows', 0)} "
            f"delete_action_rows={result.rescind_patch_summary.get('delete_action_rows', 0)} "
            f"matched_delete_rows={result.rescind_patch_summary.get('matched_delete_rows', 0)} "
            "unmatched_delete_action_rows="
            f"{result.rescind_patch_summary.get('unmatched_delete_action_rows', 0)}"
        )
    else:
        print(
            "  snapshot="
            f"run_date={run_date} "
            f"suspension_rows={result.frames['suspension_active'].height} "
            f"overdue_rows={result.frames['overdue_active'].height} "
            f"suspension_vs_overdue_rows={result.frames['suspension_vs_overdue'].height} "
            f"prior_suspension_source={result.prior_suspension_source} "
            "overdue_day_over_day_status="
            f"{result.overdue_day_over_day_summary.get('status')}"
        )
        print(
            "  disappearance_summary="
            f"disappeared={result.disappearance_summary['disappeared_count']} "
            f"resolved={result.disappearance_summary['resolved_count']} "
            f"unresolved={result.disappearance_summary['unresolved_count']}"
        )
    print("Warnings:")
    print(
        "  warning_counts="
        f"continuity={continuity_warning_count} "
        f"overdue_day_over_day={overdue_warning_count} "
        f"disappearance_rehydration={disappearance_warning_count} "
        f"delete_action_matches={len(delete_match_ids)}"
    )
    print("Validation:")
    print(
        "  status="
        f"{validation_summary.status} (applied={validation_summary.applied}, "
        f"pass={validation_summary.passed}, warn={validation_summary.warned}, "
        f"fail={validation_summary.failed})"
    )
    rule_counts = validation_summary.rule_status_counts()
    print(
        "  rules="
        f"PASS={rule_counts.get('PASS', 0)} "
        f"WARN={rule_counts.get('WARN', 0)} "
        f"FAIL={rule_counts.get('FAIL', 0)} "
        f"NONE={rule_counts.get('NONE', 0)}"
    )
    if (
        continuity_warning_count
        or overdue_warning_count
        or disappearance_warning_count
        or delete_match_ids
    ):
        if args.verbose:
            if not result.disappearance_evidence.is_empty():
                print(
                    "  disappearance_rehydration="
                    f"disappeared={result.disappearance_summary['disappeared_count']} "
                    f"resolved={result.disappearance_summary['resolved_count']} "
                    f"unresolved={result.disappearance_summary['unresolved_count']} "
                    f"rehydrated={result.disappearance_summary['rehydrated_count']}"
                )
                if result.disappearance_summary["unresolved_count"] == 0:
                    print(
                        "  warning_note=disappearance rehydration warnings were auto-resolved (unresolved=0)"
                    )
                disappearance_client_ids = _disappearance_client_ids_text(
                    disappearance_evidence=result.disappearance_evidence,
                    verbose=args.verbose,
                )
                if disappearance_client_ids is not None:
                    print(disappearance_client_ids)
            if delete_match_ids:
                print("  delete_action_match_client_ids=" + ", ".join(delete_match_ids))
            for message in result.continuity_warning_messages:
                print(f"  continuity_warning: {message}")
            for message in result.overdue_day_over_day_warning_messages:
                print(f"  overdue_day_over_day_warning: {message}")
            for message in result.disappearance_warning_messages:
                print(f"  disappearance_warning: {message}")
        else:
            if disappearance_warning_count:
                print(
                    "  disappearance_rehydration="
                    f"disappeared={result.disappearance_summary['disappeared_count']} "
                    f"resolved={result.disappearance_summary['resolved_count']} "
                    f"unresolved={result.disappearance_summary['unresolved_count']}"
                )
    if result.critical_messages:
        print("Critical messages: unresolved suspension disappearances were rehydrated")
        if args.verbose:
            for message in result.critical_messages:
                print(f"  {message}")
    print("Artifacts:")
    print(f"  written={len(written_paths)}")
    print(f"  manifest={manifest_path if args.verbose else manifest_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
