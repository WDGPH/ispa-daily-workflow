from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from ispa_daily_workflow.domain.pear.intake import (
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
)
from ispa_daily_workflow.pipeline.pear_intake_outputs import (
    _processed_outputs_for_entry,
    _ProcessedFile,
)


def _patch_processed_suspension_rescinds(
    *,
    processed_files: list[_ProcessedFile],
) -> dict[str, int | list[str]]:
    suspension_paths = [
        path
        for entry in processed_files
        if entry.report_type == REPORT_SUSPENSION and entry.processed_output is not None
        for path in _processed_outputs_for_entry(entry)
    ]
    action_paths = [
        path
        for entry in processed_files
        if entry.report_type == REPORT_SUSPENSION_VS_OVERDUE
        and entry.processed_output is not None
        for path in _processed_outputs_for_entry(entry)
    ]
    if not suspension_paths or not action_paths:
        return {
            "rescind_action_rows": 0,
            "matched_rows": 0,
            "patched_rows": 0,
            "preserved_existing_rows": 0,
            "unmatched_action_rows": 0,
            "delete_action_rows": 0,
            "matched_delete_rows": 0,
            "unmatched_delete_action_rows": 0,
            "matched_delete_client_ids": [],
            "patched_files": 0,
        }

    action_frames = [pl.read_parquet(path) for path in action_paths]
    action_df = pl.concat(action_frames, how="vertical").with_columns(
        pl.col("client_id").cast(pl.Utf8, strict=False),
        pl.col("action_required").cast(pl.Utf8, strict=False),
        pl.col("action_date").cast(pl.Date, strict=False),
    )
    delete_actions = (
        action_df.filter(pl.col("action_required") == "delete")
        .select("client_id")
        .unique(subset=["client_id"], keep="first", maintain_order=True)
    )
    rescind_actions = (
        action_df.filter(pl.col("action_required") == "rescind")
        .select(
            "client_id",
            pl.col("action_date")
            .cast(pl.Date, strict=False)
            .alias("rescind_action_date"),
        )
        .unique(subset=["client_id"], keep="first", maintain_order=True)
    )
    suspension_frames: dict[Path, pl.DataFrame] = {}
    matched_delete_ids: set[str] = set()
    for suspension_path in suspension_paths:
        frame = pl.read_parquet(suspension_path).with_columns(
            pl.col("client_id").cast(pl.Utf8, strict=False),
            pl.col("rescind_date").cast(pl.Date, strict=False),
        )
        suspension_frames[suspension_path] = frame
        file_delete_matches = (
            frame.select("client_id")
            .join(delete_actions, on="client_id", how="inner")
            .sort("client_id")
            .get_column("client_id")
            .to_list()
        )
        matched_delete_ids.update(str(client_id) for client_id in file_delete_matches)
    delete_action_rows = int(delete_actions.height)
    matched_delete_rows = len(matched_delete_ids)
    matched_delete_client_ids = sorted(matched_delete_ids)
    unmatched_delete_action_rows = delete_action_rows - matched_delete_rows
    if matched_delete_rows:
        logging.warning(
            "Processed suspension patch warning: delete action rows matched current "
            "suspension rows. This is expected mainly in pre-suspension preview windows. "
            "matched_delete_rows=%s delete_action_rows=%s",
            matched_delete_rows,
            delete_action_rows,
        )
        for client_id in sorted(matched_delete_ids):
            logging.warning("  client_id=%s action_required=delete", client_id)
    if rescind_actions.is_empty():
        return {
            "rescind_action_rows": 0,
            "matched_rows": 0,
            "patched_rows": 0,
            "preserved_existing_rows": 0,
            "unmatched_action_rows": 0,
            "delete_action_rows": delete_action_rows,
            "matched_delete_rows": matched_delete_rows,
            "unmatched_delete_action_rows": unmatched_delete_action_rows,
            "matched_delete_client_ids": matched_delete_client_ids,
            "patched_files": 0,
        }

    matched_rows = 0
    patched_rows = 0
    patched_files = 0
    for suspension_path, frame in suspension_frames.items():
        joined = frame.join(rescind_actions, on="client_id", how="left")
        with_patch_flags = joined.with_columns(
            (
                pl.col("rescind_date").is_null()
                & pl.col("rescind_action_date").is_not_null()
            ).alias("_patched_from_action"),
            pl.when(
                pl.col("rescind_date").is_null()
                & pl.col("rescind_action_date").is_not_null()
            )
            .then(pl.col("rescind_action_date"))
            .otherwise(pl.col("rescind_date"))
            .cast(pl.Date, strict=False)
            .alias("rescind_date"),
        )
        file_matched = int(
            joined.filter(pl.col("rescind_action_date").is_not_null()).height
        )
        file_patched = int(
            with_patch_flags.filter(pl.col("_patched_from_action")).height
        )
        matched_rows += file_matched
        patched_rows += file_patched
        patched_frame = (
            with_patch_flags.drop("rescind_action_date")
            .drop("_patched_from_action")
            .select(frame.columns)
        )
        if file_patched:
            patched_files += 1
            patched_frame.write_parquet(suspension_path)

    rescind_action_rows = int(rescind_actions.height)
    return {
        "rescind_action_rows": rescind_action_rows,
        "matched_rows": matched_rows,
        "patched_rows": patched_rows,
        "preserved_existing_rows": matched_rows - patched_rows,
        "unmatched_action_rows": rescind_action_rows - matched_rows,
        "delete_action_rows": delete_action_rows,
        "matched_delete_rows": matched_delete_rows,
        "unmatched_delete_action_rows": unmatched_delete_action_rows,
        "matched_delete_client_ids": matched_delete_client_ids,
        "patched_files": patched_files,
    }
