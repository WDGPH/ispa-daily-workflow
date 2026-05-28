from __future__ import annotations

from pathlib import Path

import pytest

from scripts.local_acceptance import build_command_plan, parse_args


def test_local_delivery_plan_forces_no_upload_no_download() -> None:
    args = parse_args(
        [
            "--run-date",
            "20260224",
            "--with-local-delivery",
            "--skip-compile",
            "--skip-pytest",
            "--skip-update-state-dry-run",
        ]
    )

    plans = build_command_plan(
        args,
        python_executable="python",
        project_root=Path("/repo"),
    )

    assert plans
    for plan in plans:
        assert Path(plan.command[1]).name == "deliver_outputs.py"
        assert "--no-upload" in plan.command
        assert "--no-download" in plan.command
        assert "--upload" not in plan.command
        assert "--download" not in plan.command


def test_update_state_plan_is_dry_run_only() -> None:
    args = parse_args(
        [
            "--run-date",
            "20260224",
            "--skip-compile",
            "--skip-pytest",
        ]
    )

    plans = build_command_plan(
        args,
        python_executable="python",
        project_root=Path("/repo"),
    )

    assert {plan.label for plan in plans} == {
        "update-state dry-run (panorama)",
        "update-state dry-run (pear)",
    }
    assert all("--dry-run" in plan.command for plan in plans)


def test_run_date_required_for_command_surface_checks() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--skip-compile", "--skip-pytest"])
