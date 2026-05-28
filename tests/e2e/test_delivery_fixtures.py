from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import openpyxl
import polars as pl
import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "e2e"
RUN_DATE = "20260224"
PREVIOUS_DATE = "20260223"
SLICE_TOKEN = "elementary1"
DATE_COLUMNS = {"date_of_birth", "compliant", "rescind_date", "action_date"}
TYPST_BIN = shutil.which("typst")


@dataclass(frozen=True)
class FixtureRuntime:
    config_path: Path
    output_root: Path


def _read_fixture_csv(path: Path) -> pl.DataFrame:
    frame = pl.read_csv(path, infer_schema=False, null_values=[""])
    date_expressions = [
        pl.col(column).str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias(column)
        for column in DATE_COLUMNS
        if column in frame.columns
    ]
    if date_expressions:
        frame = frame.with_columns(date_expressions)
    return frame


def _write_csv_fixture_as_parquet(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _read_fixture_csv(source).write_parquet(destination)


def _write_config(config_path: Path, *, output_root: Path, profile_root: Path) -> None:
    config: dict[str, Any] = {
        "run": {
            "timezone": "Etc/UTC",
            "workdays_csv": str(profile_root / "workdays.csv"),
            "school_year_start_month": 9,
        },
        "paths": {
            "input_root": str(config_path.parent.parent / "input"),
            "output_root": str(output_root),
            "artifacts_root": str(config_path.parent.parent / "artifacts"),
            "logs_root": str(config_path.parent.parent / "logs"),
            "reference": str(profile_root / "school_reference.json"),
        },
        "validation": {
            "schemas": str(PROJECT_ROOT / "schema"),
            "strict_headers": True,
        },
        "outputs": {
            "pdf": {
                "logo": str(PROJECT_ROOT / "profile.example" / "logo.pdf"),
                "typst_bin": TYPST_BIN or "/bin/true",
            }
        },
        "io": {
            "adls": {
                "secrets_path": str(config_path.parent.parent / "secrets" / "adls"),
                "secret_files": {
                    "tenant_id": "tenant_id",
                    "client_id": "client_id",
                    "client_secret": "client_secret",
                    "storage_account": "storage_account",
                    "container": "container",
                },
                "destinations": {
                    "landing_prefix": "Landing/fictional_panorama",
                    "processed_prefix": "Processed/fictional_panorama",
                    "pear_landing_prefix": "Landing/fictional_pear",
                    "pear_processed_prefix": "Processed/fictional_pear",
                },
            },
            "sharepoint": {
                "secrets_path": str(
                    config_path.parent.parent / "secrets" / "sharepoint"
                ),
                "secret_files": {
                    "tenant_id": "tenant_id",
                    "client_id": "client_id",
                    "client_secret": "client_secret",
                },
                "inputs": {},
                "outputs": {
                    "list_difference": "https://example.invalid/list-difference",
                    "action_queue": "https://example.invalid/action-queue",
                    "pdf": {
                        "elementary_root": "https://example.invalid/pdf/elementary",
                        "secondary_root": "https://example.invalid/pdf/secondary",
                    },
                },
            },
        },
        "logging": {
            "format": "text",
            "level": "WARNING",
            "redact_long_numeric_ids": False,
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )


def _run_cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        "command failed\n"
        f"command: {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _rows_from_xlsx(path: Path) -> list[dict[str, object]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        raw_rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    assert raw_rows
    headers = [str(value) for value in raw_rows[0]]
    return [
        dict(zip(headers, row, strict=True))
        for row in raw_rows[1:]
        if any(value is not None for value in row)
    ]


def _require_typst() -> None:
    if TYPST_BIN is None:
        pytest.skip("typst binary is required for PDF E2E fixture tests")


def _assert_pdf_was_rendered(path: Path) -> None:
    assert path.exists(), f"expected PDF output at {path}"
    assert path.stat().st_size > 1000
    with path.open("rb") as handle:
        assert handle.read(5) == b"%PDF-"


@pytest.fixture()
def fixture_runtime(tmp_path: Path) -> Iterator[FixtureRuntime]:
    runtime_parent = PROJECT_ROOT / "output" / "pytest-e2e" / tmp_path.parent.name
    runtime_root = runtime_parent / tmp_path.name
    shutil.rmtree(runtime_root, ignore_errors=True)
    output_root = runtime_root / "output"
    profile_root = runtime_root / "profile"
    config_path = profile_root / "config.yaml"
    profile_root.mkdir(parents=True)
    try:
        shutil.copy2(FIXTURE_ROOT / "school_reference.json", profile_root)
        shutil.copy2(FIXTURE_ROOT / "workdays.csv", profile_root)
        shutil.copy2(FIXTURE_ROOT / "privacy_notice.typ", profile_root)

        compliance_history_dir = output_root / "compliance_history"
        _write_csv_fixture_as_parquet(
            FIXTURE_ROOT / "panorama_compliance_history_20260223_elementary1.csv",
            compliance_history_dir
            / f"{PREVIOUS_DATE}_panorama_{SLICE_TOKEN}_compliance_history.parquet",
        )
        _write_csv_fixture_as_parquet(
            FIXTURE_ROOT / "panorama_compliance_history_20260224_elementary1.csv",
            compliance_history_dir
            / f"{RUN_DATE}_panorama_{SLICE_TOKEN}_compliance_history.parquet",
        )

        pear_processed_dir = output_root / "pear_processed"
        for source in sorted((FIXTURE_ROOT / "pear_processed").glob("*.csv")):
            _write_csv_fixture_as_parquet(
                source,
                pear_processed_dir / source.with_suffix(".parquet").name,
            )

        _write_config(config_path, output_root=output_root, profile_root=profile_root)
        _run_cli(
            [
                sys.executable,
                "-m",
                "panorama_compliance.pipeline.derive_pear_state",
                "--run-date",
                RUN_DATE,
                "--config",
                str(config_path),
            ]
        )
        yield FixtureRuntime(config_path=config_path, output_root=output_root)
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)
        for path in (runtime_parent, runtime_parent.parent):
            try:
                path.rmdir()
            except OSError:
                pass


@pytest.mark.sharepoint_safe
def test_fictional_pear_fixture_delivers_action_queue_locally(
    fixture_runtime: FixtureRuntime,
) -> None:
    result = _run_cli(
        [
            sys.executable,
            "-m",
            "panorama_compliance.pipeline.deliver_outputs",
            "sharepoint.action_queue.xlsx",
            "--source",
            "pear",
            "--run-date",
            RUN_DATE,
            "--config",
            str(fixture_runtime.config_path),
            "--wave",
            "ELEMENTARY1",
            "--no-upload",
            "--no-download",
        ]
    )

    assert "Mode: local-only" in result.stdout
    assert "Uploads performed: 0" in result.stdout
    output_path = (
        fixture_runtime.output_root
        / "inspect"
        / RUN_DATE
        / "source=pear"
        / "io=u0_d0"
        / "sharepoint.action_queue.xlsx"
        / "wave=ELEMENTARY1"
        / "output"
        / "action_queue"
        / f"{RUN_DATE}_{SLICE_TOKEN}_action_queue.xlsx"
    )
    rows = _rows_from_xlsx(output_path)
    assert [str(row["client_id"]).zfill(10) for row in rows] == ["0000000102"]
    assert rows[0]["action_required"] == "rescind"


@pytest.mark.sharepoint_safe
def test_fictional_panorama_fixture_delivers_daily_diff_locally(
    fixture_runtime: FixtureRuntime,
) -> None:
    result = _run_cli(
        [
            sys.executable,
            "-m",
            "panorama_compliance.pipeline.deliver_outputs",
            "sharepoint.panorama.diff.xlsx",
            "--source",
            "panorama",
            "--run-date",
            RUN_DATE,
            "--config",
            str(fixture_runtime.config_path),
            "--wave",
            "ELEMENTARY1",
            "--no-upload",
            "--no-download",
        ]
    )

    assert "Mode: local-only" in result.stdout
    assert "Uploads performed: 0" in result.stdout
    output_path = (
        fixture_runtime.output_root
        / "inspect"
        / RUN_DATE
        / "source=panorama"
        / "io=u0_d0"
        / "sharepoint.panorama.diff.xlsx"
        / "wave=ELEMENTARY1"
        / "output"
        / "diffs"
        / f"{RUN_DATE}_{PREVIOUS_DATE}_panorama_{SLICE_TOKEN}_became_compliant.xlsx"
    )
    rows = _rows_from_xlsx(output_path)
    assert [str(row["client_id"]).zfill(10) for row in rows] == ["0000000002"]
    assert rows[0]["school_name"] == "FICTIONAL ALPHA SCHOOL"


@pytest.mark.sharepoint_safe
def test_fictional_panorama_fixture_delivers_overdue_pdf_locally(
    fixture_runtime: FixtureRuntime,
) -> None:
    _require_typst()

    result = _run_cli(
        [
            sys.executable,
            "-m",
            "panorama_compliance.pipeline.deliver_outputs",
            "sharepoint.overdue.pdf",
            "--source",
            "panorama",
            "--run-date",
            RUN_DATE,
            "--config",
            str(fixture_runtime.config_path),
            "--wave",
            "ELEMENTARY1",
            "--no-upload",
            "--no-download",
        ]
    )

    assert "Mode: local-only" in result.stdout
    assert "Uploads performed: 0" in result.stdout
    output_path = (
        fixture_runtime.output_root
        / "inspect"
        / RUN_DATE
        / "source=panorama"
        / "io=u0_d0"
        / "sharepoint.overdue.pdf"
        / "wave=ELEMENTARY1"
        / "output"
        / "reports"
        / "Elementary_Schools"
        / "FICTIONAL ALPHA SCHOOL - 1001"
        / f"{RUN_DATE}_FICTIONAL_ALPHA_SCHOOL_1001_OVERDUE_LIST.pdf"
    )
    _assert_pdf_was_rendered(output_path)


@pytest.mark.sharepoint_safe
def test_fictional_pear_fixture_delivers_suspension_pdf_locally(
    fixture_runtime: FixtureRuntime,
) -> None:
    _require_typst()

    result = _run_cli(
        [
            sys.executable,
            "-m",
            "panorama_compliance.pipeline.deliver_outputs",
            "sharepoint.suspension.pdf",
            "--source",
            "pear",
            "--run-date",
            RUN_DATE,
            "--config",
            str(fixture_runtime.config_path),
            "--wave",
            "ELEMENTARY1",
            "--no-upload",
            "--no-download",
        ]
    )

    assert "Mode: local-only" in result.stdout
    assert "Uploads performed: 0" in result.stdout
    output_path = (
        fixture_runtime.output_root
        / "inspect"
        / RUN_DATE
        / "source=pear"
        / "io=u0_d0"
        / "sharepoint.suspension.pdf"
        / "wave=ELEMENTARY1"
        / "output"
        / "reports"
        / "Elementary_Schools"
        / "FICTIONAL ALPHA SCHOOL - 1001"
        / f"{RUN_DATE}_FICTIONAL_ALPHA_SCHOOL_1001_SUSPENSION_LIST.pdf"
    )
    _assert_pdf_was_rendered(output_path)
