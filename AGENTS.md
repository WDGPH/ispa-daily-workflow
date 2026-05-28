# AGENTS.md

Operational guidance for coding agents working on the WDGPH ISPA Daily
Workflow. Keep this file concise; the operator runbook belongs in `README.md`
and the detailed test ladder belongs in `testing.md`.

## Purpose and boundary

This repository is the Panorama- and PEAR-backed ISPA compliance workflow used
by Wellington-Dufferin-Guelph Public Health (WDGPH). It is published as a
reference implementation, not as a turnkey or vendor-neutral platform.

Preserve the operational behavior WDGPH relies on. Do not rename the
`ispa_daily_workflow` import package, the `ispa-daily-workflow` distribution,
commands, output IDs, schemas, or compliance-state semantics without an explicit
requirement and migration plan.

## Architecture pointers

- `src/ispa_daily_workflow/pipeline/`: state-update and delivery orchestration.
- `src/ispa_daily_workflow/domain/`: source and delivery business rules.
- `src/ispa_daily_workflow/io/`: SharePoint, Graph, ADLS, discovery, and readers.
- `src/ispa_daily_workflow/validation/`, `quality/`, and `schema/`: guardrails,
  evidence, and dataset contracts.
- `src/ispa_daily_workflow/reports/` and `templates/`: PDF preparation and Typst
  generation.
- `src/ispa_daily_workflow/commands/`: supporting and advanced CLI entry points.
- `schema/`: dataset registry and versioned schemas.
- `profile.example/`: public demonstration profile; `profile/` is local-only.
- `tests/`: unit, integration, command-surface, and synthetic E2E coverage.

Start operator-facing questions in `README.md`. For architecture, dependency,
or impact claims, inspect current source and tests instead of relying on stale
generated summaries.

## Environment and canonical commands

- Python: `>=3.10,<3.14`.
- Dependency manager and runtime: `uv`.
- Default runtime configuration: `profile/config.yaml`.
- Relative configuration paths resolve from the directory containing the
  configuration file.

Set up a development checkout with:

```bash
uv sync --locked
cp -R profile.example profile
```

Use the two primary commands for routine workflow work:

```bash
uv run update-state --help
uv run deliver-outputs --help
```

Run the required lightweight checks before finishing:

```bash
uv run python -m compileall src
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
uv run pytest
uv run prek run --all-files
git diff --check
```

Use the SharePoint-safe acceptance plan when command behavior is touched:

```bash
uv run local-acceptance --run-date YYYYMMDD --with-local-delivery --dry-run
```

See `testing.md` for markers, coverage guidance, production-like PDF checks,
and the full local acceptance workflow.

## Privacy and publication safety

- Use only synthetic or de-identified examples in source, tests, documentation,
  issues, and pull requests.
- Never commit client or student records, real case details, private school
  routing, non-example SharePoint URLs, tenant IDs, credentials, tokens, mounted
  secret values, logs, journals, generated business outputs, or run artifacts.
- Keep organization-specific configuration, reference data, workday calendars,
  branding, destinations, and approval procedures out of tracked `profile/`.
- Do not inspect raw input files for diagnosis unless the user explicitly asks.
- Security and privacy concerns must follow `SECURITY.md`; do not put sensitive
  evidence in a public issue.

## Change rules

### Configuration

- Preserve `profile/config.yaml` as the default and the existing resolver.
- Keep `profile.example/` internally consistent and clearly demonstrative.
- Do not add a parallel environment-variable or configuration framework without
  an explicit operational requirement.

### Schemas and datasets

- The primary join key is string `client_id`.
- Landing headers are strict; processed outputs use canonical selected fields.
- Schema versions belong in filenames as `*_v<major>.<minor>.json`.
- Keep `schema/datasets_v1.0.json`, versioned schema files, code, and tests in
  sync.
- Treat `school_reference.json` as the authority for school, wave, and level
  identifiers and routing metadata.

### Validation and evidence

- Treat validation changes as operational policy changes. Document the risk,
  hard-fail versus warning behavior, evidence location, and affected tests.
- Update `src/ispa_daily_workflow/validation/catalog.py`, then regenerate
  `validation-rules.md` with `uv run generate-validation-rules`.
- Preserve full affected `client_id` values and available `source_file` context
  in human-investigation messages; do not sample IDs in primary messages.
- Apply age-policy warnings only to unresolved rows where `compliant` is null.
- Preserve real school labels across full joins when either side has a label.

### Operational outputs

- `compliance_history` remains the source of truth for Panorama list streams.
- Preserve source-specific behavior: Panorama and PEAR are explicit and are not
  silently interchangeable.
- Preserve upload/download defaults, scope requirements, output naming, report
  content, and SharePoint cleanup safety unless the task explicitly changes the
  contract.
- XLSX delivery starts in `pipeline/deliver_outputs.py`,
  `pipeline/deliver_tabular_outputs.py`, and `domain/delivery/`.
- PDF delivery routes through delivery code into `reports/` and `templates/`.
- Update `README.md` whenever operator-visible workflow behavior changes.
