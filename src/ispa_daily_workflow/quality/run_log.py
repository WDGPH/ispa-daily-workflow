from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from ispa_daily_workflow.models import AlertRecord, FileManifest, ReportOutput
from ispa_daily_workflow.quality.manifest import build_manifest_payload


def _to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _artifact_name(run_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("_")
    return f"{safe}.json" if safe else "run.json"


def _serialize_alerts(alerts: Sequence[AlertRecord]) -> list[dict[str, Any]]:
    return [
        {
            "code": alert.code,
            "level": alert.level,
            "message": alert.message,
            "context": alert.context,
        }
        for alert in alerts
    ]


def _summary(alerts: Sequence[AlertRecord]) -> dict[str, Any]:
    warning_count = sum(1 for alert in alerts if alert.level.lower() == "warning")
    error_count = sum(1 for alert in alerts if alert.level.lower() == "error")
    critical_messages = [
        alert.message for alert in alerts if alert.level.lower() in {"warning", "error"}
    ]
    return {
        "warning_count": warning_count,
        "error_count": error_count,
        "alert_count": len(alerts),
        "critical_messages": critical_messages[:10],
    }


def write_run_artifact(
    *,
    runs_dir: Path,
    run_id: str,
    run_date: date,
    mode: str,
    status: str,
    started_at: datetime,
    ended_at: datetime,
    stages: dict[str, dict[str, Any]],
    alerts: Sequence[AlertRecord] | None = None,
    manifests: Sequence[FileManifest] | None = None,
    datasets: dict[str, pl.DataFrame] | None = None,
    report_outputs: Sequence[ReportOutput] | None = None,
    file_outputs: Sequence[Path] | None = None,
    outputs: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    alerts = alerts or []
    quality_payload = build_manifest_payload(
        timestamp=_to_utc_iso(ended_at),
        run_date=run_date,
        mode=mode,
        manifests=manifests,
        datasets=datasets,
        report_outputs=report_outputs,
        file_outputs=file_outputs,
        extra=extra,
    )

    payload = {
        "run_id": run_id,
        "run_date": run_date.isoformat(),
        "mode": mode,
        "status": status,
        "started_at": _to_utc_iso(started_at),
        "ended_at": _to_utc_iso(ended_at),
        "stages": stages,
        "quality": quality_payload,
        "alerts": _serialize_alerts(alerts),
        "summary": _summary(alerts),
        "outputs": outputs or {},
        "failure": failure,
    }

    runs_dir.mkdir(parents=True, exist_ok=True)
    output_path = runs_dir / _artifact_name(run_id)
    payload["artifacts"] = {
        "run_artifact_path": str(output_path),
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path
