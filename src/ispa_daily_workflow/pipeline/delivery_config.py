from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ispa_daily_workflow.domain.common.source_policy import (
    PANORAMA_DIFF_OUTPUT_IDS,
    PDF_OUTPUT_IDS,
)
from ispa_daily_workflow.pipeline.workflow_config import load_workflow_config


@dataclass(frozen=True)
class DeliveryRunConfig:
    config: dict
    config_path: Path
    paths_cfg: dict[str, object]
    run_cfg: dict[str, object]
    validation_cfg: dict[str, object]
    logging_cfg: dict[str, object]
    outputs_cfg: dict[str, object]
    strict_headers: bool
    school_year_start_month: int
    output_root: Path
    input_root: Path | None
    compliance_history_dir: Path
    artifacts_root: Path
    logs_root: Path
    schema_root: Path
    reference_path: Path
    workdays_path: Path
    logo_path: Path
    privacy_notice_path: Path
    typst_bin: str


def load_delivery_config(
    args: argparse.Namespace,
    *,
    project_root: Path,
) -> DeliveryRunConfig:
    runtime = load_workflow_config(args, project_root=project_root)
    output_root = runtime.required_path("output_root")
    input_root: Path | None = None
    input_root_value = runtime.paths_cfg.get("input_root")
    if input_root_value is not None:
        input_root = runtime.resolve_path(input_root_value, "paths.input_root")
    artifacts_root = runtime.required_path("artifacts_root")
    logs_root = runtime.required_path("logs_root")
    schema_root = runtime.validation_path("schemas")
    reference_path = runtime.required_path("reference")
    workdays_path = runtime.run_path("workdays_csv")
    logo_path = runtime.logo_path()
    privacy_notice_path = runtime.privacy_notice_path()
    typst_bin = runtime.typst_bin()
    runtime.validate_files(
        reference_path=reference_path,
        workdays_path=workdays_path,
        logo_path=logo_path,
        require_workdays=args.output_id in PANORAMA_DIFF_OUTPUT_IDS
        or args.output_id == "sharepoint.suspension.pdf"
        or (args.source == "pear" and args.download and not args.dry_run),
        require_logo=args.output_id in PDF_OUTPUT_IDS and not args.dry_run,
    )
    return DeliveryRunConfig(
        config=runtime.config,
        config_path=runtime.config_path,
        paths_cfg=runtime.paths_cfg,
        run_cfg=runtime.run_cfg,
        validation_cfg=runtime.validation_cfg,
        logging_cfg=runtime.logging_cfg,
        outputs_cfg=runtime.outputs_cfg,
        strict_headers=runtime.strict_headers,
        school_year_start_month=runtime.school_year_start_month,
        output_root=output_root,
        input_root=input_root,
        compliance_history_dir=output_root / "compliance_history",
        artifacts_root=artifacts_root,
        logs_root=logs_root,
        schema_root=schema_root,
        reference_path=reference_path,
        workdays_path=workdays_path,
        logo_path=logo_path,
        privacy_notice_path=privacy_notice_path,
        typst_bin=typst_bin,
    )


__all__ = ["DeliveryRunConfig", "load_delivery_config"]
