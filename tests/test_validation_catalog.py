from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.validation.catalog import (
    RULE_ARTIFACT_HYGIENE_ID,
    RULE_CATALOG,
    RULE_DATE_RANGE_ID,
    RULE_DELIVERY_CONTRACT_ID,
    RULE_PARSE_COUNTERS_ID,
    RULE_PARSE_DIAGNOSTICS_ID,
    RULE_PEAR_DELETE_ACTION_MATCH_ID,
    RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
    RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
    RULE_PEAR_RESCIND_WINDOW_START_ID,
    RULE_PEAR_SUSPENSION_CONTINUITY_ID,
    RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID,
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
    RULE_PREVIOUS_BUSINESS_DAY_ID,
    RULE_PREVIOUS_SCOPE_DATA_ID,
    RULE_TEMPORAL_BOUNDS_ID,
    all_rule_ids,
    rule_catalog_markdown,
)

RULE_PATTERN = re.compile(r"^ISPA-\d{2}-\d{3}$")


class TestValidationCatalog(unittest.TestCase):
    def test_all_rules_use_numeric_taxonomy(self) -> None:
        rule_ids = all_rule_ids()
        self.assertEqual(len(rule_ids), 55)
        self.assertEqual(len(set(rule_ids)), len(rule_ids))
        self.assertTrue(all(RULE_PATTERN.match(rule_id) for rule_id in rule_ids))

    def test_all_rules_have_lookup_metadata(self) -> None:
        for rule in RULE_CATALOG.values():
            self.assertTrue(rule.intent.strip(), rule.rule_id)
            self.assertTrue(rule.outcome.strip(), rule.rule_id)
            self.assertTrue(rule.application_points, rule.rule_id)
            self.assertTrue(rule.operator_evidence.strip(), rule.rule_id)

    def test_generated_rule_lookup_is_current(self) -> None:
        generated_path = PROJECT_ROOT / "validation-rules.md"
        self.assertTrue(generated_path.exists())
        self.assertEqual(
            generated_path.read_text(encoding="utf-8"), rule_catalog_markdown()
        )

    def test_active_constants_use_numeric_taxonomy(self) -> None:
        active_rule_ids = {
            RULE_PARSE_DIAGNOSTICS_ID,
            RULE_PREVIOUS_SCOPE_DATA_ID,
            RULE_DELIVERY_CONTRACT_ID,
            RULE_DATE_RANGE_ID,
            RULE_PREVIOUS_BUSINESS_DAY_ID,
            RULE_ARTIFACT_HYGIENE_ID,
            RULE_TEMPORAL_BOUNDS_ID,
            RULE_PARSE_COUNTERS_ID,
            RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
            RULE_PEAR_RESCIND_WINDOW_START_ID,
            RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID,
            RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
            RULE_PEAR_SUSPENSION_CONTINUITY_ID,
            RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
            RULE_PEAR_DELETE_ACTION_MATCH_ID,
        }
        self.assertEqual(len(active_rule_ids), 15)
        self.assertTrue(all(RULE_PATTERN.match(rule_id) for rule_id in active_rule_ids))


if __name__ == "__main__":
    unittest.main()
