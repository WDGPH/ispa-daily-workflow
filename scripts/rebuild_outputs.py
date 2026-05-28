#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.domain.common.workdays import WorkdayInfo
from panorama_compliance.io.workdays import load_workdays
from panorama_compliance.pipeline.workflow_config import load_workflow_config
from panorama_compliance.reference import collect_scope_values, load_school_reference
from panorama_compliance.validation.scope import (
    normalize_level_scope_value,
    normalize_school_scope_value,
    normalize_wave_scope_value,
)

PANORAMA_ONLY_OUTPUT_IDS = {
    "sharepoint.panorama.diff.xlsx",
}
PEAR_ONLY_OUTPUT_IDS = {"sharepoint.action_queue.xlsx"}


def _log(message: str) -> None:
    print(f"[rebuild_outputs] {message}", flush=True)


def parse_date_token(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def format_date_token(value: date) -> str:
    return value.strftime("%Y%m%d")


def date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def load_workdays_map(
    start: date,
    end: date,
    workdays_path: Path | None,
    assets_dir: Path,
) -> dict[date, WorkdayInfo]:
    if workdays_path is not None:
        return load_workdays(workdays_path)

    workdays: dict[date, WorkdayInfo] = {}
    for year in range(start.year, end.year + 1):
        path = assets_dir / f"{year}_workdays.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing workdays file for {year}: {path}")
        workdays.update(load_workdays(path))
    return workdays


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run update_state across a business-day range and optionally run one or "
            "more scoped deliver_outputs commands per day."
        )
    )
    parser.add_argument("--start-date", required=True, help="Start date (YYYYMMDD)")
    parser.add_argument(
        "--end-date", default=None, help="End date (YYYYMMDD), defaults to today"
    )
    parser.add_argument(
        "--workdays", type=Path, default=None, help="Override workdays CSV"
    )
    parser.add_argument("--assets-dir", type=Path, default=Path("assets"))
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )
    parser.add_argument(
        "--skip-state-update",
        action="store_true",
        help="Skip update_state runs and execute delivery commands only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to update_state and deliver_outputs.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Pass --verbose to update_state and deliver_outputs.",
    )
    parser.add_argument(
        "--retain-local-scratch",
        action="store_true",
        help="Pass --retain-local-scratch to update_state.",
    )
    parser.add_argument(
        "--init-compliance-history",
        action="store_true",
        help="Pass --init-compliance-history to update_state.",
    )
    parser.add_argument(
        "--allow-new-client-ids",
        action="store_true",
        help="Pass --allow-new-client-ids to update_state.",
    )
    parser.add_argument(
        "--deliver",
        action="append",
        default=[],
        choices=(
            "sharepoint.panorama.diff.xlsx",
            "sharepoint.action_queue.xlsx",
            "sharepoint.overdue.pdf",
            "sharepoint.suspension.pdf",
        ),
        help=(
            "Output ID to deliver per day; repeat as needed. "
            "Defaults to no delivery unless --derive-* legacy flags are used."
        ),
    )
    parser.add_argument(
        "--source",
        choices=("panorama", "pear"),
        default=None,
        help=(
            "Source selector for update_state and deliver_outputs. "
            "Required unless --skip-state-update is used with no deliveries."
        ),
    )
    parser.add_argument(
        "--derive-reports",
        action="store_true",
        help=(
            "Convenience alias for --deliver sharepoint.overdue.pdf and "
            "--deliver sharepoint.suspension.pdf."
        ),
    )
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--wave",
        type=str,
        default=None,
        help="Scope wave value from school_reference (or ALL).",
    )
    scope_group.add_argument(
        "--level",
        type=str,
        default=None,
        help="Scope level value from school_reference (or ALL).",
    )
    scope_group.add_argument(
        "--school",
        type=str,
        default=None,
        help="Scope value for deliver_outputs --school (or ALL).",
    )
    args = parser.parse_args(argv)

    if any(
        value is not None and not str(value).strip()
        for value in (args.wave, args.level, args.school)
    ):
        parser.error("--wave/--level/--school require non-empty values")

    if args.school is not None:
        try:
            normalized_school, _ = normalize_school_scope_value(args.school)
        except ValueError as exc:
            parser.error(str(exc))
        args.school = normalized_school

    selected_scope_count = sum(
        value is not None for value in (args.wave, args.level, args.school)
    )
    if args.source == "pear" and (
        args.init_compliance_history or args.allow_new_client_ids
    ):
        parser.error(
            "--init-compliance-history and --allow-new-client-ids require --source panorama"
        )
    if args.source != "pear":
        if args.allow_new_client_ids and selected_scope_count != 1:
            parser.error(
                "--allow-new-client-ids requires exactly one scope flag: "
                "--wave, --level, or --school"
            )
        if args.init_compliance_history and args.wave is None:
            parser.error("--init-compliance-history requires --wave")

    start_date = parse_date_token(args.start_date)
    end_date = parse_date_token(args.end_date) if args.end_date else date.today()
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date")

    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)
    if args.wave is not None or args.level is not None:
        reference_path = runtime.required_path("reference")
        reference = load_school_reference(reference_path)
        allowed_waves, allowed_levels = collect_scope_values(reference)
        try:
            if args.wave is not None:
                args.wave, _ = normalize_wave_scope_value(
                    args.wave,
                    allowed_values=allowed_waves,
                )
            if args.level is not None:
                args.level, _ = normalize_level_scope_value(
                    args.level,
                    allowed_values=allowed_levels,
                )
        except ValueError as exc:
            parser.error(str(exc))

    if args.workdays is not None:
        workdays_path = runtime.resolve_path(args.workdays, "--workdays")
    else:
        workdays_path = runtime.run_path("workdays_csv")
    runtime.validate_files(
        reference_path=None,
        require_reference=False,
        workdays_path=workdays_path,
        require_workdays=True,
    )

    assets_dir = runtime.optional_path(args.assets_dir)
    if assets_dir is None:
        assets_dir = PROJECT_ROOT / args.assets_dir
    elif not assets_dir.is_absolute():
        assets_dir = (PROJECT_ROOT / assets_dir).resolve()
    workdays = load_workdays_map(
        start_date,
        end_date,
        workdays_path,
        assets_dir,
    )
    business_days = [
        day
        for day in date_range(start_date, end_date)
        if workdays.get(day) and workdays[day].business_day
    ]
    if not business_days:
        _log("No business days found in requested range.")
        return 0

    deliver_ids: list[str] = list(args.deliver)
    if args.derive_reports:
        deliver_ids.extend(["sharepoint.overdue.pdf", "sharepoint.suspension.pdf"])
    # Preserve user order while removing duplicates.
    deliver_ids = list(dict.fromkeys(deliver_ids))
    if not args.skip_state_update and args.source is None:
        parser.error("--source is required unless --skip-state-update is used")
    if deliver_ids and args.source is None:
        parser.error("--source is required when --deliver/--derive-reports is used")

    if args.source == "panorama":
        pear_only_requested = sorted(
            output_id for output_id in deliver_ids if output_id in PEAR_ONLY_OUTPUT_IDS
        )
        if pear_only_requested:
            parser.error(
                "--source panorama is incompatible with PEAR-only outputs: "
                + ", ".join(pear_only_requested)
            )
    if args.source == "pear":
        panorama_only_requested = sorted(
            output_id
            for output_id in deliver_ids
            if output_id in PANORAMA_ONLY_OUTPUT_IDS
        )
        if panorama_only_requested:
            parser.error(
                "--source pear is incompatible with Panorama-only outputs: "
                + ", ".join(panorama_only_requested)
            )

    update_scope_args: list[str] = []
    if args.source == "panorama":
        if args.wave is not None:
            update_scope_args = ["--wave", args.wave]
        elif args.level is not None:
            update_scope_args = ["--level", args.level]
        elif args.school is not None:
            update_scope_args = ["--school", args.school]

    scope_args: list[str] = []
    if args.wave is not None:
        scope_args = ["--wave", args.wave]
    elif args.level is not None:
        scope_args = ["--level", args.level]
    elif args.school is not None:
        scope_args = ["--school", args.school]
    elif deliver_ids:
        scope_args = ["--wave", "ALL"]

    for day in business_days:
        run_date = format_date_token(day)
        if not args.skip_state_update:
            _log(f"Running update_state for {run_date}")
            update_cmd = [
                "uv",
                "run",
                "scripts/update_state.py",
                "--source",
                str(args.source),
                "--run-date",
                run_date,
                "--config",
                str(args.config),
            ]
            if args.dry_run:
                update_cmd.append("--dry-run")
            if args.verbose:
                update_cmd.append("--verbose")
            if args.retain_local_scratch:
                update_cmd.append("--retain-local-scratch")
            if args.init_compliance_history:
                update_cmd.append("--init-compliance-history")
            if args.allow_new_client_ids:
                update_cmd.append("--allow-new-client-ids")
            update_cmd.extend(update_scope_args)

            subprocess.run(update_cmd, check=True, cwd=PROJECT_ROOT)

        for output_id in deliver_ids:
            _log(f"Running deliver_outputs for {run_date}: {output_id}")
            deliver_cmd = [
                "uv",
                "run",
                "scripts/deliver_outputs.py",
                output_id,
                "--source",
                str(args.source),
                "--run-date",
                run_date,
                "--config",
                str(args.config),
                *scope_args,
            ]
            if args.dry_run:
                deliver_cmd.append("--dry-run")
            if args.verbose:
                deliver_cmd.append("--verbose")
            subprocess.run(deliver_cmd, check=True, cwd=PROJECT_ROOT)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
