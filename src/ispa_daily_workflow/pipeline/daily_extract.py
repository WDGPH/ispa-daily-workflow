from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ispa_daily_workflow.ingest import (
    canonical_panorama_filename,
    normalize_and_classify_landing_file,
)
from ispa_daily_workflow.io.adls import (
    AdlsSettings,
)
from ispa_daily_workflow.io.adls_sync import (
    download_landing_files_for_run,
    sync_prior_compliance_histories,
    upload_landing_files,
)
from ispa_daily_workflow.io.adls_sync import (
    landing_prefix as _landing_prefix,
)
from ispa_daily_workflow.io.readers import read_dataframe_with_schema
from ispa_daily_workflow.io.sharepoint_items import SharePointItem
from ispa_daily_workflow.io.sharepoint_session import (
    SharePointSession,
)
from ispa_daily_workflow.io.sharepoint_settings import SharePointSettings
from ispa_daily_workflow.models import AlertRecord
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.schema import ValidationError, resolve_dataset_schema

MAX_SHAREPOINT_SUBFOLDER_DEPTH = 2
TORONTO_STANDARD_OFFSET = timedelta(hours=-5)
TORONTO_DAYLIGHT_OFFSET = timedelta(hours=-4)
try:
    TORONTO_ZONE = ZoneInfo("America/Toronto")
except ZoneInfoNotFoundError:
    TORONTO_ZONE = None


@dataclass(frozen=True)
class _SelectedSharePointFile:
    item: SharePointItem
    created_date_token: str


@dataclass(frozen=True)
class ExtractStageResult:
    created_window_start_utc: str
    created_window_end_utc: str
    destination_url: str
    enumerated_count: int
    non_file_skipped_count: int
    rejected_by_suffix_count: int
    rejected_by_date_count: int
    selected_count: int
    renamed_outputs: list[Path]
    adls_uploaded_paths: list[str]


@dataclass(frozen=True)
class DownloadInputsStageResult:
    remote_prefix: str
    downloaded_paths: list[Path]


@dataclass(frozen=True)
class SyncComplianceHistoryStageResult:
    synced_paths: list[Path]
    warning_alert: AlertRecord | None


def clear_local_inputs(input_raw: Path) -> None:
    if not input_raw.exists():
        return
    for path in input_raw.glob("*"):
        if path.is_file():
            path.unlink()


def cleanup_local_scratch(*, input_raw: Path, standardized_dir: Path) -> None:
    clear_local_inputs(input_raw)
    if standardized_dir.exists():
        shutil.rmtree(standardized_dir, ignore_errors=True)


def _first_sunday(year: int, month: int) -> int:
    day = date(year, month, 1)
    return 1 + ((6 - day.weekday()) % 7)


def _second_sunday(year: int, month: int) -> int:
    return _first_sunday(year, month) + 7


def _toronto_offset_for_local(local_dt: datetime) -> timedelta:
    if local_dt.tzinfo is not None:
        raise ValueError("Expected a naive local datetime for Toronto conversion")
    dst_start_local = datetime(local_dt.year, 3, _second_sunday(local_dt.year, 3), 2, 0)
    dst_end_local = datetime(local_dt.year, 11, _first_sunday(local_dt.year, 11), 2, 0)
    if dst_start_local <= local_dt < dst_end_local:
        return TORONTO_DAYLIGHT_OFFSET
    return TORONTO_STANDARD_OFFSET


def _toronto_offset_for_utc(utc_dt: datetime) -> timedelta:
    if utc_dt.tzinfo is None:
        raise ValueError("Expected a timezone-aware UTC datetime")
    utc = utc_dt.astimezone(timezone.utc)
    year = utc.year
    dst_start_utc = datetime(
        year,
        3,
        _second_sunday(year, 3),
        7,
        0,
        tzinfo=timezone.utc,
    )
    dst_end_utc = datetime(
        year,
        11,
        _first_sunday(year, 11),
        6,
        0,
        tzinfo=timezone.utc,
    )
    if dst_start_utc <= utc < dst_end_utc:
        return TORONTO_DAYLIGHT_OFFSET
    return TORONTO_STANDARD_OFFSET


def _toronto_local_to_utc(local_dt: datetime) -> datetime:
    offset = _toronto_offset_for_local(local_dt)
    return (local_dt - offset).replace(tzinfo=timezone.utc)


def _toronto_date_token_from_utc(utc_dt: datetime) -> str:
    if TORONTO_ZONE is not None:
        return utc_dt.astimezone(TORONTO_ZONE).strftime("%Y%m%d")
    utc = utc_dt.astimezone(timezone.utc)
    local = utc + _toronto_offset_for_utc(utc)
    return local.strftime("%Y%m%d")


def _created_window_utc(run_day: date) -> tuple[datetime, datetime]:
    if TORONTO_ZONE is not None:
        start_local = datetime.combine(run_day, time.min, tzinfo=TORONTO_ZONE)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
    start_local = datetime.combine(run_day, time.min)
    end_local = datetime.combine(run_day + timedelta(days=1), time.min)
    return _toronto_local_to_utc(start_local), _toronto_local_to_utc(end_local)


def _parse_created_utc(value: str | None, *, item_name: str) -> datetime:
    if not value:
        raise RuntimeError(
            f"SharePoint Created timestamp missing for candidate file: {item_name}"
        )
    candidate = value
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise RuntimeError(
            f"SharePoint Created timestamp is invalid for {item_name}: {value}"
        ) from exc
    if parsed.tzinfo is None:
        raise RuntimeError(
            f"SharePoint Created timestamp missing timezone for {item_name}: {value}"
        )
    return parsed.astimezone(timezone.utc)


def extract_stage(
    *,
    run_day: date,
    run_date: str,
    input_raw: Path,
    schema_root: Path,
    reference: SchoolReference,
    sharepoint_settings: SharePointSettings,
    adls_settings: AdlsSettings,
    upload_to_adls: bool,
    strict_headers: bool,
    landing_prefix: str | None = None,
    overwrite_local: bool = True,
) -> ExtractStageResult:
    destination_url = sharepoint_settings.inputs.panorama_overdue
    if not destination_url:
        raise RuntimeError(
            "SharePoint extraction skipped because io.sharepoint.inputs.panorama_overdue is not configured"
        )

    landing_schema = resolve_dataset_schema(
        "landing.panorama.compliance",
        schema_root=schema_root,
    )
    start_utc, end_utc = _created_window_utc(run_day)
    staging_dir = input_raw / ".extract_staging" / run_date

    selected_items: list[_SelectedSharePointFile] = []
    renamed_outputs: list[Path] = []
    adls_uploaded: list[str] = []
    enumerated_count = 0
    non_file_skipped_count = 0
    rejected_by_suffix_count = 0
    rejected_by_date_count = 0

    try:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        with SharePointSession(sharepoint_settings) as session:
            listed_items = session.list_folder_items(
                folder_url=destination_url,
                recursive=True,
                max_depth=MAX_SHAREPOINT_SUBFOLDER_DEPTH,
            )
            enumerated_count = len(listed_items)
            for item in listed_items:
                if not item.is_file:
                    non_file_skipped_count += 1
                    continue
                if Path(item.name).suffix.lower() != ".xls":
                    rejected_by_suffix_count += 1
                    continue

                created_utc = _parse_created_utc(item.created, item_name=item.name)
                if not (start_utc <= created_utc < end_utc):
                    rejected_by_date_count += 1
                    continue

                selected_items.append(
                    _SelectedSharePointFile(
                        item=item,
                        created_date_token=_toronto_date_token_from_utc(created_utc),
                    )
                )

            staged_items: list[SharePointItem] = []
            for selected in selected_items:
                suffix = Path(selected.item.name).suffix.lower() or ".xls"
                staged_items.append(
                    replace(selected.item, name=f"{selected.item.id}{suffix}")
                )

            downloaded = session.download_folder_items(
                folder_url=destination_url,
                output_dir=staging_dir,
                items=staged_items,
                overwrite=overwrite_local,
            )

        selected_by_item_id = {entry.item.id: entry for entry in selected_items}
        seen_targets: dict[str, Path] = {}
        for download in downloaded:
            selected = selected_by_item_id.get(download.item.id)
            if selected is None:
                raise RuntimeError(
                    "Missing SharePoint metadata for downloaded file: "
                    f"{download.local_path.name}"
                )

            _, classification = normalize_and_classify_landing_file(
                file_path=download.local_path,
                landing_schema=landing_schema,
                reference=reference,
                strict_headers=strict_headers,
            )
            target_name = canonical_panorama_filename(
                date_token=selected.created_date_token,
                classification=classification,
                extension="xlsx",
            )
            if target_name in seen_targets:
                previous = seen_targets[target_name]
                raise ValidationError(
                    "Raw input rename collision for "
                    f"{target_name}: {previous.name} and {download.local_path.name}"
                )

            target_path = input_raw / target_name
            if target_path.exists():
                if not overwrite_local:
                    raise FileExistsError(
                        "Refusing to overwrite existing canonical raw file without "
                        f"overwrite=True: {target_path}"
                    )
                target_path.unlink()
            # Preserve landing header contract while normalizing file format to .xlsx.
            landing_frame = read_dataframe_with_schema(
                download.local_path,
                landing_schema,
                file_format=download.local_path.suffix.lstrip("."),
                as_string=True,
            )
            landing_frame.write_excel(target_path)
            renamed_outputs.append(target_path)
            seen_targets[target_name] = download.local_path

        if upload_to_adls:
            remote_prefix = _landing_prefix(adls_settings, landing_prefix)
            adls_uploaded.extend(
                upload_landing_files(
                    adls_settings,
                    paths=renamed_outputs,
                    prefix=remote_prefix,
                )
            )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return ExtractStageResult(
        created_window_start_utc=start_utc.isoformat().replace("+00:00", "Z"),
        created_window_end_utc=end_utc.isoformat().replace("+00:00", "Z"),
        destination_url=destination_url,
        enumerated_count=enumerated_count,
        non_file_skipped_count=non_file_skipped_count,
        rejected_by_suffix_count=rejected_by_suffix_count,
        rejected_by_date_count=rejected_by_date_count,
        selected_count=len(selected_items),
        renamed_outputs=renamed_outputs,
        adls_uploaded_paths=adls_uploaded,
    )


def download_inputs_stage(
    *,
    run_date: str,
    input_raw: Path,
    adls_settings: AdlsSettings,
    landing_prefix: str | None = None,
) -> DownloadInputsStageResult:
    clear_local_inputs(input_raw)
    remote_prefix = _landing_prefix(adls_settings, landing_prefix)
    downloaded = download_landing_files_for_run(
        adls_settings,
        run_date=run_date,
        output_dir=input_raw,
        prefix=remote_prefix,
    )
    if not downloaded:
        raise RuntimeError(
            "ADLS input download found no files under "
            f"{remote_prefix} for run_date={run_date}"
        )
    return DownloadInputsStageResult(
        remote_prefix=remote_prefix,
        downloaded_paths=downloaded,
    )


def sync_compliance_history_stage(
    *,
    run_date: str,
    compliance_history_dir: Path,
    adls_settings: AdlsSettings,
    scope_description: str,
) -> SyncComplianceHistoryStageResult:
    synced = sync_prior_compliance_histories(
        adls_settings,
        compliance_history_dir=compliance_history_dir,
        run_date=run_date,
    )
    warning_alert: AlertRecord | None = None
    if not synced:
        warning_message = (
            "No prior compliance_history snapshots were found in ADLS processed storage "
            f"before run_date={run_date} (scope: {scope_description})."
        )
        warning_alert = AlertRecord(
            code="compliance_history_sync_empty",
            level="warning",
            message=warning_message,
            context={"run_date": run_date, "scope": scope_description},
        )
    return SyncComplianceHistoryStageResult(
        synced_paths=synced, warning_alert=warning_alert
    )
