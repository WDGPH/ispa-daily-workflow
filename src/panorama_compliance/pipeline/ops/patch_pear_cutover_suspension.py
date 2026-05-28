from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[4]

from panorama_compliance.config import (
    ensure_dir,
    get_paths_config,
    load_config,
    require_config_value,
    resolve_required_path,
)
from panorama_compliance.ingest.combine import wave_to_token
from panorama_compliance.io.adls import load_adls_settings, upload_paths
from panorama_compliance.io.workdays import parse_run_date
from panorama_compliance.domain.delivery.routing import parse_scope_selection
from panorama_compliance.quality import write_manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a one-off PEAR suspension cutover patch file by removing PEAR rows "
            "that are absent from yesterday's Panorama overdue list and rescinded on "
            "run_date. Optionally upload patched outputs to ADLS processed prefix."
        )
    )
    parser.add_argument(
        "--run-date",
        required=True,
        type=str,
        help="Run date in YYYYMMDD format for PEAR suspension operational source.",
    )
    parser.add_argument(
        "--previous-date",
        required=True,
        type=str,
        help="Previous Panorama overdue date in YYYYMMDD format.",
    )
    parser.add_argument(
        "--wave",
        required=True,
        type=str,
        help="Wave value for cutover patching (for example: ELEMENTARY2).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )
    parser.add_argument(
        "--pear-suspension-file",
        type=Path,
        default=None,
        help=(
            "Override source PEAR suspension operational parquet. Default: "
            "output/pear_state/YYYYMMDD_pear_<slice>_suspension_operational.parquet"
        ),
    )
    parser.add_argument(
        "--panorama-overdue-file",
        type=Path,
        default=None,
        help=(
            "Override source Panorama overdue parquet. Default: "
            "output/combined/YYYYMMDD_panorama_<slice>_noncompliant.parquet"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for patched files (default: output/cutover_patch).",
    )
    parser.add_argument(
        "--patch-tag",
        type=str,
        default="cutover_patch_v1",
        help="Unique filename tag for patch artifacts (default: cutover_patch_v1).",
    )
    parser.add_argument(
        "--upload-to-adls",
        action="store_true",
        help=(
            "Upload patch artifacts to io.adls.destinations.pear_processed_prefix "
            "(flat placement under Processed/pear_compliance/)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute patch outputs and print preflight summary without writing files, "
            "writing manifests, or uploading."
        ),
    )
    return parser.parse_args(argv)


def _normalize_ids(frame: pl.DataFrame, *, label: str) -> pl.DataFrame:
    required = {"client_id", "school_id"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}")
    output = frame.with_columns(
        pl.col("client_id")
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .alias("client_id"),
        pl.col("school_id")
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .alias("school_id"),
    ).filter(
        pl.col("client_id").is_not_null()
        & (pl.col("client_id") != "")
        & pl.col("school_id").is_not_null()
        & (pl.col("school_id") != "")
    )
    return output


def _build_cutover_patch(
    *,
    suspension_df: pl.DataFrame,
    panorama_overdue_df: pl.DataFrame,
    run_day: date,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    if "rescind_date" not in suspension_df.columns:
        raise ValueError("suspension_df missing required column: rescind_date")
    suspension_norm = _normalize_ids(suspension_df, label="suspension_df").with_columns(
        pl.col("rescind_date").cast(pl.Date, strict=False).alias("rescind_date")
    )
    overdue_norm = _normalize_ids(panorama_overdue_df, label="panorama_overdue_df")
    overdue_ids = overdue_norm.select("client_id").unique()
    pear_only = suspension_norm.join(overdue_ids, on="client_id", how="anti")
    excluded = pear_only.filter(pl.col("rescind_date") == pl.lit(run_day))
    patched = suspension_norm.join(
        excluded.select("client_id").unique(),
        on="client_id",
        how="anti",
    )
    return patched, excluded


def _rescind_distribution(frame: pl.DataFrame) -> list[dict[str, object]]:
    rows = frame.group_by("rescind_date").len().sort("rescind_date").to_dicts()
    output: list[dict[str, object]] = []
    for row in rows:
        rescind = row.get("rescind_date")
        if isinstance(rescind, date):
            rescind_display: str | None = rescind.isoformat()
        elif rescind is None:
            rescind_display = None
        else:
            rescind_display = str(rescind)
        output.append({"rescind_date": rescind_display, "count": int(row["len"])})
    return output


def _print_preflight(
    *,
    args: argparse.Namespace,
    scope_value: str,
    source_suspension_path: Path,
    source_overdue_path: Path,
    output_dir: Path,
    patched_path: Path,
    excluded_path: Path,
    source_rows: int,
    removed_rows: int,
    patched_rows: int,
    removed_distribution: list[dict[str, object]],
) -> None:
    print("PEAR cutover patch preflight")
    print(f"  run_date={args.run_date}")
    print(f"  previous_date={args.previous_date}")
    print(f"  wave={scope_value}")
    print(f"  dry_run={args.dry_run}")
    print(f"  upload_to_adls={args.upload_to_adls}")
    print(f"  source_suspension_file={source_suspension_path}")
    print(f"  source_overdue_file={source_overdue_path}")
    print(f"  output_dir={output_dir}")
    print(f"  source_rows={source_rows}")
    print(f"  removed_rows={removed_rows}")
    print(f"  patched_rows={patched_rows}")
    if removed_rows:
        print("  removed_rescind_distribution:")
        for row in removed_distribution:
            print(f"    rescind_date={row['rescind_date']} count={row['count']}")
    print(f"  planned_patched_file={patched_path}")
    print(f"  planned_excluded_file={excluded_path}")


def _resolve_output_dir(
    *, requested_output_dir: Path | None, output_root: Path
) -> Path:
    return requested_output_dir or (output_root / "cutover_patch")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_day = parse_run_date(args.run_date)
    previous_day = parse_run_date(args.previous_date)
    if previous_day >= run_day:
        raise ValueError("--previous-date must be before --run-date")

    scope = parse_scope_selection(wave=args.wave, level=None, school=None)
    if scope.is_all:
        raise ValueError("--wave cannot be ALL for cutover patching")
    slice_token = wave_to_token(scope.normalized_value)

    config, config_path = load_config(config_path=args.config, required=True)
    paths_cfg = get_paths_config(config)
    output_root = resolve_required_path(
        require_config_value(paths_cfg, "output_root", label="paths.output_root"),
        config_path,
        "paths.output_root",
    )
    artifacts_root = resolve_required_path(
        require_config_value(paths_cfg, "artifacts_root", label="paths.artifacts_root"),
        config_path,
        "paths.artifacts_root",
    )

    source_suspension_path = args.pear_suspension_file or (
        output_root
        / "pear_state"
        / f"{args.run_date}_pear_{slice_token}_suspension_operational.parquet"
    )
    source_overdue_path = args.panorama_overdue_file or (
        output_root
        / "combined"
        / f"{args.previous_date}_panorama_{slice_token}_noncompliant.parquet"
    )
    if not source_suspension_path.exists():
        raise FileNotFoundError(
            f"Missing source suspension file: {source_suspension_path}"
        )
    if not source_overdue_path.exists():
        raise FileNotFoundError(f"Missing source overdue file: {source_overdue_path}")

    output_dir = _resolve_output_dir(
        requested_output_dir=args.output_dir,
        output_root=output_root,
    )
    tag = args.patch_tag.strip()
    if not tag:
        raise ValueError("--patch-tag cannot be empty")

    base = f"{args.run_date}_{args.previous_date}_pear_{slice_token}_{tag}"
    patched_path = output_dir / f"{base}_suspension_operational.parquet"
    excluded_path = output_dir / f"{base}_excluded_rescinds.parquet"

    suspension_df = pl.read_parquet(source_suspension_path)
    overdue_df = pl.read_parquet(source_overdue_path)
    patched_df, excluded_df = _build_cutover_patch(
        suspension_df=suspension_df,
        panorama_overdue_df=overdue_df,
        run_day=run_day,
    )
    removed_distribution = _rescind_distribution(excluded_df)
    source_rows = _normalize_ids(suspension_df, label="suspension_df").height
    _print_preflight(
        args=args,
        scope_value=scope.normalized_value,
        source_suspension_path=source_suspension_path,
        source_overdue_path=source_overdue_path,
        output_dir=output_dir,
        patched_path=patched_path,
        excluded_path=excluded_path,
        source_rows=source_rows,
        removed_rows=excluded_df.height,
        patched_rows=patched_df.height,
        removed_distribution=removed_distribution,
    )
    if args.dry_run:
        print(
            "Dry-run complete: no files written, no manifest written, no uploads performed."
        )
        return 0

    output_dir = ensure_dir(output_dir)
    patched_df.write_parquet(patched_path)
    excluded_df.write_parquet(excluded_path)

    uploaded_paths: list[str] = []
    if args.upload_to_adls:
        adls_settings = load_adls_settings(config)
        prefix = adls_settings.destinations.pear_processed_prefix
        if prefix is None or not prefix.strip():
            raise ValueError(
                "io.adls.destinations.pear_processed_prefix is required for --upload-to-adls"
            )
        uploaded_paths = upload_paths(
            adls_settings,
            paths=[patched_path, excluded_path],
            prefix=prefix,
        )

    quality_dir = ensure_dir(artifacts_root / "data_quality")
    manifest_path = write_manifest(
        quality_dir=quality_dir,
        timestamp=datetime.now().strftime("%Y%m%dT%H%M%S"),
        run_date=run_day,
        mode="patch_pear_cutover_suspension",
        datasets={
            "patched_suspension_operational": patched_df,
            "excluded_rescinds": excluded_df,
        },
        file_outputs=[patched_path, excluded_path],
        extra={
            "status": "success",
            "run_date": args.run_date,
            "previous_date": args.previous_date,
            "wave": scope.normalized_value,
            "slice_token": slice_token,
            "source_suspension_file": str(source_suspension_path),
            "source_overdue_file": str(source_overdue_path),
            "patch_tag": tag,
            "removed_count": excluded_df.height,
            "patched_count": patched_df.height,
            "removed_rescind_distribution": removed_distribution,
            "uploaded_count": len(uploaded_paths),
            "uploaded_paths": uploaded_paths,
        },
    )

    print("PEAR cutover patch complete")
    print(f"  run_date={args.run_date}")
    print(f"  previous_date={args.previous_date}")
    print(f"  wave={scope.normalized_value}")
    print(f"  source_suspension_file={source_suspension_path}")
    print(f"  source_overdue_file={source_overdue_path}")
    print(f"  source_rows={source_rows}")
    print(f"  removed_rows={excluded_df.height}")
    print(f"  patched_rows={patched_df.height}")
    if excluded_df.height:
        print("  removed_rescind_distribution:")
        for row in removed_distribution:
            print(f"    rescind_date={row['rescind_date']} count={row['count']}")
    print(f"  patched_file={patched_path}")
    print(f"  excluded_file={excluded_path}")
    print(f"  uploaded={len(uploaded_paths)}")
    for remote in uploaded_paths:
        print(f"    {remote}")
    print(f"Manifest: {manifest_path}")

    print("Use patched file for PDF generation:")
    print(
        "  uv run deliver-outputs sharepoint.suspension.pdf "
        f"--source pear --run-date {args.run_date} --wave {scope.normalized_value} "
        f"--pear-suspension-file {patched_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
