# Testing Before Merge

This repo should use a light acceptance ladder: enough coverage to catch command,
validation, and delivery regressions before production, without chasing broad
unit-test coverage for every helper.

## Test Ladder

Run from the repo root with the repo-local environment:

```bash
uv sync --locked
uv run python -m compileall src
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
uv run pytest
uv run prek run --all-files
git diff --check
```

For validation-focused work:

```bash
uv run pytest -m validation
```

To gauge coverage without making coverage percentage the target:

```bash
uv run pytest --cov=ispa_daily_workflow --cov-report=term-missing:skip-covered
```

Coverage should be read as a map of unexercised command and validation surfaces,
not as a gate to maximize.

## SharePoint-Safe Acceptance

Use `local-acceptance` for the pre-merge operator check. It has two
safety rules baked in:

- `update-state` checks are `--dry-run` only.
- `deliver-outputs` checks force `--no-upload --no-download`.

This command runs compile, pytest, update-state dry-runs for both sources, and
local cached delivery checks for the default output matrix:

```bash
uv run local-acceptance \
  --run-date YYYYMMDD \
  --with-local-delivery \
  --scope-dimension wave \
  --scope-value ALL
```

Add coverage when useful:

```bash
uv run local-acceptance \
  --run-date YYYYMMDD \
  --coverage \
  --with-local-delivery
```

If local cached state is incomplete, first run the command plan only:

```bash
uv run local-acceptance \
  --run-date YYYYMMDD \
  --with-local-delivery \
  --dry-run
```

To target one delivery check:

```bash
uv run local-acceptance \
  --run-date YYYYMMDD \
  --with-local-delivery \
  --delivery pear:sharepoint.suspension.pdf \
  --scope-dimension wave \
  --scope-value SECONDARY1
```

Do not use routine publishing commands as pre-merge tests. For delivery checks
that may use authoritative ADLS input but must not publish, keep `--no-upload`
explicit:

```bash
uv run deliver-outputs sharepoint.suspension.pdf \
  --source pear \
  --run-date YYYYMMDD \
  --wave ALL \
  --no-upload
```

For fully local cached state, also use `--no-download`.

## Datafile Profiling For Fictional Fixtures

Use the profiler to inspect real local data shapes without emitting cell values
by default:

```bash
uv run inspect-datafiles \
  input output/pear_processed output/compliance_history \
  --recursive \
  --output artifacts/data_profiles/YYYYMMDD_profile.json
```

Markdown output is useful for review:

```bash
uv run inspect-datafiles output/pear_processed \
  --recursive \
  --format markdown \
  --output artifacts/data_profiles/YYYYMMDD_pear_processed.md
```

The default profile includes file shape, table shape, column names, observed
types, null rates, unique counts, and string lengths. Directory scans include
CSV, Parquet, and Excel files by default; explicit JSON files such as
`profile/school_reference.json` can also be profiled. The profile does not
include cell examples. Add `--include-ranges` only when date or numeric min/max
values are needed for fixture design. Add `--include-examples` only when the
output will stay private and local.

Use these profiles to create small fictional datasets under `tests/fixtures/`
later. The goal is a representative E2E fixture set that covers:

- Panorama compliance_history update and scoped delivery.
- PEAR landing/processed/state derivation.
- Validation failures and warnings that should block or surface uncertainty.
- No-upload PDF/XLSX delivery from local cached state.
