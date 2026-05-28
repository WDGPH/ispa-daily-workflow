from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ispa_daily_workflow.config import (
    get_alerts_config,
    get_logging_config,
    get_outputs_config,
    get_paths_config,
    get_run_config,
    get_validation_config,
    load_config,
    require_config_value,
    resolve_config_bool,
    resolve_config_path,
    resolve_pdf_logo_path,
    resolve_profile_privacy_notice_path,
    resolve_required_path,
    resolve_school_year_start_month,
    validate_required_runtime_files,
)


@dataclass(frozen=True)
class WorkflowConfig:
    config: dict[str, Any]
    config_path: Path
    paths_cfg: dict[str, Any]
    run_cfg: dict[str, Any]
    validation_cfg: dict[str, Any]
    logging_cfg: dict[str, Any]
    outputs_cfg: dict[str, Any]
    alerts_cfg: dict[str, Any]
    strict_headers: bool
    school_year_start_month: int
    project_root: Path

    def required_path(self, key: str, *, label: str | None = None) -> Path:
        config_label = label or f"paths.{key}"
        return resolve_required_path(
            require_config_value(self.paths_cfg, key, label=config_label),
            self.config_path,
            config_label,
        )

    def validation_path(self, key: str, *, label: str | None = None) -> Path:
        config_label = label or f"validation.{key}"
        return resolve_required_path(
            require_config_value(self.validation_cfg, key, label=config_label),
            self.config_path,
            config_label,
        )

    def run_path(self, key: str, *, label: str | None = None) -> Path:
        config_label = label or f"run.{key}"
        return resolve_required_path(
            require_config_value(self.run_cfg, key, label=config_label),
            self.config_path,
            config_label,
        )

    def resolve_path(self, value: str | Path | None, label: str) -> Path:
        return resolve_required_path(value, self.config_path, label)

    def optional_path(self, value: str | Path | None) -> Path | None:
        return resolve_config_path(value, self.config_path)

    def logo_path(self) -> Path:
        return resolve_pdf_logo_path(
            outputs_cfg=self.outputs_cfg,
            config_path=self.config_path,
            project_root=self.project_root,
        )

    def privacy_notice_path(self) -> Path:
        return resolve_profile_privacy_notice_path(
            config_path=self.config_path,
            project_root=self.project_root,
        )

    def typst_bin(self, override: str = "typst") -> str:
        pdf_cfg = self.outputs_cfg.get("pdf", {})
        configured = (
            str(pdf_cfg.get("typst_bin", "typst"))
            if isinstance(pdf_cfg, dict)
            else "typst"
        )
        return configured if override == "typst" else override

    def validate_files(
        self,
        *,
        reference_path: Path | None,
        require_reference: bool = True,
        workdays_path: Path | None = None,
        logo_path: Path | None = None,
        require_workdays: bool = False,
        require_logo: bool = False,
    ) -> None:
        validate_required_runtime_files(
            reference_path=reference_path,
            require_reference=require_reference,
            workdays_path=workdays_path,
            logo_path=logo_path,
            require_workdays=require_workdays,
            require_logo=require_logo,
            profile_root=self.project_root / "profile",
        )


def load_workflow_config(
    args: argparse.Namespace,
    *,
    project_root: Path,
) -> WorkflowConfig:
    config, config_path = load_config(config_path=args.config, required=True)
    if config_path is None:
        raise RuntimeError("Workflow requires a resolved config path.")
    run_cfg = get_run_config(config)
    validation_cfg = get_validation_config(config)
    return WorkflowConfig(
        config=config,
        config_path=config_path,
        paths_cfg=get_paths_config(config),
        run_cfg=run_cfg,
        validation_cfg=validation_cfg,
        logging_cfg=get_logging_config(config),
        outputs_cfg=get_outputs_config(config),
        alerts_cfg=get_alerts_config(config),
        strict_headers=resolve_config_bool(
            validation_cfg,
            "strict_headers",
            default=True,
            label="validation.strict_headers",
        ),
        school_year_start_month=resolve_school_year_start_month(run_cfg),
        project_root=project_root,
    )
