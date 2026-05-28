from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_CHOICES = ("panorama", "pear")
OUTPUT_SOURCE_DEFAULTS = {
    "sharepoint.panorama.diff.xlsx": "panorama",
    "sharepoint.action_queue.xlsx": "pear",
    "sharepoint.overdue.pdf": "panorama",
    "sharepoint.suspension.pdf": "pear",
}
PANORAMA_ONLY_OUTPUTS = {"sharepoint.panorama.diff.xlsx"}
PEAR_ONLY_OUTPUTS = {"sharepoint.action_queue.xlsx"}
DEFAULT_DELIVERIES = (
    ("panorama", "sharepoint.panorama.diff.xlsx"),
    ("pear", "sharepoint.action_queue.xlsx"),
    ("panorama", "sharepoint.overdue.pdf"),
    ("pear", "sharepoint.suspension.pdf"),
)


@dataclass(frozen=True)
class CommandPlan:
    label: str
    command: list[str]
    sharepoint_safe: bool = True


def _parse_delivery(value: str) -> tuple[str, str]:
    raw = value.strip()
    if ":" in raw:
        source, output_id = [part.strip() for part in raw.split(":", 1)]
    else:
        output_id = raw
        source = OUTPUT_SOURCE_DEFAULTS.get(output_id, "")
    if source not in SOURCE_CHOICES:
        raise argparse.ArgumentTypeError(
            "delivery must be OUTPUT_ID or SOURCE:OUTPUT_ID with source "
            "panorama or pear"
        )
    if output_id not in OUTPUT_SOURCE_DEFAULTS:
        raise argparse.ArgumentTypeError(f"unknown delivery output_id: {output_id}")
    if output_id in PANORAMA_ONLY_OUTPUTS and source != "panorama":
        raise argparse.ArgumentTypeError(f"{output_id} requires source panorama")
    if output_id in PEAR_ONLY_OUTPUTS and source != "pear":
        raise argparse.ArgumentTypeError(f"{output_id} requires source pear")
    return source, output_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the lightweight pre-merge acceptance ladder. Delivery checks are "
            "forced into --no-upload --no-download mode, and update-state checks "
            "are dry-run only."
        )
    )
    parser.add_argument(
        "--run-date",
        help="Run date in YYYYMMDD format for dry-run and local delivery checks.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Runtime config path used by command-surface checks.",
    )
    parser.add_argument(
        "--scope-dimension",
        choices=("wave", "level", "school"),
        default="wave",
        help="Scope flag to use for local delivery checks.",
    )
    parser.add_argument(
        "--scope-value",
        default="ALL",
        help="Scope value to use for local delivery checks.",
    )
    parser.add_argument(
        "--update-source",
        action="append",
        choices=SOURCE_CHOICES,
        default=None,
        help="Source to dry-run with update-state. Repeat to select multiple.",
    )
    parser.add_argument(
        "--with-local-delivery",
        action="store_true",
        help=(
            "Run deliver-outputs against local cached state using "
            "--no-upload --no-download."
        ),
    )
    parser.add_argument(
        "--delivery",
        action="append",
        type=_parse_delivery,
        default=None,
        help=(
            "Delivery to run as OUTPUT_ID or SOURCE:OUTPUT_ID. Defaults to a "
            "small matrix covering XLSX/PDF and panorama/pear when "
            "--with-local-delivery is set."
        ),
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Include pytest coverage reporting for ispa_daily_workflow.",
    )
    parser.add_argument(
        "--coverage-html-dir",
        type=Path,
        default=Path("artifacts/coverage/html"),
        help="HTML coverage output directory when --coverage is used.",
    )
    parser.add_argument(
        "--pytest-marker",
        default="not local_data",
        help="Pytest marker expression. Defaults to excluding private local data tests.",
    )
    parser.add_argument(
        "--skip-compile",
        action="store_true",
        help="Skip python -m compileall src.",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip pytest.",
    )
    parser.add_argument(
        "--skip-update-state-dry-run",
        action="store_true",
        help="Skip update-state dry-run command checks.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Pass --verbose to pipeline command-surface checks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command plan without executing it.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue after a failed command and return non-zero at the end.",
    )
    args = parser.parse_args(argv)
    if (
        args.with_local_delivery or not args.skip_update_state_dry_run
    ) and not args.run_date:
        parser.error("--run-date is required for command-surface checks")
    return args


def build_command_plan(
    args: argparse.Namespace,
    *,
    python_executable: str | None = None,
    project_root: Path = PROJECT_ROOT,
) -> list[CommandPlan]:
    python = python_executable or sys.executable
    plans: list[CommandPlan] = []

    if not args.skip_compile:
        plans.append(
            CommandPlan(
                label="compile",
                command=[python, "-m", "compileall", "src"],
            )
        )

    if not args.skip_pytest:
        pytest_command = [python, "-m", "pytest"]
        if args.pytest_marker:
            pytest_command.extend(["-m", args.pytest_marker])
        if args.coverage:
            pytest_command.extend(
                [
                    "--cov=ispa_daily_workflow",
                    "--cov-report=term-missing:skip-covered",
                    f"--cov-report=html:{args.coverage_html_dir}",
                ]
            )
        plans.append(CommandPlan(label="pytest", command=pytest_command))

    if not args.skip_update_state_dry_run:
        for source in args.update_source or list(SOURCE_CHOICES):
            command = [
                python,
                "-m",
                "ispa_daily_workflow.pipeline.update_state",
                "--source",
                source,
                "--run-date",
                args.run_date,
                "--config",
                str(args.config),
                "--dry-run",
            ]
            if args.verbose:
                command.append("--verbose")
            plans.append(
                CommandPlan(
                    label=f"update-state dry-run ({source})",
                    command=command,
                )
            )

    if args.with_local_delivery:
        deliveries = args.delivery or list(DEFAULT_DELIVERIES)
        for source, output_id in deliveries:
            command = [
                python,
                "-m",
                "ispa_daily_workflow.pipeline.deliver_outputs",
                output_id,
                "--source",
                source,
                "--run-date",
                args.run_date,
                "--config",
                str(args.config),
                f"--{args.scope_dimension}",
                args.scope_value,
                "--no-upload",
                "--no-download",
            ]
            if args.verbose:
                command.append("--verbose")
            plans.append(
                CommandPlan(
                    label=f"local delivery ({source} {output_id})",
                    command=command,
                )
            )

    for plan in plans:
        _validate_sharepoint_safety(plan)
    return plans


def _validate_sharepoint_safety(plan: CommandPlan) -> None:
    command_names = {Path(part).name for part in plan.command}
    is_delivery_command = (
        "deliver-outputs" in command_names
        or "ispa_daily_workflow.pipeline.deliver_outputs" in plan.command
    )
    if is_delivery_command:
        if "--no-upload" not in plan.command or "--no-download" not in plan.command:
            raise ValueError(
                f"unsafe delivery command missing no-upload/no-download: {plan.label}"
            )
        if "--upload" in plan.command or "--download" in plan.command:
            raise ValueError(f"unsafe delivery command enables IO: {plan.label}")
    is_update_command = (
        "update-state" in command_names
        or "ispa_daily_workflow.pipeline.update_state" in plan.command
    )
    if is_update_command and "--dry-run" not in plan.command:
        raise ValueError(f"unsafe update-state command missing --dry-run: {plan.label}")


def _run_command(plan: CommandPlan, *, cwd: Path) -> int:
    print(f"\n== {plan.label} ==")
    print(shlex.join(plan.command), flush=True)
    env = os.environ.copy()
    src_path = str(cwd / "src")
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not pythonpath else os.pathsep.join([src_path, pythonpath])
    )
    completed = subprocess.run(plan.command, cwd=cwd, env=env, check=False)
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plans = build_command_plan(args)
    if not plans:
        print("No commands selected.")
        return 0

    print("SharePoint-safe acceptance plan:")
    for plan in plans:
        print(f"  - {plan.label}: {shlex.join(plan.command)}")
    if args.dry_run:
        return 0

    failures: list[tuple[str, int]] = []
    for plan in plans:
        returncode = _run_command(plan, cwd=PROJECT_ROOT)
        if returncode != 0:
            failures.append((plan.label, returncode))
            if not args.keep_going:
                break

    if failures:
        print("\nFailures:")
        for label, returncode in failures:
            print(f"  - {label}: exit {returncode}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
