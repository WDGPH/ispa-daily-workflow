from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from panorama_compliance.validation import (
    RULE_PEAR_DELETE_ACTION_MATCH_ID,
    RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
    RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
    RULE_PEAR_RESCIND_WINDOW_START_ID,
    RULE_PEAR_SUSPENSION_CONTINUITY_ID,
    RuleResult,
    ValidationSummary,
    continuity_warning_results,
    delete_action_match_warning,
    disappearance_warning_results,
)


@dataclass(frozen=True)
class PearStateValidationCounts:
    delete_match_ids: list[str]
    continuity_warning_count: int
    overdue_warning_count: int
    disappearance_warning_count: int


def record_pear_state_validation(
    *,
    result: Any,
    validation_summary: ValidationSummary,
    pass_log: Callable[[str], None] | None,
    warning_log: Callable[[str], None] | None,
) -> PearStateValidationCounts:
    matched_delete_client_ids = result.rescind_patch_summary.get(
        "matched_delete_client_ids", []
    )
    delete_match_ids = (
        [str(value) for value in matched_delete_client_ids]
        if isinstance(matched_delete_client_ids, list)
        else []
    )

    validation_summary.record_pass(
        rule_id=RULE_PEAR_RESCIND_WINDOW_START_ID,
        message=(
            "PEAR suspension rescind_date values validated against wave "
            "suspension_window_start bounds"
        ),
        log=pass_log,
    )
    continuity_results = continuity_warning_results(result.continuity_warning_messages)
    if continuity_results:
        for warning in continuity_results:
            validation_summary.record_warning(warning, log=warning_log)
    else:
        validation_summary.record_pass(
            rule_id=RULE_PEAR_SUSPENSION_CONTINUITY_ID,
            message="PEAR suspension continuity checks passed without warnings",
            log=pass_log,
        )

    overdue_status = str(
        result.overdue_day_over_day_summary.get("status") or ""
    ).lower()
    if overdue_status == "warning":
        for message in result.overdue_day_over_day_warning_messages:
            validation_summary.record_warning(
                RuleResult(
                    rule_id=RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
                    code="pear_overdue_day_over_day_warning",
                    severity="warning",
                    message=message,
                    count=1,
                ),
                log=warning_log,
            )
    else:
        validation_summary.record_pass(
            rule_id=RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
            message=(
                "PEAR overdue day-over-day continuity check completed "
                f"(status={result.overdue_day_over_day_summary.get('status')})"
            ),
            log=pass_log,
        )

    disappearance_results = disappearance_warning_results(
        result.disappearance_warning_messages
    )
    if disappearance_results:
        for warning in disappearance_results:
            validation_summary.record_warning(warning, log=warning_log)
    else:
        validation_summary.record_pass(
            rule_id=RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
            message="No suspension disappearances required rehydration",
            log=pass_log,
        )

    delete_match_warning = delete_action_match_warning(client_ids=delete_match_ids)
    if delete_match_warning is not None:
        validation_summary.record_warning(delete_match_warning, log=warning_log)
    else:
        validation_summary.record_pass(
            rule_id=RULE_PEAR_DELETE_ACTION_MATCH_ID,
            message="No delete action rows matched current suspension rows",
            log=pass_log,
        )

    return PearStateValidationCounts(
        delete_match_ids=delete_match_ids,
        continuity_warning_count=len(result.continuity_warning_messages),
        overdue_warning_count=len(result.overdue_day_over_day_warning_messages),
        disappearance_warning_count=len(result.disappearance_warning_messages),
    )
