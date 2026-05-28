from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.validation.catalog import all_rule_ids
from ispa_daily_workflow.validation.models import RuleResult
from ispa_daily_workflow.validation.status import (
    FAIL_STATUS,
    NONE_STATUS,
    PASS_STATUS,
    WARN_STATUS,
    ValidationSummary,
)


class TestValidationStatus(unittest.TestCase):
    def test_summary_starts_with_explicit_none_for_all_rules(self) -> None:
        summary = ValidationSummary(tracked_rule_ids=all_rule_ids())
        counts = summary.rule_status_counts()
        self.assertEqual(summary.status, NONE_STATUS)
        self.assertEqual(counts[PASS_STATUS], 0)
        self.assertEqual(counts[WARN_STATUS], 0)
        self.assertEqual(counts[FAIL_STATUS], 0)
        self.assertEqual(counts[NONE_STATUS], len(all_rule_ids()))

    def test_rule_level_transitions_are_recorded(self) -> None:
        rule_ids = all_rule_ids()
        summary = ValidationSummary(tracked_rule_ids=rule_ids)
        pass_rule = rule_ids[0]
        warn_rule = rule_ids[1]
        fail_rule = rule_ids[2]

        summary.record_pass(rule_id=pass_rule, message="pass")
        summary.record_warning(
            RuleResult(
                rule_id=warn_rule,
                code="warning",
                severity="warning",
                message="warn",
            )
        )
        summary.record_failure(rule_id=fail_rule, message="fail")

        payload = summary.as_dict()
        rules = cast(dict[str, dict[str, object]], payload["rules"])
        self.assertEqual(rules[pass_rule]["status"], PASS_STATUS)
        self.assertEqual(rules[warn_rule]["status"], WARN_STATUS)
        self.assertEqual(rules[fail_rule]["status"], FAIL_STATUS)
        self.assertEqual(payload["status"], FAIL_STATUS)
        self.assertEqual(payload["applied"], 3)
        self.assertEqual(payload["passed"], 1)
        self.assertEqual(payload["warned"], 1)
        self.assertEqual(payload["failed"], 1)


if __name__ == "__main__":
    unittest.main()
