from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ispa_daily_workflow.io.readers import (
    read_dataframe_with_schema,
)
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.schema import (
    LoadedSchema,
    ValidationError,
    resolve_dataset_schema,
)
from ispa_daily_workflow.validation import (
    classify_reference_slice,
    ensure_no_duplicate_client_ids,
    normalize_landing_identifier_columns,
    validate_landing_headers,
)

COLUMN_MAPPING = {
    "Client ID": "client_id",
    "Ontario Immunization ID": "ontario_immunization_id",
    "Last Name": "last_name",
    "First Name": "first_name",
    "Middle Name": "middle_name",
    "Date of Birth": "date_of_birth",
    "Age < 16": "is_under_16",
    "Gender": "gender",
    "Grade": "grade",
    "Class": "class",
    "School Board": "school_board",
    "School/ Daycare": "school_name",
    "School/ Daycare ID": "school_id",
    "Phone Number": "primary_phone",
    "Street Address": "street_address",
    "City": "city",
    "Province": "province",
    "Postal Code": "postal_code",
    "Guardian 1 First Name": "guardian_1_first_name",
    "Guardian 1 Last Name": "guardian_1_last_name",
    "Guardian 1 Phone": "guardian_1_phone",
    "Guardian 2 First Name": "guardian_2_first_name",
    "Guardian 2 Last Name": "guardian_2_last_name",
    "Guardian 2 Phone": "guardian_2_phone",
    "Disease(s)/Agent(s)": "reported_diseases_agents",
    "Imms History by Agent": "immunization_history_by_agent",
    "Imms History by Disease": "immunization_history_by_disease",
    "Meningococcal Disease": "meningococcal_disease_status",
}


@dataclass(frozen=True)
class StandardizedFile:
    path: Path
    level: str
    wave: str
    fq_group: str | None = None
    school_id: str | None = None
    cohort: str | None = None


def canonical_panorama_filename(
    *,
    date_token: str,
    classification: StandardizedFile,
    extension: str,
) -> str:
    normalized_extension = extension.lstrip(".").lower()
    if not normalized_extension:
        raise ValueError("Filename extension is required for canonical naming")

    if classification.level == "ELEMENTARY":
        assert classification.fq_group is not None
        token = _fq_group_to_token(classification.fq_group)
        return (
            f"{date_token}_panorama_compliance_elementary_{token}."
            f"{normalized_extension}"
        )

    if classification.level == "SECONDARY":
        assert (
            classification.school_id is not None and classification.cohort is not None
        )
        return (
            f"{date_token}_panorama_compliance_secondary_"
            f"{classification.school_id}_{classification.cohort}.{normalized_extension}"
        )

    raise ValidationError(
        f"Unsupported level for canonical filename: {classification.level}"
    )


def _read_landing_frame(path: Path, landing_schema: LoadedSchema) -> pl.DataFrame:
    return read_dataframe_with_schema(
        path,
        landing_schema,
        file_format="xlsx" if path.suffix.lower() == ".xlsx" else "xls",
        # Read as strings to eliminate parser inference and rely on schema checks/casts.
        as_string=True,
    )


def _rename_columns(df: pl.DataFrame) -> pl.DataFrame:
    rename_map = {
        source: target
        for source, target in COLUMN_MAPPING.items()
        if source in df.columns
    }
    return df.rename(rename_map) if rename_map else df


def _fq_group_to_token(fq_group: str) -> str:
    digits = re.findall(r"\d+", fq_group)
    if digits:
        return f"fq{digits[0]}"
    return re.sub(r"[^a-z0-9]+", "_", fq_group.lower()).strip("_")


def normalize_and_classify_landing_file(
    *,
    file_path: Path,
    landing_schema: LoadedSchema,
    reference: SchoolReference,
    strict_headers: bool = True,
) -> tuple[pl.DataFrame, StandardizedFile]:
    validate_landing_headers(
        file_path,
        landing_schema,
        strict_headers=strict_headers,
    )

    frame = _read_landing_frame(file_path, landing_schema)
    frame = normalize_landing_identifier_columns(frame)
    normalized = _rename_columns(frame)
    ensure_no_duplicate_client_ids(normalized, label=file_path.name)

    slice_classification = classify_reference_slice(
        normalized,
        label=file_path.name,
        reference=reference,
    )
    classification = StandardizedFile(
        path=file_path,
        level=slice_classification.level,
        wave=slice_classification.wave,
        fq_group=slice_classification.fq_group,
        school_id=slice_classification.secondary_school_id,
        cohort=slice_classification.cohort,
    )
    return normalized, classification


def standardize_input_files(
    *,
    input_dir: Path,
    standardized_dir: Path,
    run_date: str,
    reference: SchoolReference,
    schema_root: Path,
    strict_headers: bool = True,
) -> list[StandardizedFile]:
    landing_schema = resolve_dataset_schema(
        "landing.panorama.compliance",
        schema_root=schema_root,
    )
    files = sorted(input_dir.glob("*.xls")) + sorted(input_dir.glob("*.xlsx"))

    if not files:
        logging.info("No input files to standardize in %s", input_dir)
        return []

    standardized_dir.mkdir(parents=True, exist_ok=True)
    source_by_target: dict[str, Path] = {}
    output_by_target: dict[str, StandardizedFile] = {}

    for file_path in files:
        normalized, classification = normalize_and_classify_landing_file(
            file_path=file_path,
            landing_schema=landing_schema,
            reference=reference,
            strict_headers=strict_headers,
        )
        target_name = canonical_panorama_filename(
            date_token=run_date,
            classification=classification,
            extension="xlsx",
        )

        target = standardized_dir / target_name
        existing_source = source_by_target.get(target_name)
        if (
            existing_source is not None
            and existing_source.resolve() != file_path.resolve()
        ):
            logging.warning(
                "Standardized filename collision for %s: overwriting %s with %s",
                target_name,
                existing_source.name,
                file_path.name,
            )

        normalized.write_excel(target)
        source_by_target[target_name] = file_path

        output_by_target[target_name] = StandardizedFile(
            path=target,
            level=classification.level,
            wave=classification.wave,
            fq_group=classification.fq_group,
            school_id=classification.school_id,
            cohort=classification.cohort,
        )

    return sorted(output_by_target.values(), key=lambda entry: entry.path.name)
