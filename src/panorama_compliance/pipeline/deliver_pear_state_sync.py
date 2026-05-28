from __future__ import annotations

import logging
import re
from pathlib import Path

from panorama_compliance.domain.pear.state import (
    derive_pear_state,
    discover_latest_pear_processed_inputs,
    write_pear_authoritative_suspension_outputs,
    write_pear_state_outputs,
)
from panorama_compliance.io.adapters import AdlsStateStore, StateStore
from panorama_compliance.io.local_artifacts import clear_matching_files
from panorama_compliance.io.workdays import load_workdays, parse_run_date
from panorama_compliance.reference import SchoolReference


PEAR_PROCESSED_FILENAME_PATTERN = re.compile(
    r"^\d{8}_(?:"
    r"pear_(?:overdue_list|suspension_list|suspension_vs_overdue|suspension_operational)_[a-z0-9_]+"
    r"|overdue_list_pear"
    r"|suspension_vs_overdue"
    r"|suspension_list_(?:elementary|secondary)"
    r")\.parquet$",
    re.IGNORECASE,
)


def sync_pear_state_from_adls(
    *,
    adls_settings,
    run_date: str,
    schema_root: Path,
    reference: SchoolReference,
    workdays_path: Path,
    pear_processed_dir: Path,
    pear_state_dir: Path,
    continuity_waived_waves: set[str] | None = None,
    strict_headers: bool = True,
    verbose_warning_details: bool = False,
    warning_details: list[str] | None = None,
) -> list[Path]:
    return sync_pear_state_from_store(
        state_store=AdlsStateStore(adls_settings),
        run_date=run_date,
        schema_root=schema_root,
        reference=reference,
        workdays_path=workdays_path,
        pear_processed_dir=pear_processed_dir,
        pear_state_dir=pear_state_dir,
        continuity_waived_waves=continuity_waived_waves,
        strict_headers=strict_headers,
        verbose_warning_details=verbose_warning_details,
        warning_details=warning_details,
    )


def _pear_processed_prefix(state_store: StateStore) -> str | None:
    settings = getattr(state_store, "settings", None)
    destinations = getattr(settings, "destinations", None)
    value = getattr(destinations, "pear_processed_prefix", None)
    return str(value) if value is not None else None


def sync_pear_state_from_store(
    *,
    state_store: StateStore,
    run_date: str,
    schema_root: Path,
    reference: SchoolReference,
    workdays_path: Path,
    pear_processed_dir: Path,
    pear_state_dir: Path,
    continuity_waived_waves: set[str] | None = None,
    strict_headers: bool = True,
    verbose_warning_details: bool = False,
    warning_details: list[str] | None = None,
) -> list[Path]:
    prefix = _pear_processed_prefix(state_store)
    if prefix is None or not prefix.strip():
        if state_store.name == "adls":
            raise RuntimeError(
                "PEAR delivery with --download requires "
                "io.adls.destinations.pear_processed_prefix"
            )
        prefix = None
    pear_processed_dir.mkdir(parents=True, exist_ok=True)
    pear_state_dir.mkdir(parents=True, exist_ok=True)
    cleared_processed = clear_matching_files(pear_processed_dir, pattern="*.parquet")
    cleared_state = clear_matching_files(pear_state_dir, pattern="*_pear_*_*.parquet")
    if cleared_processed or cleared_state:
        logging.debug(
            "Cleared local PEAR files before ADLS sync: processed=%s state=%s",
            cleared_processed,
            cleared_state,
        )
    workdays = load_workdays(workdays_path)
    run_day = parse_run_date(run_date)
    run_info = workdays.get(run_day)
    previous_business_day = (
        run_info.previous_business_day if run_info is not None else None
    )
    processed_download_dates = [run_date]
    if previous_business_day is not None:
        processed_download_dates.append(previous_business_day.strftime("%Y%m%d"))
    requested_dates = sorted(set(processed_download_dates))
    logging.debug(
        "Syncing PEAR processed snapshots from %s state store: dates=%s prefix=%s",
        state_store.name,
        ", ".join(requested_dates),
        prefix or "(root)",
    )
    downloaded_processed: list[Path] = []
    downloaded_counts_by_date: dict[str, int] = {}
    for processed_date in requested_dates:
        downloaded_for_date = state_store.download_files_for_date(
            run_date=processed_date,
            output_dir=pear_processed_dir,
            prefix=prefix,
            filename_pattern=PEAR_PROCESSED_FILENAME_PATTERN,
        )
        downloaded_counts_by_date[processed_date] = len(downloaded_for_date)
        downloaded_processed.extend(downloaded_for_date)
    if not downloaded_processed:
        raise RuntimeError(
            "No PEAR processed snapshots were downloaded from "
            f"{state_store.name} state store for run_date={run_date} "
            f"prefix={prefix or '(root)'}"
        )
    selection = discover_latest_pear_processed_inputs(
        processed_dir=pear_processed_dir,
        run_date=run_date,
    )
    result = derive_pear_state(
        selection=selection,
        schema_root=schema_root,
        reference=reference,
        authoritative_dir=pear_processed_dir,
        workdays=workdays,
        continuity_waived_waves=continuity_waived_waves,
        strict_headers=strict_headers,
    )
    continuity_count = len(result.continuity_warning_messages)
    overdue_count = len(result.overdue_day_over_day_warning_messages)
    disappearance_count = len(result.disappearance_warning_messages)
    unresolved_disappearance_count = int(
        result.disappearance_summary.get("unresolved_count", 0)
    )
    resolved_disappearance_count = int(
        result.disappearance_summary.get("resolved_count", 0)
    )
    if continuity_count or overdue_count or disappearance_count:
        logging.warning(
            "PEAR state warnings during sync: continuity=%s overdue_day_over_day=%s disappearance_rehydration=%s resolved=%s unresolved=%s",
            continuity_count,
            overdue_count,
            disappearance_count,
            resolved_disappearance_count,
            unresolved_disappearance_count,
        )
    if verbose_warning_details:
        for message in result.continuity_warning_messages:
            logging.warning("PEAR suspension continuity warning: %s", message)
        for message in result.overdue_day_over_day_warning_messages:
            logging.warning("PEAR overdue day-over-day warning: %s", message)
        for message in result.disappearance_warning_messages:
            logging.warning("PEAR disappearance rehydration warning: %s", message)
    if warning_details is not None:
        warning_details.extend(
            f"PEAR continuity warning: {message}"
            for message in result.continuity_warning_messages
        )
        warning_details.extend(
            f"PEAR overdue day-over-day warning: {message}"
            for message in result.overdue_day_over_day_warning_messages
        )
        warning_details.extend(
            f"PEAR disappearance warning: {message}"
            for message in result.disappearance_warning_messages
        )
    rescind_patch_summary = result.rescind_patch_summary
    rescind_action_rows_raw = rescind_patch_summary.get("rescind_action_rows", 0)
    rescind_action_rows = (
        rescind_action_rows_raw if isinstance(rescind_action_rows_raw, int) else 0
    )
    if rescind_action_rows > 0:
        logging.debug(
            "PEAR state rescind patch summary: action_rows=%s matched_rescind_rows=%s patched_rescind_rows=%s preserved_existing_rescind_rows=%s unmatched_rescind_action_rows=%s",
            rescind_action_rows,
            rescind_patch_summary.get("matched_rescind_rows", 0),
            rescind_patch_summary.get("patched_rescind_rows", 0),
            rescind_patch_summary.get("preserved_existing_rescind_rows", 0),
            rescind_patch_summary.get("unmatched_rescind_action_rows", 0),
        )
    written_state = write_pear_state_outputs(
        frames=result.frames,
        run_date=run_date,
        output_dir=pear_state_dir,
        formats=("parquet",),
    )
    written_authoritative = write_pear_authoritative_suspension_outputs(
        suspension_operational=result.frames["suspension_operational"],
        run_date=run_date,
        output_dir=pear_processed_dir,
    )
    written_state.extend(written_authoritative)
    disappearance_path = (
        pear_state_dir / f"{run_date}_pear_disappearance_evidence.parquet"
    )
    if result.disappearance_evidence.is_empty():
        disappearance_path.unlink(missing_ok=True)
    else:
        result.disappearance_evidence.write_parquet(disappearance_path)
        written_state.append(disappearance_path)

    logging.info(
        "PEAR state sync complete: processed_files=%s dates=%s derived_files=%s",
        len(downloaded_processed),
        ", ".join(
            f"{date_token}:{count}"
            for date_token, count in sorted(downloaded_counts_by_date.items())
        ),
        len(written_state),
    )
    return written_state
