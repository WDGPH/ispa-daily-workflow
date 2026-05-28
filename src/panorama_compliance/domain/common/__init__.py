"""Common domain primitives shared across sources."""

from panorama_compliance.validation.scope import (
    ScopeSelection,
    parse_scope_selection,
)
from panorama_compliance.domain.common.source_policy import (
    PANORAMA_ONLY_OUTPUT_IDS,
    PEAR_ONLY_OUTPUT_IDS,
    PDF_OUTPUT_IDS,
    SOURCE_CHOICES,
    validate_output_source,
)
from panorama_compliance.domain.common.workdays import WorkdayInfo

__all__ = [
    "ScopeSelection",
    "parse_scope_selection",
    "WorkdayInfo",
    "SOURCE_CHOICES",
    "PDF_OUTPUT_IDS",
    "PANORAMA_ONLY_OUTPUT_IDS",
    "PEAR_ONLY_OUTPUT_IDS",
    "validate_output_source",
]
