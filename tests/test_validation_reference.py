from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.reference import SchoolRecord, SchoolReference  # noqa: E402
from panorama_compliance.schema import ValidationError  # noqa: E402
from panorama_compliance.validation.reference import (  # noqa: E402
    classify_reference_slice,
    determine_secondary_birth_cohort,
)


def _reference() -> SchoolReference:
    record_elem = SchoolRecord(
        school_name="ALPHA SCHOOL",
        school_id="1001",
        level="ELEMENTARY",
        wave="ELEMENTARY1",
        fq_group="GROUP_A",
    )
    record_sec = SchoolRecord(
        school_name="BETA SCHOOL",
        school_id="2001",
        level="SECONDARY",
        wave="SECONDARY1",
        fq_group="GROUP_B",
    )
    return SchoolReference(
        by_id={"1001": record_elem, "2001": record_sec},
        by_name={
            "ALPHA SCHOOL": record_elem,
            "BETA SCHOOL": record_sec,
        },
        secondary_labels={"BETA SCHOOL - 2001"},
    )


class TestValidationReference(unittest.TestCase):
    def test_determine_secondary_birth_cohort(self) -> None:
        cohort = determine_secondary_birth_cohort(
            pl.DataFrame({"date_of_birth": ["2012-01-01", "2014-01-01"]}),
            label="secondary_file.xlsx",
        )
        self.assertEqual(cohort, "2010_and_later")

    def test_classify_reference_slice_elementary(self) -> None:
        classification = classify_reference_slice(
            pl.DataFrame({"school_name": ["ALPHA SCHOOL"], "school_id": ["1001"]}),
            label="elementary_file.xlsx",
            reference=_reference(),
        )
        self.assertEqual(classification.level, "ELEMENTARY")
        self.assertEqual(classification.wave, "ELEMENTARY1")
        self.assertEqual(classification.fq_group, "GROUP_A")

    def test_classify_reference_slice_secondary(self) -> None:
        classification = classify_reference_slice(
            pl.DataFrame(
                {
                    "school_name": ["BETA SCHOOL"],
                    "school_id": ["2001"],
                    "date_of_birth": ["2011-01-01"],
                }
            ),
            label="secondary_file.xlsx",
            reference=_reference(),
        )
        self.assertEqual(classification.level, "SECONDARY")
        self.assertEqual(classification.wave, "SECONDARY1")
        self.assertEqual(classification.secondary_school_id, "2001")
        self.assertEqual(classification.cohort, "2010_and_later")

    def test_unknown_school_raises(self) -> None:
        with self.assertRaisesRegex(ValidationError, "school not in reference"):
            classify_reference_slice(
                pl.DataFrame({"school_name": ["UNKNOWN"], "school_id": ["9999"]}),
                label="unknown.xlsx",
                reference=_reference(),
            )


if __name__ == "__main__":
    unittest.main()
