from __future__ import annotations

from ispa_daily_workflow.validation.models import RuleCatalogEntry

CATEGORY_NAMES: dict[str, str] = {
    "01": "ingest_contracts",
    "02": "identity_reference",
    "03": "temporal_history",
    "04": "delivery_scope_contracts",
    "05": "io_runtime_safety",
    "06": "quality_evidence",
}


CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "01": "Ingest Contracts And Intake Controls",
    "02": "Identity And School-Reference Integrity",
    "03": "Temporal And History Continuity",
    "04": "Delivery Scope And Contract Enforcement",
    "05": "IO And Runtime Safety Controls",
    "06": "Quality Evidence And Artifact Hygiene",
}


CATEGORY_INTENT_CONTEXT: dict[str, str] = {
    "01": "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged.",
    "02": "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools.",
    "03": "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates.",
    "04": "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive.",
    "05": "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs.",
    "06": "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts.",
}


RULE_PARSE_DIAGNOSTICS_ID = "ISPA-01-004"
RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID = "ISPA-01-010"
RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID = "ISPA-02-009"
RULE_PREVIOUS_SCOPE_DATA_ID = "ISPA-03-008"
RULE_DELIVERY_CONTRACT_ID = "ISPA-04-002"
RULE_DATE_RANGE_ID = "ISPA-03-001"
RULE_PREVIOUS_BUSINESS_DAY_ID = "ISPA-03-002"
RULE_ARTIFACT_HYGIENE_ID = "ISPA-06-005"
RULE_TEMPORAL_BOUNDS_ID = "ISPA-03-004"
RULE_PARSE_COUNTERS_ID = "ISPA-06-007"
RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID = "ISPA-03-009"
RULE_PEAR_RESCIND_WINDOW_START_ID = "ISPA-03-010"
RULE_PEAR_SUSPENSION_CONTINUITY_ID = "ISPA-03-011"
RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID = "ISPA-03-012"
RULE_PEAR_DELETE_ACTION_MATCH_ID = "ISPA-03-013"


_RULE_SPECS: list[tuple[str, str, str, str]] = [
    ("ISPA-01-001", "01", "Exact landing headers enforced.", "error"),
    ("ISPA-01-002", "01", "Normalized rows match processed contract.", "error"),
    ("ISPA-01-003", "01", "Required fields must be present/non-null.", "error"),
    ("ISPA-01-004", "01", "Date/type parse diagnostics are explicit.", "warning"),
    ("ISPA-01-005", "01", "Canonical filename collisions are auditable.", "warning"),
    ("ISPA-01-006", "01", "Landing filename canonicalization is strict.", "error"),
    ("ISPA-01-007", "01", "SharePoint extract window/suffix checks.", "error"),
    ("ISPA-01-008", "01", "Canonical target collisions hard-fail.", "error"),
    ("ISPA-01-009", "01", "Internal streams remain parquet-only.", "error"),
    (
        "ISPA-01-010",
        "01",
        "PEAR suspension canonical suffix is school-reference authoritative; title fallback warns.",
        "warning",
    ),
    ("ISPA-02-001", "02", "client_id normalization continuity.", "error"),
    ("ISPA-02-002", "02", "Duplicate student keys blocked pre-merge.", "error"),
    ("ISPA-02-003", "02", "Duplicate keys blocked in history/diff.", "error"),
    ("ISPA-02-004", "02", "Diff current_only subset protections.", "error"),
    ("ISPA-02-005", "02", "Unknown schools blocked against reference.", "error"),
    ("ISPA-02-006", "02", "Single coherent cohort per source file.", "error"),
    ("ISPA-02-007", "02", "Secondary cohort split consistency.", "error"),
    (
        "ISPA-02-008",
        "02",
        "New client_id additions require explicit override.",
        "error",
    ),
    (
        "ISPA-02-009",
        "02",
        "PEAR wave windows must come from school_reference metadata (no fallback defaults).",
        "error",
    ),
    ("ISPA-03-001", "03", "Date-range ordering and business-day integrity.", "error"),
    ("ISPA-03-002", "03", "Previous-business-day prerequisite policy.", "error"),
    ("ISPA-03-003", "03", "Typst compile failures fail fast.", "error"),
    ("ISPA-03-004", "03", "Temporal bounds (DOB/compliant windows).", "error"),
    (
        "ISPA-03-005",
        "03",
        "Integrated diff degrades to warning when prerequisite absent.",
        "warning",
    ),
    (
        "ISPA-03-006",
        "03",
        "No-prior-history hard-fail on non-initial business day.",
        "error",
    ),
    ("ISPA-03-007", "03", "No-change snapshot suppression.", "warning"),
    (
        "ISPA-03-008",
        "03",
        "Prior-day source-file coverage uncertainty warning.",
        "warning",
    ),
    (
        "ISPA-03-009",
        "03",
        "PEAR overdue day-over-day continuity and new-client warning.",
        "warning",
    ),
    (
        "ISPA-03-010",
        "03",
        "PEAR suspension rescind_date must be on/after wave suspension_window_start.",
        "error",
    ),
    (
        "ISPA-03-011",
        "03",
        "PEAR suspension continuity is enforced business-day by wave/level.",
        "error",
    ),
    (
        "ISPA-03-012",
        "03",
        "PEAR suspension disappearances are restored with explicit evidence warnings.",
        "warning",
    ),
    (
        "ISPA-03-013",
        "03",
        "Delete action rows matching current suspension rows emit investigation warnings.",
        "warning",
    ),
    ("ISPA-04-001", "04", "Processed-stream schema projection controls.", "error"),
    ("ISPA-04-002", "04", "Delivery-surface schema contracts.", "error"),
    ("ISPA-04-003", "04", "Robocall field contract controls.", "error"),
    ("ISPA-04-004", "04", "Exactly one delivery scope required.", "error"),
    ("ISPA-04-005", "04", "Zero-row scoped deliveries hard-fail.", "error"),
    ("ISPA-04-006", "04", "Locked output identifiers only.", "error"),
    (
        "ISPA-04-007",
        "04",
        "No-upload inspect isolation and retention cleanup strictness.",
        "warning",
    ),
    ("ISPA-04-008", "04", "SharePoint PDF cleanup guardrails.", "error"),
    ("ISPA-05-001", "05", "Inactive root-scoped discovery control.", "warning"),
    ("ISPA-05-002", "05", "Strict/typed Graph API error handling.", "error"),
    ("ISPA-05-003", "05", "Runtime config/file strictness.", "error"),
    ("ISPA-05-004", "05", "SharePoint path sanitization.", "error"),
    ("ISPA-05-005", "05", "ADLS prefix strictness/resilience.", "warning"),
    ("ISPA-05-006", "05", "Publish/derive dependency checks.", "error"),
    ("ISPA-06-001", "06", "File manifest evidence coverage.", "warning"),
    ("ISPA-06-002", "06", "Exact-duplicate input evidence checks.", "warning"),
    ("ISPA-06-003", "06", "Missing-input alerting controls.", "warning"),
    ("ISPA-06-004", "06", "Per-school delta warning controls.", "warning"),
    ("ISPA-06-005", "06", "Sensitive artifact retention minimization.", "warning"),
    ("ISPA-06-006", "06", "Long numeric ID log redaction option.", "warning"),
    ("ISPA-06-007", "06", "Parse-failure counter evidence.", "warning"),
    ("ISPA-06-008", "06", "Per-slice expected-input profiling.", "warning"),
    ("ISPA-06-009", "06", "Unified run artifact evidence envelope.", "warning"),
]


_RULE_DETAILS: dict[str, tuple[str, str]] = {
    "ISPA-01-001": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Enforces exact landing header contracts so upstream export drift cannot silently alter legal population logic.",
        "Hard fail on header mismatch.",
    ),
    "ISPA-01-002": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Confirms normalized records still satisfy the processed schema contract before merge.",
        "Hard fail on contract violation.",
    ),
    "ISPA-01-003": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Ensures required fields are present and non-null before counts or reports are derived.",
        "Hard fail on missing required values.",
    ),
    "ISPA-01-004": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Makes parse quality observable through explicit parse-failure telemetry.",
        "Warning telemetry; execution continues unless paired with a blocking control.",
    ),
    "ISPA-01-005": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Detects canonical filename collisions so overwrite behavior is auditable.",
        "Warning with explicit collision context.",
    ),
    "ISPA-01-006": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Restricts landing intake to canonical filename patterns.",
        "Hard fail or strict skip based on pattern checks.",
    ),
    "ISPA-01-007": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Limits SharePoint extraction to same-day Toronto-window Panorama file candidates.",
        "Hard fail for invalid candidate sets or mismatch constraints.",
    ),
    "ISPA-01-008": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Prevents ambiguous source-to-target mapping when two files resolve to one canonical target name.",
        "Hard fail on deterministic collision.",
    ),
    "ISPA-01-009": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Keeps internal pipeline streams parquet-only to avoid mixed-format drift.",
        "Hard fail or strict enforcement of parquet-only outputs.",
    ),
    "ISPA-01-010": (
        "In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged. Enforces PEAR suspension canonical suffix authority from school-reference level distribution.",
        "Warning telemetry for fallback or ambiguous suffix resolution.",
    ),
    "ISPA-02-001": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Standardizes client_id representation so identity continuity is preserved across commands.",
        "Hard fail if the key column is unavailable or unusable.",
    ),
    "ISPA-02-002": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Blocks duplicate student identifiers before merge.",
        "Hard fail on duplicate IDs.",
    ),
    "ISPA-02-003": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Blocks duplicate key states in history and diff computations.",
        "Hard fail on duplicate keys.",
    ),
    "ISPA-02-004": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Enforces subset logic on day-over-day transitions to block impossible transition publication.",
        "Hard fail when subset invariants are violated.",
    ),
    "ISPA-02-005": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Rejects schools not present in the active reference governance file.",
        "Hard fail on unknown school mapping.",
    ),
    "ISPA-02-006": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Requires a coherent single cohort slice per source file.",
        "Hard fail on mixed or ambiguous cohort classification.",
    ),
    "ISPA-02-007": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Enforces secondary cohort split integrity for suspension-wave behavior.",
        "Hard fail on incoherent cohort composition.",
    ),
    "ISPA-02-008": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Prevents accidental new client_id introduction in compliance_history outside controlled bootstrap or override scenarios.",
        "Hard fail by default; warning context when an override is intentionally enabled.",
    ),
    "ISPA-02-009": (
        "In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools. Requires PEAR suspension and action derivations to use wave windows from active school_reference metadata.",
        "Hard fail on missing wave-window metadata.",
    ),
    "ISPA-03-001": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Enforces date-token parsing and ordered date ranges.",
        "Hard fail on malformed or non-increasing date ranges.",
    ),
    "ISPA-03-002": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Requires a resolvable previous business day for suspension and diff prerequisites.",
        "Hard fail when previous business day is required but unavailable.",
    ),
    "ISPA-03-003": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Prevents silently partial PDF publication by treating Typst compilation failure as blocking.",
        "Hard fail on compile failure.",
    ),
    "ISPA-03-004": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Validates DOB and compliance temporal bounds with explicit reason codes.",
        "Hard fail for impossible windows; warning for out-of-policy age-band checks.",
    ),
    "ISPA-03-005": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Allows integrated run mode to proceed when diff-only prerequisites are missing while surfacing degradation.",
        "Warning when prerequisite is unavailable; no hard block for non-diff outputs.",
    ),
    "ISPA-03-006": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Prevents accidental history reset when no prior compliance_history snapshot exists.",
        "Hard fail unless explicit bootstrap override is provided.",
    ),
    "ISPA-03-007": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Avoids unnecessary snapshot churn by suppressing no-change snapshot emissions.",
        "Warning or informational deterministic suppression behavior.",
    ),
    "ISPA-03-008": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Flags uncertainty in prior-day source-file coverage for scoped diff or suspension interpretation.",
        "Warning only; never a standalone delivery blocker when current-run history exists.",
    ),
    "ISPA-03-009": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Detects PEAR overdue day-over-day continuity uncertainty and introduced run-date overdue clients.",
        "Warning only; missing prior PEAR overdue or introduced IDs do not hard-fail state derivation.",
    ),
    "ISPA-03-010": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Prevents pre-start PEAR suspension rescinds.",
        "Hard fail on out-of-window rescind dates or missing wave-window metadata for rescinded rows.",
    ),
    "ISPA-03-011": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Enforces PEAR suspension continuity business-day by business-day by wave and level.",
        "Hard fail on missing required current/prior inputs; warning for pre-suspension initial-list timing.",
    ),
    "ISPA-03-012": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Makes suspension disappearance rehydration explicit with per-client restoration evidence.",
        "Warning telemetry when rehydration occurs; execution continues with restored rows.",
    ),
    "ISPA-03-013": (
        "In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates. Surfaces delete-action matches against current suspension rows for investigation.",
        "Warning telemetry; no destructive row deletion from suspension state.",
    ),
    "ISPA-04-001": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Ensures processed-stream projections expose only intended fields before derived outputs are built.",
        "Hard fail on schema projection contract break.",
    ),
    "ISPA-04-002": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Enforces explicit delivery-surface contracts for each approved output ID.",
        "Hard fail on required-column delivery contract violations.",
    ),
    "ISPA-04-003": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Enforces the approved robocall field contract when robocall-oriented delivery surfaces are produced.",
        "Hard fail on robocall field contract violations.",
    ),
    "ISPA-04-004": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Requires exactly one scope selector to prevent ambiguous cohort targeting.",
        "Hard fail on missing or mixed scope arguments.",
    ),
    "ISPA-04-005": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Blocks zero-row scoped delivery actions for tabular outputs while allowing explicit zero-row final-summary PDFs.",
        "Hard fail on empty scoped tabular delivery set.",
    ),
    "ISPA-04-006": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Restricts deliveries to locked output IDs.",
        "Hard fail on unsupported output IDs.",
    ),
    "ISPA-04-007": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Guarantees no-upload inspect directories are isolated and stale inspection/cache artifacts are bounded.",
        "Warning or informational enforcement with deterministic cleanup.",
    ),
    "ISPA-04-008": (
        "In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive. Constrains SharePoint cleanup to safe report/output combinations and dry-run inspectability.",
        "Hard fail on invalid cleanup mode or final-summary lock conflict; warning logs for cleanup outcomes.",
    ),
    "ISPA-05-001": (
        "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs. Retains historical root-scoped discovery control as governance context only.",
        "Retired; not actively enforced.",
    ),
    "ISPA-05-002": (
        "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs. Enforces strict typed Graph API error handling for SharePoint operations.",
        "Hard fail on Graph API operation errors.",
    ),
    "ISPA-05-003": (
        "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs. Requires explicit runtime config and required file paths.",
        "Hard fail on missing or invalid required config.",
    ),
    "ISPA-05-004": (
        "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs. Sanitizes SharePoint remote paths and file leaf names.",
        "Hard fail on invalid remote path shapes.",
    ),
    "ISPA-05-005": (
        "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs. Applies ADLS prefix strictness with controlled resilience.",
        "Warning or hard fail depending on operation and prefix mode.",
    ),
    "ISPA-05-006": (
        "In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs. Prevents incoherent run plans by validating dependency relationships between derive and publish options.",
        "Hard fail on invalid plan combinations.",
    ),
    "ISPA-06-001": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Captures input manifest evidence for each run.",
        "Warning or evidence control recorded in artifact payload.",
    ),
    "ISPA-06-002": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Detects exact duplicate input files for provenance quality investigations.",
        "Warning or evidence control.",
    ),
    "ISPA-06-003": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Raises missing-input alerts for incomplete expected intake conditions.",
        "Warning alert control.",
    ),
    "ISPA-06-004": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Produces per-school delta warnings for abnormal distribution shifts.",
        "Warning alert control.",
    ),
    "ISPA-06-005": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Minimizes retention of report-source artifacts to reduce exposure of sensitive derived content.",
        "Warning-governed hygiene control with opt-in retention behavior.",
    ),
    "ISPA-06-006": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Supports optional long numeric ID redaction in logs.",
        "Warning-governed hygiene control; configurable behavior.",
    ),
    "ISPA-06-007": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Aggregates field-level parse failure counters for quality diagnostics.",
        "Warning-only quality signal.",
    ),
    "ISPA-06-008": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Retains per-slice expected-input profiling as low-priority governance context.",
        "Recommended retire; not core active enforcement.",
    ),
    "ISPA-06-009": (
        "In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts. Maintains a unified run artifact as the evidence envelope for stage outcomes, alerts, and validation telemetry.",
        "Required evidence output for each run.",
    ),
}


def _trace_lookup_hint(rule_id: str) -> str:
    return (
        f"Search the codebase for `{rule_id}` to find the current implementation path."
    )


RULE_CATALOG: dict[str, RuleCatalogEntry] = {
    rule_id: RuleCatalogEntry(
        rule_id=rule_id,
        category_code=category_code,
        category_name=CATEGORY_NAMES[category_code],
        summary=summary,
        default_severity=default_severity,
        intent=_RULE_DETAILS[rule_id][0],
        outcome=_RULE_DETAILS[rule_id][1],
        application_points=(_trace_lookup_hint(rule_id),),
    )
    for rule_id, category_code, summary, default_severity in _RULE_SPECS
}


def all_rule_ids() -> tuple[str, ...]:
    return tuple(RULE_CATALOG.keys())


def rules_by_category() -> dict[str, tuple[RuleCatalogEntry, ...]]:
    grouped: dict[str, list[RuleCatalogEntry]] = {
        category_code: [] for category_code in CATEGORY_NAMES
    }
    for rule in RULE_CATALOG.values():
        if rule.category_code is None:
            continue
        grouped.setdefault(rule.category_code, []).append(rule)
    return {
        category_code: tuple(rules) for category_code, rules in grouped.items() if rules
    }


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _operator_intent(rule: RuleCatalogEntry) -> str:
    intent = rule.intent.strip()
    category_code = rule.category_code or ""
    context = CATEGORY_INTENT_CONTEXT.get(category_code, "").strip()
    if context and intent.startswith(f"{context} "):
        return intent[len(context) + 1 :]
    return intent


def rule_catalog_markdown() -> str:
    lines = [
        "# Validation Rules",
        "",
        "This file is generated from `src/ispa_daily_workflow/validation/catalog.py`.",
        "Update the catalog first, then regenerate this file.",
        "",
        (
            "Use this index when CLI output or run artifacts show a validation line such as "
            "`VALIDATION WARN [ISPA-03-008] ...`."
        ),
        "",
    ]
    grouped = rules_by_category()
    for category_code, rules in grouped.items():
        category_name = CATEGORY_DISPLAY_NAMES[category_code]
        lines.extend(
            [
                f"## Category {category_code}: {category_name}",
                "",
                f"Workflow context: {CATEGORY_INTENT_CONTEXT[category_code]}",
                "",
                "| Rule | Severity | Intent | Outcome | Evidence |",
                "|---|---|---|---|---|",
            ]
        )
        for rule in rules:
            lines.append(
                "| "
                f"`{rule.rule_id}` | "
                f"{_markdown_cell(rule.default_severity)} | "
                f"{_markdown_cell(_operator_intent(rule))} | "
                f"{_markdown_cell(rule.outcome)} | "
                f"{_markdown_cell(rule.operator_evidence)} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
