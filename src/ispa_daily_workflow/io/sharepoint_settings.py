from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ispa_daily_workflow.config import (
    get_io_config,
    require_config_mapping,
    require_config_value,
)


@dataclass(frozen=True)
class SharePointPdfOutputs:
    elementary_root: str | None
    secondary_root: str | None


@dataclass(frozen=True)
class SharePointInputs:
    panorama_overdue: str | None
    pear_overdue: str | None
    pear_suspension_vs_overdue: str | None
    pear_suspension: str | None


@dataclass(frozen=True)
class SharePointOutputs:
    list_difference: str | None
    action_queue: str | None
    pdf: SharePointPdfOutputs


@dataclass(frozen=True)
class SharePointSettings:
    secrets_path: Path
    secret_files: dict[str, str]
    inputs: SharePointInputs
    outputs: SharePointOutputs

    def destination_urls(self) -> dict[str, str]:
        urls: dict[str, str] = {}
        if self.inputs.panorama_overdue:
            urls["inputs.panorama_overdue"] = self.inputs.panorama_overdue
        if self.inputs.pear_overdue:
            urls["inputs.pear_overdue"] = self.inputs.pear_overdue
        if self.inputs.pear_suspension_vs_overdue:
            urls["inputs.pear_suspension_vs_overdue"] = (
                self.inputs.pear_suspension_vs_overdue
            )
        if self.inputs.pear_suspension:
            urls["inputs.pear_suspension"] = self.inputs.pear_suspension
        if self.outputs.list_difference:
            urls["outputs.list_difference"] = self.outputs.list_difference
        if self.outputs.action_queue:
            urls["outputs.action_queue"] = self.outputs.action_queue
        if self.outputs.pdf.elementary_root:
            urls["outputs.pdf.elementary_root"] = self.outputs.pdf.elementary_root
        if self.outputs.pdf.secondary_root:
            urls["outputs.pdf.secondary_root"] = self.outputs.pdf.secondary_root
        return urls


@dataclass(frozen=True)
class SharePointPublishSummary:
    uploaded_urls: list[str]
    deleted_overdue: list[str]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_sharepoint_settings(config: dict) -> SharePointSettings:
    io_config = get_io_config(config)
    sharepoint = require_config_mapping(io_config, "sharepoint", label="io.sharepoint")
    inputs_cfg = require_config_mapping(
        sharepoint,
        "inputs",
        label="io.sharepoint.inputs",
    )
    outputs_cfg = require_config_mapping(
        sharepoint,
        "outputs",
        label="io.sharepoint.outputs",
    )
    outputs_pdf_cfg = (
        outputs_cfg.get("pdf", {}) if isinstance(outputs_cfg.get("pdf"), dict) else {}
    )
    secret_files_cfg = require_config_mapping(
        sharepoint,
        "secret_files",
        label="io.sharepoint.secret_files",
    )
    secret_files: dict[str, str] = {}
    for key in ("tenant_id", "client_id", "client_secret"):
        secret_files[key] = str(
            require_config_value(
                secret_files_cfg,
                key,
                label=f"io.sharepoint.secret_files.{key}",
            )
        )

    return SharePointSettings(
        secrets_path=Path(
            str(
                require_config_value(
                    sharepoint,
                    "secrets_path",
                    label="io.sharepoint.secrets_path",
                )
            )
        ),
        secret_files=secret_files,
        inputs=SharePointInputs(
            panorama_overdue=_optional_str(inputs_cfg.get("panorama_overdue")),
            pear_overdue=_optional_str(inputs_cfg.get("pear_overdue")),
            pear_suspension_vs_overdue=_optional_str(
                inputs_cfg.get("pear_suspension_vs_overdue")
            ),
            pear_suspension=_optional_str(inputs_cfg.get("pear_suspension")),
        ),
        outputs=SharePointOutputs(
            list_difference=_optional_str(outputs_cfg.get("list_difference")),
            action_queue=_optional_str(outputs_cfg.get("action_queue")),
            pdf=SharePointPdfOutputs(
                elementary_root=_optional_str(outputs_pdf_cfg.get("elementary_root")),
                secondary_root=_optional_str(outputs_pdf_cfg.get("secondary_root")),
            ),
        ),
    )


__all__ = [
    "SharePointInputs",
    "SharePointOutputs",
    "SharePointPdfOutputs",
    "SharePointPublishSummary",
    "SharePointSettings",
    "load_sharepoint_settings",
]
