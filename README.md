# WDGPH ISPA Daily Workflow

[![CI](https://github.com/WDGPH/ISPA-daily-workflow/actions/workflows/ci.yml/badge.svg)](https://github.com/WDGPH/ISPA-daily-workflow/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This repository contains the ISPA daily compliance workflow used by
Wellington-Dufferin-Guelph Public Health (WDGPH). It is shared as a reference
implementation for transparency, reuse, and adaptation by other public health
organizations. It reflects WDGPH's source systems, Microsoft cloud environment,
and operating practices; it is not a turnkey product or a complete statement of
how every health unit should administer ISPA workflows.

Panorama and PEAR report formats and local operating policies may differ between
organizations. Local configuration, school reference data, calendars,
credentials, SharePoint destinations, and approval processes are intentionally
excluded. Adopters should expect to supply those items and may need to adapt
source-specific transforms.

The project uses `ispa_daily_workflow` as its Python import package and
`ispa-daily-workflow` as its distribution name.

The system has two main commands:

1. `update-state`: refresh authoritative state for one source and run date.
2. `deliver-outputs`: generate and optionally publish one scoped output.

## What This Does

The important operational distinction is state versus delivery.

`update-state` decides what the official source state is. It does not publish
school-facing outputs.

`deliver-outputs` decides which subset of that state should be inspected or
published. Re-running delivery should not silently mutate authoritative state.

Main sources:

| Source | Meaning | Primary state |
|---|---|---|
| `panorama` | Longitudinal ISPA compliance backbone | `compliance_history` |
| `pear` | PEAR operational reporting and suspension pathway | PEAR processed inputs plus derived PEAR state, including `suspension_operational` |

Main outputs:

| Output ID | Source | Operational meaning |
|---|---|---|
| `sharepoint.panorama.diff.xlsx` | `panorama` | Students who were noncompliant on the previous business day and are now compliant |
| `sharepoint.action_queue.xlsx` | `pear` | PEAR action queue derived from `suspension_vs_overdue` |
| `sharepoint.overdue.pdf` | `panorama` or `pear` | School-facing overdue report PDFs |
| `sharepoint.suspension.pdf` | `panorama` or `pear` | School-facing suspension report PDFs |

Panorama and PEAR are not interchangeable. `deliver-outputs` never switches
sources automatically. Panorama `compliant` dates and PEAR `rescind_date`
signals can describe related workflow events with different timing, so the
pipeline validates continuity and temporal plausibility rather than forcing
cross-source date equality.

## Before You Run

The WDGPH deployment uses SharePoint for source and publication IO and Azure
Data Lake Storage Gen2 (ADLS) for authoritative state. Those are the default
adapters in `profile.example/config.yaml`, not claims that every adopter must
use the same storage design. The repository also includes local filesystem
adapters for development and evaluation; another production backend requires
adapter implementation and local operational validation.

The following infrastructure, inputs, and decisions must exist outside the
code:

- For the default state-store adapter, an ADLS storage account and container
  have been provisioned with reviewed landing and processed prefixes.
- For the default input and output adapters, a SharePoint site and the
  configured source and destination folders already exist, and the application
  identity has only the Microsoft Graph access required for those locations.
- ADLS and SharePoint credentials are mounted as files outside the repository;
  `profile/config.yaml` points to those mounts and never contains secret values.
- Install the [Typst CLI](https://typst.app/open-source/) on every host that
  compiles PDF outputs, and confirm `typst --version` succeeds. Typst is an
  external executable and is not installed by `uv sync`.
- Panorama exports have been placed in the configured SharePoint drop folder
  before `update-state --source panorama` runs.
- PEAR overdue, suspension, and `suspension_vs_overdue` reports have been
  generated and placed in configured SharePoint source folders before
  `update-state --source pear` runs.
- `school_reference.json` is current for schools, waves, levels, optional
  school-level SharePoint routing, and PEAR suspension window metadata.
- `workdays.csv` includes the run date and previous-business-day mappings needed
  for diffs, suspension continuity checks, and rescind reporting windows.
- Someone is responsible for reviewing warnings, validation summaries, and run
  artifacts before school-facing outputs are published.

## Daily Workflow

Update authoritative state first:

```bash
uv run update-state --source panorama --run-date YYYYMMDD
uv run update-state --source pear --run-date YYYYMMDD
```

Use dry-run mode when checking configuration or source availability:

```bash
uv run update-state --source panorama --run-date YYYYMMDD --dry-run
uv run update-state --source pear --run-date YYYYMMDD --dry-run
```

Inspect delivery locally before publishing. This reads authoritative state from
ADLS but skips SharePoint upload:

```bash
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL --no-upload
```

For fully local cached inspection, also skip ADLS download:

```bash
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL --no-upload --no-download
```

Publish one scoped output after review:

```bash
uv run deliver-outputs sharepoint.panorama.diff.xlsx --source panorama --run-date YYYYMMDD --wave ALL
uv run deliver-outputs sharepoint.action_queue.xlsx --source pear --run-date YYYYMMDD --wave ALL
uv run deliver-outputs sharepoint.overdue.pdf --source panorama --run-date YYYYMMDD --wave ALL
uv run deliver-outputs sharepoint.suspension.pdf --source pear --run-date YYYYMMDD --wave ALL
```

Rebuild a date range when operational recovery requires it:

```bash
uv run rebuild-outputs --start-date YYYYMMDD --end-date YYYYMMDD
```

If `--deliver` is provided without a scope flag, `rebuild-outputs` defaults
delivery scope to `--wave ALL`.

## Guardrails

`update-state` always processes exactly one source: `--source panorama` or
`--source pear`.

Panorama history bootstrap is guarded:

```bash
uv run update-state \
  --source panorama \
  --run-date YYYYMMDD \
  --init-compliance-history \
  --wave SECONDARY1 \
  --allow-new-client-ids
```

Rules that matter:

- `--init-compliance-history` must be combined with `--wave`.
- `--allow-new-client-ids` must be combined with exactly one of `--wave`,
  `--level`, or `--school`.
- On non-initial business days, Panorama state update hard-fails when no prior
  `compliance_history` snapshot exists unless bootstrap is explicit.

`deliver-outputs` always requires one `output_id`, one `--source`, one
`--run-date`, and exactly one scope flag:

```bash
--wave VALUE|ALL
--level VALUE|ALL
--school VALUE|ALL
```

Delivery IO rules:

- Upload and download are enabled by default.
- Upload requires download.
- `--no-upload --download` is the recommended review mode.
- `--no-upload --no-download` is local cache inspection mode.
- `--cleanup-sharepoint-pdfs` is valid only for overdue and suspension PDFs.

Before publishing school-facing outputs, review validation failures and
warnings, previous-business-day continuity messages, scope and row-count
reasonableness, source freshness, and any exception workflow used during the
run.

## PEAR Notes

This repository does not create PEAR reports. It downloads already-generated
PEAR reports, validates them, converts them to canonical landing and processed
artifacts, derives PEAR state, and uses that state for PEAR-backed delivery.

Operational details that affect publication:

- `suspension_vs_overdue` is an action signal, not just a comparison file.
- `suspension_operational` is the PEAR suspension-report dataset used for
  suspension PDF delivery.
- PEAR suspension continuity is enforced by business day, wave, and level using
  `workdays.csv` and suspension windows from `school_reference.json`.
- PEAR overdue continuity warnings do not hard-fail state derivation when the
  previous-business-day overdue input is missing.
- Unexpected suspension disappearances are restored with warning evidence so
  reviewers can see what changed.
- `--pear-suspension-file` and the cutover patch helper are exceptional
  reconciliation tools, not routine workflow.

For detailed PEAR behavior, start with the PEAR intake and state modules under
`src/ispa_daily_workflow/pipeline/` and `src/ispa_daily_workflow/domain/pear/`.

## Validation And Evidence

Validation is part of the operating model. The pipeline uses hard stops,
warnings, and artifacts to make source drift and uncertainty visible before
school-facing outputs are trusted or published.

Validation covers ingest contracts, identity and school-reference integrity,
temporal continuity, delivery contracts, runtime safety, and evidence hygiene.

When CLI output or a run artifact includes a line such as
`VALIDATION WARN [ISPA-03-008] ...`, open
[validation-rules.md](validation-rules.md) and search for the rule ID.

Evidence usually lands under:

- `artifacts/runs/`
- `artifacts/data_quality/`
- `artifacts/warnings/`
- `output/compliance_history/`
- `output/inspect/`

When validation policy changes, update
`src/ispa_daily_workflow/validation/catalog.py` first, then regenerate
`validation-rules.md`:

```bash
uv run generate-validation-rules
```

## Configuration

Initialize a local profile from the example:

```bash
cp -R profile.example profile
```

Runtime configuration lives in `profile/config.yaml` and should not be
committed.

Minimum configuration areas:

- `run.*`: timezone, workday calendar, school-year settings
- `paths.*`: input, output, artifacts, logs, reference data
- `validation.*`: schemas and header strictness
- `io.input_provider`, `io.state_store`, and `io.output_publisher`: select the
  default cloud adapters or explicit local filesystem adapters
- `io.adls.*`: mounted secret files plus landing and processed prefixes when
  the ADLS state-store adapter is selected
- `io.sharepoint.*`: mounted secret files plus source and destination folders
  when SharePoint input or output adapters are selected

Important conventions:

- Relative paths in `profile/config.yaml` are resolved from the `profile/`
  directory containing that file.
- The WDGPH defaults are SharePoint input, ADLS authoritative state, and
  SharePoint publication. A local adapter requires a configured `root` path.
- `schema/datasets_v1.0.json` is the dataset registry used by the codebase.
- `school_reference.json` is the source of truth for valid schools, levels, and
  waves.
- PEAR suspension workflows require `suspension_applied_date`,
  `suspension_window_start`, and `suspension_window_end` metadata.
- Optional school-level SharePoint PDF routing can use `sharepoint_folder` in
  `school_reference.json`.
- ADLS and SharePoint credentials are read from mounted secret files referenced
  by `io.adls.secret_files.*` and `io.sharepoint.secret_files.*`.

## Setup

Recommended setup:

```bash
uv sync --locked
cp -R profile.example profile
uv tool install --force -e .
```

`uv sync` installs the Python environment, but it does not install Typst. If
this host will generate PDFs, install the Typst CLI separately and verify it:

```bash
typst --version
```

If the executable is not named `typst` or is not on `PATH`, set
`outputs.pdf.typst_bin` in `profile/config.yaml` to its reviewed location.

If direct commands are not found in your shell, run:

```bash
uv tool update-shell
```

Commands can be run directly:

```bash
update-state --source panorama --run-date YYYYMMDD
deliver-outputs sharepoint.panorama.diff.xlsx --source panorama --run-date YYYYMMDD --wave ALL
```

Or through the repo-local environment:

```bash
uv run update-state --source panorama --run-date YYYYMMDD
uv run deliver-outputs sharepoint.panorama.diff.xlsx --source panorama --run-date YYYYMMDD --wave ALL
```

## Testing

Use the repo-local `uv` environment:

```bash
uv run pytest
uv run local-acceptance --run-date YYYYMMDD --with-local-delivery
uv run prek run --all-files
```

Install the `prek` commit hook when preparing a development checkout:

```bash
uv run prek install --hook-type pre-commit
```

`local-acceptance` keeps production publishing out of the acceptance
loop: `update-state` runs in dry-run mode and delivery checks use
`--no-upload --no-download`.

For coverage:

```bash
uv run pytest --cov=ispa_daily_workflow --cov-report=term-missing:skip-covered
```

See [testing.md](testing.md) for the full lightweight testing ladder.

## Where To Look Next

| Need | Start here |
|---|---|
| Operator commands | This README |
| Validation rule meaning | [validation-rules.md](validation-rules.md) |
| Codebase relationships | `src/`, `tests/`, and code search |
| Agent and repo conventions | [AGENTS.md](AGENTS.md) |
| Local profile shape | [profile.example](profile.example/) |
| Test strategy | [testing.md](testing.md) |
| Contribution process | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Community expectations | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |

High-level source layout:

- `src/ispa_daily_workflow/`: package code
- `src/ispa_daily_workflow/commands/`: package-owned CLI implementations
- `schema/`: dataset registry and table schemas
- `profile.example/`: local profile scaffold
- `tests/`: unit, integration, and fixture tests

## Adoption Notes

Another public health unit adopting this repository should document several
local decisions outside the code:

- who exports Panorama files,
- who generates PEAR reports,
- when source files are expected to be available,
- which outputs are allowed to use each source,
- what freshness expectation is promised to schools and school boards,
- who reviews warnings and approves publication,
- what fallback and cutover process is used when a source is late or incomplete.

Without that local operating policy, the code can still run, but the workflow
may not match the organization's service expectations.

## Public Collaboration

This project is MIT licensed. Public health units and public-sector
collaborators are welcome to adapt it for local ISPA operations, but local
deployment data must stay private.

Before publishing, sharing, or opening a pull request:

- keep real runtime configuration in `profile/` or another private repository,
- keep generated source data, reports, logs, and run artifacts out of Git,
- use synthetic examples in issues, tests, and documentation,
- document validation policy changes in
  `src/ispa_daily_workflow/validation/catalog.py`,
- regenerate `validation-rules.md` after validation catalog changes,
- follow the PHU-oriented guidance in [CONTRIBUTING.md](CONTRIBUTING.md).

Participation in this repository is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Related Projects

[`WDGPH/ImmuKnow`](https://github.com/WDGPH/immuknow) generates personalized
immunization history charts and notice letters for children overdue for
mandated vaccinations under the Child Care and Early Years Act (CCEYA) and ISPA.