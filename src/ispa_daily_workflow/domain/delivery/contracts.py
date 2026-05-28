from __future__ import annotations

from pathlib import Path

import polars as pl

from ispa_daily_workflow.schema import project_to_dataset

DELIVERY_DATASET_BY_OUTPUT_ID = {
    "sharepoint.panorama.diff.xlsx": "delivery.sharepoint.diff",
    "sharepoint.action_queue.xlsx": "delivery.sharepoint.action_queue",
}


def project_delivery_contract(
    frame: pl.DataFrame,
    *,
    output_id: str,
    schema_root: Path,
) -> pl.DataFrame:
    dataset_id = DELIVERY_DATASET_BY_OUTPUT_ID.get(output_id)
    if dataset_id is None:
        raise ValueError(f"No delivery schema is registered for output_id={output_id}")
    return project_to_dataset(frame, dataset_id, schema_root=schema_root)
