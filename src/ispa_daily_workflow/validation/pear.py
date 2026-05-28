from __future__ import annotations

from ispa_daily_workflow.reference import SchoolReference, WaveWindow
from ispa_daily_workflow.schema import ValidationError
from ispa_daily_workflow.validation.catalog import (
    RULE_PEAR_DELETE_ACTION_MATCH_ID,
    RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
    RULE_PEAR_SUSPENSION_CONTINUITY_ID,
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
)
from ispa_daily_workflow.validation.models import RuleResult


def require_wave_window_authority(
    *,
    reference: SchoolReference,
    context: str,
    rule_id: str = RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
) -> dict[str, WaveWindow]:
    windows = dict(reference.wave_windows)
    if windows:
        return windows
    raise ValidationError(
        f"VALIDATION FAIL [{rule_id}] {context} requires school_reference suspension "
        "window metadata (suspension_applied_date, suspension_window_start, "
        "suspension_window_end) for each active wave; fallback defaults are not allowed"
    )


def continuity_warning_results(messages: tuple[str, ...]) -> tuple[RuleResult, ...]:
    return tuple(
        RuleResult(
            rule_id=RULE_PEAR_SUSPENSION_CONTINUITY_ID,
            code="pear_suspension_continuity_warning",
            severity="warning",
            message=message,
            count=1,
        )
        for message in messages
        if str(message).strip()
    )


def disappearance_warning_results(messages: tuple[str, ...]) -> tuple[RuleResult, ...]:
    return tuple(
        RuleResult(
            rule_id=RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
            code="pear_suspension_disappearance_rehydrated",
            severity="warning",
            message=message,
            count=1,
        )
        for message in messages
        if str(message).strip()
    )


def delete_action_match_warning(
    *,
    client_ids: list[str],
) -> RuleResult | None:
    normalized = sorted(
        {str(value).strip() for value in client_ids if str(value).strip()}
    )
    if not normalized:
        return None
    lines = [
        f"    client_id={client_id} action_required=delete" for client_id in normalized
    ]
    message = (
        "Delete action rows matched current suspension rows "
        "(expected mainly for pre-suspension preview/mock periods):\n"
        + "\n".join(lines)
    )
    return RuleResult(
        rule_id=RULE_PEAR_DELETE_ACTION_MATCH_ID,
        code="pear_delete_action_matches_current_suspension",
        severity="warning",
        message=message,
        count=len(normalized),
        context={"client_ids": normalized},
    )
