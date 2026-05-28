from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable

from panorama_compliance.validation.models import RuleResult


PASS_STATUS = "PASS"
WARN_STATUS = "WARN"
FAIL_STATUS = "FAIL"
NONE_STATUS = "NONE"


def validation_line(*, status: str, rule_id: str, message: str) -> str:
    return f"VALIDATION {status} [{rule_id}] {message}"


def _strip_validation_prefix(message: str) -> str:
    return re.sub(
        r"^VALIDATION\s+(?:PASS|WARN|FAIL)\s+\[[^\]]+\]\s*",
        "",
        str(message).strip(),
    )


@dataclass
class RuleTelemetry:
    status: str = NONE_STATUS
    applied: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    last_message: str = ""

    def as_dict(self) -> dict[str, int | str]:
        return {
            "status": self.status,
            "applied": self.applied,
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
            "last_message": self.last_message,
        }


@dataclass
class ValidationSummary:
    tracked_rule_ids: tuple[str, ...] = ()
    applied: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    rules: dict[str, RuleTelemetry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tracked_rule_ids = tuple(dict.fromkeys(self.tracked_rule_ids))
        for rule_id in self.tracked_rule_ids:
            self.rules.setdefault(rule_id, RuleTelemetry())

    @property
    def status(self) -> str:
        if self.failed > 0:
            return FAIL_STATUS
        if self.warned > 0:
            return WARN_STATUS
        if self.applied > 0:
            return PASS_STATUS
        return NONE_STATUS

    def _get_rule(self, rule_id: str) -> RuleTelemetry:
        rule = self.rules.get(rule_id)
        if rule is None:
            rule = RuleTelemetry()
            self.rules[rule_id] = rule
        return rule

    @staticmethod
    def _refresh_rule_status(rule: RuleTelemetry) -> None:
        if rule.failed > 0:
            rule.status = FAIL_STATUS
        elif rule.warned > 0:
            rule.status = WARN_STATUS
        elif rule.passed > 0:
            rule.status = PASS_STATUS
        else:
            rule.status = NONE_STATUS

    def rule_status_counts(self) -> dict[str, int]:
        counts = {
            PASS_STATUS: 0,
            WARN_STATUS: 0,
            FAIL_STATUS: 0,
            NONE_STATUS: 0,
        }
        tracked = (
            self.tracked_rule_ids if self.tracked_rule_ids else tuple(self.rules.keys())
        )
        for rule_id in tracked:
            status = self.rules.get(rule_id, RuleTelemetry()).status
            counts[status] = counts.get(status, 0) + 1
        return counts

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "applied": self.applied,
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
            "rule_status_counts": self.rule_status_counts(),
            "rules": {
                rule_id: telemetry.as_dict()
                for rule_id, telemetry in sorted(self.rules.items())
            },
        }

    def record_pass(
        self,
        *,
        rule_id: str,
        message: str,
        log: Callable[[str], None] | None = None,
    ) -> None:
        clean = _strip_validation_prefix(message)
        self.applied += 1
        self.passed += 1
        rule = self._get_rule(rule_id)
        rule.applied += 1
        rule.passed += 1
        rule.last_message = clean
        self._refresh_rule_status(rule)
        if log is not None:
            log(validation_line(status=PASS_STATUS, rule_id=rule_id, message=clean))

    def record_pass_count(
        self,
        *,
        rule_id: str,
        count: int,
        message: str,
        log: Callable[[str], None] | None = None,
    ) -> None:
        if count <= 0:
            return
        clean = _strip_validation_prefix(message)
        self.applied += count
        self.passed += count
        rule = self._get_rule(rule_id)
        rule.applied += count
        rule.passed += count
        rule.last_message = clean
        self._refresh_rule_status(rule)
        if log is not None:
            log(validation_line(status=PASS_STATUS, rule_id=rule_id, message=clean))

    def record_warning(
        self,
        result: RuleResult,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        clean = _strip_validation_prefix(result.message)
        self.applied += 1
        self.warned += 1
        rule = self._get_rule(result.rule_id)
        rule.applied += 1
        rule.warned += 1
        rule.last_message = clean
        self._refresh_rule_status(rule)
        if log is not None:
            log(
                validation_line(
                    status=WARN_STATUS,
                    rule_id=result.rule_id,
                    message=clean,
                )
            )

    def record_failure(
        self,
        *,
        rule_id: str,
        message: str,
        log: Callable[[str], None] | None = None,
    ) -> None:
        clean = _strip_validation_prefix(message)
        self.applied += 1
        self.failed += 1
        rule = self._get_rule(rule_id)
        rule.applied += 1
        rule.failed += 1
        rule.last_message = clean
        self._refresh_rule_status(rule)
        if log is not None:
            log(validation_line(status=FAIL_STATUS, rule_id=rule_id, message=clean))
