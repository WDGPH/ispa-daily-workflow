from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.validation.catalog import RULE_PARSE_COUNTERS_ID  # noqa: E402
from panorama_compliance.validation.evidence import (  # noqa: E402
    aggregate_parse_counters,
    collect_date_parse_counters,
    parse_counter_alerts,
)


class TestValidationEvidence(unittest.TestCase):
    def test_collect_date_parse_counters(self) -> None:
        frame = pl.DataFrame(
            {
                "date_of_birth": ["2012-05-01", "bad-date", ""],
                "compliant": ["", "2026-01-01", "nope"],
            }
        )
        counters = collect_date_parse_counters(
            frame,
            stream="sample_stream",
            fields=("date_of_birth", "compliant"),
        )
        by_field = {counter.field: counter for counter in counters}
        self.assertEqual(by_field["date_of_birth"].failed_count, 1)
        self.assertEqual(by_field["date_of_birth"].non_empty_count, 2)
        self.assertEqual(by_field["compliant"].failed_count, 1)
        self.assertEqual(by_field["compliant"].non_empty_count, 2)

    def test_aggregate_and_alerts(self) -> None:
        frame_a = pl.DataFrame({"date_of_birth": ["bad", "2010-01-01"]})
        frame_b = pl.DataFrame({"date_of_birth": ["bad", "bad"]})
        counters = []
        counters.extend(
            collect_date_parse_counters(
                frame_a,
                stream="a",
                fields=("date_of_birth",),
            )
        )
        counters.extend(
            collect_date_parse_counters(
                frame_b,
                stream="b",
                fields=("date_of_birth",),
            )
        )
        totals = aggregate_parse_counters(counters)
        self.assertEqual(totals["date_of_birth"]["failed_count"], 3)
        self.assertEqual(totals["date_of_birth"]["non_empty_count"], 4)

        alerts = parse_counter_alerts(counters)
        self.assertEqual(len(alerts), 2)
        self.assertTrue(
            all(alert.rule_id == RULE_PARSE_COUNTERS_ID for alert in alerts)
        )


if __name__ == "__main__":
    unittest.main()
