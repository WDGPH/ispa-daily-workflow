# Validation Rules

This file is generated from `src/panorama_compliance/validation/catalog.py`.
Update the catalog first, then regenerate this file.

Use this index when CLI output or run artifacts show a validation line such as `VALIDATION WARN [ISPA-03-008] ...`.

## Category 01: Ingest Contracts And Intake Controls

Workflow context: In day-to-day ISPA intake operations, this check protects source-file trust before student records are standardized or merged.

| Rule | Severity | Intent | Outcome | Evidence |
|---|---|---|---|---|
| `ISPA-01-001` | error | Enforces exact landing header contracts so upstream export drift cannot silently alter legal population logic. | Hard fail on header mismatch. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-002` | error | Confirms normalized records still satisfy the processed schema contract before merge. | Hard fail on contract violation. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-003` | error | Ensures required fields are present and non-null before counts or reports are derived. | Hard fail on missing required values. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-004` | warning | Makes parse quality observable through explicit parse-failure telemetry. | Warning telemetry; execution continues unless paired with a blocking control. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-005` | warning | Detects canonical filename collisions so overwrite behavior is auditable. | Warning with explicit collision context. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-006` | error | Restricts landing intake to canonical filename patterns. | Hard fail or strict skip based on pattern checks. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-007` | error | Limits SharePoint extraction to same-day Toronto-window Panorama file candidates. | Hard fail for invalid candidate sets or mismatch constraints. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-008` | error | Prevents ambiguous source-to-target mapping when two files resolve to one canonical target name. | Hard fail on deterministic collision. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-009` | error | Keeps internal pipeline streams parquet-only to avoid mixed-format drift. | Hard fail or strict enforcement of parquet-only outputs. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-01-010` | warning | Enforces PEAR suspension canonical suffix authority from school-reference level distribution. | Warning telemetry for fallback or ambiguous suffix resolution. | CLI validation summary and run artifacts; warning details artifact when emitted. |

## Category 02: Identity And School-Reference Integrity

Workflow context: In day-to-day ISPA operations, this check protects student identity and school mapping so outreach or suspension actions stay tied to the correct students and schools.

| Rule | Severity | Intent | Outcome | Evidence |
|---|---|---|---|---|
| `ISPA-02-001` | error | Standardizes client_id representation so identity continuity is preserved across commands. | Hard fail if the key column is unavailable or unusable. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-002` | error | Blocks duplicate student identifiers before merge. | Hard fail on duplicate IDs. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-003` | error | Blocks duplicate key states in history and diff computations. | Hard fail on duplicate keys. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-004` | error | Enforces subset logic on day-over-day transitions to block impossible transition publication. | Hard fail when subset invariants are violated. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-005` | error | Rejects schools not present in the active reference governance file. | Hard fail on unknown school mapping. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-006` | error | Requires a coherent single cohort slice per source file. | Hard fail on mixed or ambiguous cohort classification. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-007` | error | Enforces secondary cohort split integrity for suspension-wave behavior. | Hard fail on incoherent cohort composition. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-008` | error | Prevents accidental new client_id introduction in compliance_history outside controlled bootstrap or override scenarios. | Hard fail by default; warning context when an override is intentionally enabled. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-02-009` | error | Requires PEAR suspension and action derivations to use wave windows from active school_reference metadata. | Hard fail on missing wave-window metadata. | CLI validation summary and run artifacts; warning details artifact when emitted. |

## Category 03: Temporal And History Continuity

Workflow context: In day-to-day ISPA operations, this check protects business-day timing and continuity so state updates and deliveries remain reliable across dates.

| Rule | Severity | Intent | Outcome | Evidence |
|---|---|---|---|---|
| `ISPA-03-001` | error | Enforces date-token parsing and ordered date ranges. | Hard fail on malformed or non-increasing date ranges. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-002` | error | Requires a resolvable previous business day for suspension and diff prerequisites. | Hard fail when previous business day is required but unavailable. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-003` | error | Prevents silently partial PDF publication by treating Typst compilation failure as blocking. | Hard fail on compile failure. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-004` | error | Validates DOB and compliance temporal bounds with explicit reason codes. | Hard fail for impossible windows; warning for out-of-policy age-band checks. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-005` | warning | Allows integrated run mode to proceed when diff-only prerequisites are missing while surfacing degradation. | Warning when prerequisite is unavailable; no hard block for non-diff outputs. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-006` | error | Prevents accidental history reset when no prior compliance_history snapshot exists. | Hard fail unless explicit bootstrap override is provided. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-007` | warning | Avoids unnecessary snapshot churn by suppressing no-change snapshot emissions. | Warning or informational deterministic suppression behavior. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-008` | warning | Flags uncertainty in prior-day source-file coverage for scoped diff or suspension interpretation. | Warning only; never a standalone delivery blocker when current-run history exists. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-009` | warning | Detects PEAR overdue day-over-day continuity uncertainty and introduced run-date overdue clients. | Warning only; missing prior PEAR overdue or introduced IDs do not hard-fail state derivation. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-010` | error | Prevents pre-start PEAR suspension rescinds. | Hard fail on out-of-window rescind dates or missing wave-window metadata for rescinded rows. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-011` | error | Enforces PEAR suspension continuity business-day by business-day by wave and level. | Hard fail on missing required current/prior inputs; warning for pre-suspension initial-list timing. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-012` | warning | Makes suspension disappearance rehydration explicit with per-client restoration evidence. | Warning telemetry when rehydration occurs; execution continues with restored rows. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-03-013` | warning | Surfaces delete-action matches against current suspension rows for investigation. | Warning telemetry; no destructive row deletion from suspension state. | CLI validation summary and run artifacts; warning details artifact when emitted. |

## Category 04: Delivery Scope And Contract Enforcement

Workflow context: In day-to-day ISPA operations, this check protects delivery scope and output contracts so published lists and reports match what schools are meant to receive.

| Rule | Severity | Intent | Outcome | Evidence |
|---|---|---|---|---|
| `ISPA-04-001` | error | Ensures processed-stream projections expose only intended fields before derived outputs are built. | Hard fail on schema projection contract break. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-002` | error | Enforces explicit delivery-surface contracts for each approved output ID. | Hard fail on required-column delivery contract violations. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-003` | error | Enforces the approved robocall field contract when robocall-oriented delivery surfaces are produced. | Hard fail on robocall field contract violations. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-004` | error | Requires exactly one scope selector to prevent ambiguous cohort targeting. | Hard fail on missing or mixed scope arguments. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-005` | error | Blocks zero-row scoped delivery actions for tabular outputs while allowing explicit zero-row final-summary PDFs. | Hard fail on empty scoped tabular delivery set. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-006` | error | Restricts deliveries to locked output IDs. | Hard fail on unsupported output IDs. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-007` | warning | Guarantees no-upload inspect directories are isolated and stale inspection/cache artifacts are bounded. | Warning or informational enforcement with deterministic cleanup. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-04-008` | error | Constrains SharePoint cleanup to safe report/output combinations and dry-run inspectability. | Hard fail on invalid cleanup mode or final-summary lock conflict; warning logs for cleanup outcomes. | CLI validation summary and run artifacts; warning details artifact when emitted. |

## Category 05: IO And Runtime Safety Controls

Workflow context: In day-to-day ISPA operations, this check protects runtime and external-IO safety so configuration or service issues fail safely instead of silently misrouting outputs.

| Rule | Severity | Intent | Outcome | Evidence |
|---|---|---|---|---|
| `ISPA-05-001` | warning | Retains historical root-scoped discovery control as governance context only. | Retired; not actively enforced. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-05-002` | error | Enforces strict typed Graph API error handling for SharePoint operations. | Hard fail on Graph API operation errors. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-05-003` | error | Requires explicit runtime config and required file paths. | Hard fail on missing or invalid required config. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-05-004` | error | Sanitizes SharePoint remote paths and file leaf names. | Hard fail on invalid remote path shapes. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-05-005` | warning | Applies ADLS prefix strictness with controlled resilience. | Warning or hard fail depending on operation and prefix mode. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-05-006` | error | Prevents incoherent run plans by validating dependency relationships between derive and publish options. | Hard fail on invalid plan combinations. | CLI validation summary and run artifacts; warning details artifact when emitted. |

## Category 06: Quality Evidence And Artifact Hygiene

Workflow context: In day-to-day ISPA operations, this check protects auditability and data-handling hygiene so teams can review decisions without retaining unnecessary sensitive artifacts.

| Rule | Severity | Intent | Outcome | Evidence |
|---|---|---|---|---|
| `ISPA-06-001` | warning | Captures input manifest evidence for each run. | Warning or evidence control recorded in artifact payload. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-002` | warning | Detects exact duplicate input files for provenance quality investigations. | Warning or evidence control. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-003` | warning | Raises missing-input alerts for incomplete expected intake conditions. | Warning alert control. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-004` | warning | Produces per-school delta warnings for abnormal distribution shifts. | Warning alert control. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-005` | warning | Minimizes retention of report-source artifacts to reduce exposure of sensitive derived content. | Warning-governed hygiene control with opt-in retention behavior. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-006` | warning | Supports optional long numeric ID redaction in logs. | Warning-governed hygiene control; configurable behavior. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-007` | warning | Aggregates field-level parse failure counters for quality diagnostics. | Warning-only quality signal. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-008` | warning | Retains per-slice expected-input profiling as low-priority governance context. | Recommended retire; not core active enforcement. | CLI validation summary and run artifacts; warning details artifact when emitted. |
| `ISPA-06-009` | warning | Maintains a unified run artifact as the evidence envelope for stage outcomes, alerts, and validation telemetry. | Required evidence output for each run. | CLI validation summary and run artifacts; warning details artifact when emitted. |
