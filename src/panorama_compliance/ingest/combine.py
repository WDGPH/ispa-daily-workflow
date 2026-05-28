from __future__ import annotations

import logging
import re
from pathlib import Path

import polars as pl

from panorama_compliance.ingest.standardize import StandardizedFile
from panorama_compliance.io.readers import read_dataframe_with_schema
from panorama_compliance.normalize import normalize_compliance_dataframe
from panorama_compliance.reference import SchoolReference
from panorama_compliance.schema import (
    LoadedSchema,
    ValidationError,
    resolve_dataset_schema,
    required_fields,
    schema_field_names,
    validate_exact_headers,
    validate_required_non_null,
)
from panorama_compliance.validation.evidence import (
    ParseFailureCounter,
    collect_date_parse_counters,
)
from panorama_compliance.validation.frames import filter_by_school_ids
from panorama_compliance.validation.identity import ensure_unique_identifier


def wave_to_token(wave_key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", wave_key.lower()).strip("_")


def _apply_school_filter(df: pl.DataFrame, school_ids: set[str]) -> pl.DataFrame:
    return filter_by_school_ids(df, school_ids=school_ids, school_id_column="school_id")


def _read_standardized(path: Path, processed_schema: LoadedSchema) -> pl.DataFrame:
    return read_dataframe_with_schema(
        path,
        processed_schema,
        file_format="xlsx",
        # Standardized files are read with explicit schema overrides to avoid inference.
        as_string=True,
    )


def combine_standardized_files(
    *,
    entries: list[StandardizedFile],
    run_date: str,
    output_dir: Path,
    schema_root: Path,
    reference: SchoolReference,
    school_ids: set[str] | None = None,
    levels: set[str] | None = None,
    waves: set[str] | None = None,
    formats: tuple[str, ...] = ("parquet",),
    parse_counters_sink: list[ParseFailureCounter] | None = None,
) -> dict[str, list[Path]]:
    processed_schema = resolve_dataset_schema(
        "processed.panorama.compliance",
        schema_root=schema_root,
    )
    noncompliant_schema = resolve_dataset_schema(
        "processed.panorama.noncompliant",
        schema_root=schema_root,
    )

    school_ids = school_ids or set()
    levels = levels or set()
    waves = waves or set()

    selected = entries
    if levels:
        selected = [entry for entry in selected if entry.level in levels]
    if waves:
        selected = [entry for entry in selected if entry.wave in waves]

    if not selected:
        logging.info("No standardized files matched filters")
        return {}

    frames: list[pl.DataFrame] = []
    for entry in selected:
        df = _read_standardized(entry.path, processed_schema)
        if parse_counters_sink is not None:
            parse_counters_sink.extend(
                collect_date_parse_counters(
                    df,
                    stream=entry.path.name,
                    fields=("date_of_birth", "compliant"),
                )
            )
        validate_exact_headers(df.columns, processed_schema, entry.path.name)
        normalized = normalize_compliance_dataframe(
            df,
            reference=reference,
            source_file=entry.path.name,
            wave=entry.wave,
        )
        validate_required_non_null(normalized, processed_schema, entry.path.name)
        ensure_unique_identifier(normalized, key="client_id", label=entry.path.name)
        frames.append(normalized)

    combined_df = pl.concat(frames, how="vertical")
    combined_df = _apply_school_filter(combined_df, school_ids)
    if combined_df.is_empty():
        logging.info("No rows remain after filters")
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    expected_columns = list(schema_field_names(noncompliant_schema))
    required = set(required_fields(noncompliant_schema))

    written: dict[str, list[Path]] = {}
    for wave_key, wave_df in combined_df.partition_by("wave", as_dict=True).items():
        if wave_key is None or str(wave_key).strip() == "":
            raise ValidationError("Missing wave value in combined output")
        wave_token = wave_to_token(str(wave_key))

        missing_required = [col for col in required if col not in wave_df.columns]
        if missing_required:
            raise ValidationError(
                f"Combined output missing required columns for {wave_token}: {missing_required}"
            )

        for column in expected_columns:
            if column not in wave_df.columns:
                wave_df = wave_df.with_columns(pl.lit(None).alias(column))

        minimized = wave_df.select(expected_columns)
        ensure_unique_identifier(
            minimized,
            key="client_id",
            label=f"combined output {wave_token}",
        )

        outputs: list[Path] = []
        base = output_dir / f"{run_date}_panorama_{wave_token}_noncompliant"
        if "parquet" in formats:
            parquet_path = base.with_suffix(".parquet")
            minimized.write_parquet(parquet_path)
            outputs.append(parquet_path)
        if "xlsx" in formats:
            xlsx_path = base.with_suffix(".xlsx")
            minimized.write_excel(xlsx_path)
            outputs.append(xlsx_path)

        written[str(wave_key)] = outputs

    return written
