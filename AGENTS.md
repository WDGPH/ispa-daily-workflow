# AGENTS.md

Agent onboarding for `panorama-compliance`. Keep this file short and operational:
it should state durable repo rules, not duplicate the source tree.

## Purpose

This repo is the standalone ISPA compliance pipeline for Panorama- and
PEAR-backed school compliance workflows.

It updates authoritative source state, derives scoped delivery inputs, generates
school-facing XLSX/PDF outputs, publishes to SharePoint when requested, and
records validation, warning, and run evidence for review.

For the operator-facing explanation, start with `README.md`. For codebase
relationships, inspect `src/`, `tests/`, and the focused docs referenced here.

## Repo Map

- `src/panorama_compliance/`: core package.
  - `pipeline/`: orchestration for state update, PEAR intake/state, delivery, and daily runs.
    - `intake_pear.py` is the PEAR intake CLI conductor.
    - `pear_intake_sources.py`, `pear_intake_outputs.py`, and
      `pear_intake_rescinds.py` own PEAR intake source download, output
      planning, and rescind patching boundaries.
  - `domain/`: business rules for source and delivery domains.
  - `ingest/`, `compliance_history/`, `pear_state/`: source-state construction and compatibility facades.
  - `io/`: SharePoint facade plus Graph/path/item helpers, ADLS, file discovery, readers, and workdays.
  - `validation/`, `quality/`, `schema/`: guardrails, evidence, and dataset contracts.
  - `reports/`: report data preparation, Typst source writing, compilation, and cleanup.
  - `templates/`: editable Typst template generators for school-facing PDFs.
  - `reference/`: school-reference loading and scope authority.
- `src/panorama_compliance/commands/`: package-owned secondary CLI implementations.
- `schema/`: dataset registry and versioned table schemas (`*_v<major>.<minor>.json`).
- `profile.example/`: scaffold for local/private runtime profile content.
- `profile/`: local or private profile content; ignored and not part of the public repo.
- `assets/`: shared static assets.
- `output/`: generated business outputs; do not treat as source code.
- `artifacts/`: run artifacts, data-quality manifests, parity reports, warnings, and alerts.

## Environment

- Python: `>=3.10,<3.14`.
- Package manager/runtime: `uv`.
- Setup (recommended):

```bash
uv sync
cp -R profile.example profile
uv tool install --force -e .
```

- If direct commands (for example `update-state`) are not on PATH, run:

```bash
uv tool update-shell
```

- Optional org-specific step:
  - If using a private profile repository, clone or mount it outside the public
    Git history and expose its files through local `profile/config.yaml`.

- `profile/config.yaml` is local-only and should not be committed.
- Prefer profile-submodule wiring in `profile/config.yaml` for org-specific files:
  - `paths.reference: "school_reference.json"`
  - `run.workdays_csv: "workdays.csv"`
- If `uv` is unavailable, run commands with a virtualenv that has dependencies from `pyproject.toml` installed.
- Use `uv run ...` for repo commands. Direct console scripts are optional and
  depend on a healthy `uv tool` install.

## Secrets Configuration

- ADLS credentials use mounted secret files via:
  - `io.adls.secrets_path`
  - `io.adls.secret_files.{tenant_id,client_id,client_secret,storage_account,container}`
- SharePoint credentials follow the same mounted-secret approach via:
  - `io.sharepoint.secrets_path`
  - `io.sharepoint.secret_files.{tenant_id,client_id,client_secret}`
- SharePoint URLs live under `io.sharepoint.destinations`.
- ADLS storage roots live under `io.adls.destinations.{landing_prefix,processed_prefix}`.
- Runtime behavior (state update + scoped delivery) is CLI-owned.
- Use `profile.example/config.yaml` as the template; keep real values only in local `profile/config.yaml`.

## Core Runbook

- Step 1: Update authoritative state:

```bash
uv run update-state --source panorama --run-date YYYYMMDD
uv run update-state --source pear --run-date YYYYMMDD
```

- State update dry run (no writes/uploads/deletes):

```bash
uv run update-state --source panorama --run-date YYYYMMDD --dry-run
uv run update-state --source pear --run-date YYYYMMDD --dry-run
```

- State update with explicit compliance_history safety overrides:

```bash
uv run update-state \
  --source panorama \
  --run-date YYYYMMDD \
  --init-compliance-history \
  --wave SECONDARY1 \
  --allow-new-client-ids
```

State-update behavior is source-specific:
- `--source panorama` updates the longitudinal `compliance_history` backbone.
- `--source pear` intakes PEAR reports and derives PEAR state used by
  PEAR-backed delivery.

If ADLS compliance_history sync is enabled but no prior compliance_history snapshot is available
(and none exists locally), `update-state` hard-fails on non-initial business days
to prevent accidental history reset. Bypass only when intentional with
`--init-compliance-history`.

Safety rules:
- `--init-compliance-history` must be combined with `--wave`.
- `--allow-new-client-ids` must be combined with exactly one of `--wave`, `--level`, or `--school`.

- Step 2: Deliver one scoped output:

```bash
uv run deliver-outputs <output_id> --source panorama --run-date YYYYMMDD --wave ALL
uv run deliver-outputs <output_id> --source pear --run-date YYYYMMDD --wave ALL
```

Supported `<output_id>`:
- `sharepoint.panorama.diff.xlsx`
- `sharepoint.action_queue.xlsx`
- `sharepoint.overdue.pdf`
- `sharepoint.suspension.pdf`

Delivery implementation note:
- XLSX outputs are not Typst-backed; start with `pipeline/deliver_outputs.py`,
  `pipeline/deliver_tabular_outputs.py`, and `domain/delivery/`.
- PDF output routing still starts in delivery code, then report data flows through
  `reports/` into editable Typst template generators under `templates/`.

Exactly one scope flag is required:
- `--wave VALUE|ALL`
- `--level VALUE|ALL`
- `--school VALUE|ALL`

Example scoped deliveries:

```bash
uv run deliver-outputs sharepoint.panorama.diff.xlsx --source panorama --run-date YYYYMMDD --wave SECONDARY1
uv run deliver-outputs sharepoint.action_queue.xlsx --source pear --run-date YYYYMMDD --level SECONDARY
uv run deliver-outputs sharepoint.overdue.pdf --source panorama --run-date YYYYMMDD --school 1100
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL
```

- SharePoint extract (drop folder -> local `input/raw`, optional ADLS landing upload):

```bash
uv run extract-inputs --run-date YYYYMMDD
```

- Daily diff only:

```bash
uv run diff-lists daily --previous-file <prev> --current-file <current>
```

- Daily diff upload to SharePoint list-difference destination:

```bash
uv run diff-lists daily --previous-file <prev> --current-file <current> --sharepoint-upload
```

- Daily diff from compliance_history:

```bash
uv run diff-lists daily \
  --compliance_history-file output/compliance_history/YYYYMMDD_panorama_<slice>_compliance_history.parquet \
  --previous-date YYYYMMDD \
  --run-date YYYYMMDD
```

- Adhoc diff:

```bash
uv run diff-lists adhoc --baseline-file <baseline> --delivery-file <delivery>
```

- Adhoc diff from compliance_history:

```bash
uv run diff-lists adhoc \
  --compliance_history-file output/compliance_history/YYYYMMDD_panorama_<slice>_compliance_history.parquet \
  --baseline-date YYYYMMDD \
  --delivery-date YYYYMMDD
```

- Reports only:

```bash
uv run build-reports --run-date YYYYMMDD --report both
```

- Reports only (force overdue from combined fallback):

```bash
uv run build-reports --run-date YYYYMMDD --report overdue --overdue-source combined
```

- Rebuild range:

```bash
uv run rebuild-outputs --start-date YYYYMMDD --end-date YYYYMMDD
```

- Rebuild range + scoped deliveries:

```bash
uv run rebuild-outputs \
  --start-date YYYYMMDD \
  --end-date YYYYMMDD \
  --deliver sharepoint.panorama.diff.xlsx \
  --deliver sharepoint.action_queue.xlsx \
  --wave ALL
```

- Delivery-only rebuild pass (skip state update):

```bash
uv run rebuild-outputs \
  --start-date YYYYMMDD \
  --end-date YYYYMMDD \
  --skip-state-update \
  --deliver sharepoint.overdue.pdf \
  --level SECONDARY
```

If `--deliver` is provided without a scope flag, `rebuild-outputs`
defaults delivery scope to `--wave ALL`.

- Dry-run scoped delivery validation:

```bash
uv run deliver-outputs sharepoint.panorama.diff.xlsx --source panorama --run-date YYYYMMDD --wave ALL --dry-run
```

- No-upload scoped delivery inspection from authoritative ADLS state:

```bash
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL --no-upload
```

- Fully local cached inspection (no upload + no ADLS download):

```bash
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL --no-upload --no-download
```

- Scoped PDF delivery with SharePoint history cleanup:

```bash
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL --cleanup-sharepoint-pdfs
```

No-upload delivery behavior:
1. writes scoped outputs under `output/inspect/{run_date}/source={source}/io=u0_d{0|1}/{output_id}/{scope}`,
2. clears that exact scoped folder before generation to avoid stale inspection files,
3. skips SharePoint uploads and prints a cleanup command.

SharePoint PDF cleanup behavior:
1. `--cleanup-sharepoint-pdfs` is valid only for `sharepoint.overdue.pdf` and `sharepoint.suspension.pdf`,
2. it requires upload mode in execute runs (`--upload`) and is therefore incompatible with `--no-upload` unless using `--dry-run`,
3. with `--dry-run`, the CLI lists exactly which SharePoint files would be removed,
4. default logging/summary uses shorter path and folder display; use `--verbose` for full paths/URLs and per-folder cleanup logs.

Delivery IO mode rules:
1. `--upload` and `--download` are enabled by default.
2. `--upload` requires `--download`; `--upload --no-download` is invalid.
3. `--no-upload --download` is the recommended test mode for authoritative input + local-only output.
4. `--no-upload --no-download` is local cache inspection mode.
5. With `--source pear`, `--download` re-syncs run-date PEAR processed snapshots from ADLS and re-derives local PEAR state before delivery.

Automatic retention cleanup in non-dry-run `deliver-outputs`:
1. prune `output/inspect/*` run-date folders older than 14 days,
2. prune `input/state_sync/*` run-date folders older than 7 days,
3. prune `artifacts/data_quality/*` run-date files older than 30 days,
4. preserve `artifacts/runs/*` and `output/compliance_history/*`.

## Contracts And Conventions

- Primary join key is `client_id` (string).
- Header validation is strict against landing schema (`schema/landing_panorama_compliance_v1.0.json`).
- ADLS landing downloads ingest only canonical run-date files named
  `YYYYMMDD_panorama_compliance_*.xlsx`; legacy/non-canonical filenames are ignored.
- Canonical raw landing files preserve landing-schema headers (for example `Client ID`);
  processed snake_case headers are for processed outputs, not landing inputs.
- Processed outputs are schema-selected and minimized per stream.
- Compliance History is the source of truth for list streams:
  - combined noncompliant is derived from active compliance_history rows (`compliant` null or > run date),
  - daily/adhoc became_compliant is derived from compliance_history compliance windows,
  - overdue report input is derived from active compliance_history rows,
  - suspension report input uses compliance_history snapshot rows,
  - new compliance_history snapshots are emitted per slice only when merged compliance_history state changes.
- Schema versions are encoded in filename (`*_v<major>.<minor>.json`).
- If two raw files map to the same standardized canonical target, standardization
  overwrites the target with the later file and emits a warning (run does not hard-fail).
- Optional school-level SharePoint PDF routing uses `sharepoint_folder` in
  the active school reference file configured via `paths.reference` (default `school_reference.json`).
- Expected school reference row fields are `school_name`, `school_id`, `level`, `wave`, `fq_group`
  with optional `sharepoint_folder`.
- Identifier source of truth:
  - wave and level identifiers must match the active school reference file (`paths.reference`, default `school_reference.json`),
  - treat the reference file as the source of truth for valid `wave` and `level` values,
  - if identifiers change in the reference file, update strict validators in:
    - `src/panorama_compliance/ingest/combine.py`,
    - `src/panorama_compliance/validation/scope.py`,
    - `src/panorama_compliance/domain/delivery/routing.py`,
  - `compliance_history` remains wave-sliced regardless of whether run filters use `--wave`, `--level`, or `--school`.
- Output naming patterns:
  - `output/combined/{date}_panorama_{slice}_noncompliant.{xlsx|parquet}`
  - `output/diffs/{current}_{previous}_panorama_{slice}_became_compliant.{xlsx|parquet}`
  - `output/diffs/{delivery}_{baseline}_panorama_adhoc_became_compliant.{xlsx|parquet}`
  - `output/compliance_history/{date}_panorama_{slice}_compliance_history.{xlsx|parquet}`

## Data Quality And Evidence

- Run artifacts: `artifacts/runs/{run_id}.json`.
- Guardrails include:
  - required-field checks,
  - duplicate-key checks,
  - diff subset enforcement (`current_only` protection),
  - unknown-school protection,
  - workday calendar integrity.
- Compliance History-specific controls:
  - hard-fail on unexpected compliance_history `client_id` additions (unless explicitly bypassed),
  - warning when daily diff is requested without a previous business day,
  - hard-fail when compliance_history sync finds no prior snapshot (and none exists locally) on non-initial business days unless explicitly bypassed with `--init-compliance-history`,
  - one JSON run artifact containing stage outcomes, quality counters, alerts, and output inventory,
  - concise end-of-run warning/error summary in CLI output,
  - quiet third-party HTTP request logs by default (enable with `--verbose`),
  - SharePoint publish path checks + strict Graph error handling.

## Logging Preferences

- Guardrail identity/age messages should include full affected `client_id` values (no sampled IDs in primary message text).
- ISPA age policy warnings should apply only to unresolved rows (`compliant` is null), not historical rows with a populated `compliant` date.
- When available, include `source_file` for each affected `client_id`.
- For affected-ID investigation output, prefer:
  1. one summary header line,
  2. one indented `client_id=... source_file=...` line per affected row.
- Keep critical-message text human-investigation friendly in CLI output (`Critical messages`) and easy to copy/paste.
- Do not inspect raw input files for diagnosis unless explicitly requested by the user.
- For school-row delta alerts, preserve real school labels across full joins; avoid `UNKNOWN` when either join side has a label.

## Agent Change Checklist

Before finishing work:
- Run lightweight validation for touched code (at minimum `python -m compileall src` for Python edits).
- Verify outputs/paths for operational script changes.
- Keep schema and code changes synchronized.
- Update `README.md` when workflow behavior changes.
- For architecture, dependency, or impact-analysis claims, verify against the
  current source and tests rather than relying on stale generated summaries.
