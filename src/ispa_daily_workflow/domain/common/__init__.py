"""Common domain primitives shared across sources."""

from ispa_daily_workflow.domain.common.source_policy import (
    PANORAMA_ONLY_OUTPUT_IDS,
    PDF_OUTPUT_IDS,
    PEAR_ONLY_OUTPUT_IDS,
    SOURCE_CHOICES,
    validate_output_source,
)
from ispa_daily_workflow.domain.common.workdays import WorkdayInfo
from ispa_daily_workflow.validation.scope import (
    ScopeSelection,
    parse_scope_selection,
)

__all__ = [
    "PANORAMA_ONLY_OUTPUT_IDS",
    "PDF_OUTPUT_IDS",
    "PEAR_ONLY_OUTPUT_IDS",
    "SOURCE_CHOICES",
    "ScopeSelection",
    "WorkdayInfo",
    "parse_scope_selection",
    "validate_output_source",
]
