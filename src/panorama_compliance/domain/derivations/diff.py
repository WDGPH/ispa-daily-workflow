from __future__ import annotations

import polars as pl
from pathlib import Path

from panorama_compliance.compliance_history import project_schema_columns
from panorama_compliance.validation import sample_key_values, subset_difference


def derive_daily_diff_frame(
    *,
    previous_active: pl.DataFrame,
    current_active: pl.DataFrame,
    run_date: str,
    previous_date: str,
    slice_token: str,
    schema_root: Path,
) -> pl.DataFrame:
    current_ids = current_active.select("client_id").unique()
    became_compliant = previous_active.join(current_ids, on="client_id", how="anti")
    current_only = subset_difference(
        current_active,
        previous_active,
        key="client_id",
        subset_label=f"current_active {slice_token}",
        superset_label=f"previous_active {slice_token}",
    )

    if current_only.height:
        sample_ids = sample_key_values(current_only, key="client_id")
        raise RuntimeError(
            "Scoped daily diff failed subset validation "
            f"for slice={slice_token} run_date={run_date} previous_date={previous_date}: "
            f"current_only_rows={current_only.height} sample_client_ids={sample_ids}"
        )

    return project_schema_columns(
        became_compliant,
        schema_root=schema_root,
        dataset_id="processed.panorama.became_compliant",
    )
