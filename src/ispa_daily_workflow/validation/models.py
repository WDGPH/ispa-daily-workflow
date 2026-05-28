from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuleCatalogEntry:
    rule_id: str
    summary: str
    default_severity: str
    intent: str
    outcome: str
    application_points: tuple[str, ...]
    category_code: str | None = None
    category_name: str | None = None
    operator_evidence: str = "CLI validation summary and run artifacts; warning details artifact when emitted."


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    code: str
    severity: str
    message: str
    count: int = 0
    context: dict[str, Any] = field(default_factory=dict)
