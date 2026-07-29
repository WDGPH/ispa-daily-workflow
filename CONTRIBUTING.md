# Contributing

WDGPH shares this ISPA daily workflow as a reference implementation for public
health units and public-sector collaborators adapting Panorama- and PEAR-backed
compliance automation to local operations. It reflects WDGPH's environment and
is not a turnkey, vendor-neutral platform.

Participation in this repository is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Collaboration Expectations

- Use synthetic or de-identified examples in issues, pull requests, tests, and
  documentation.
- Do not commit real student records, school-specific operational exports,
  SharePoint URLs, tenant IDs, secret filenames that reveal local infrastructure,
  logs, generated business outputs, or private run notes.
- Keep local deployment data in `profile/` or another private repository. Use
  `profile.example/` for public examples.
- Prefer changes that preserve the command contract for `update-state` and
  `deliver-outputs`; public health operators should not need to relearn routine
  workflows for internal refactors.
- Treat validation changes as operational policy changes. Explain the risk being
  controlled, whether the result should hard-fail or warn, and where telemetry is
  recorded.

## Good First Orientation

Start with:

- `README.md` for operator workflows and repository structure.
- `validation-rules.md` for direct validation rule lookup.
- `schema/datasets_v1.0.json` for the maintained source and dataset catalog.
- `AGENTS.md` for concise implementation rules and current module boundaries.
- `profile.example/` for the shape of local configuration and deployment data.
- `testing.md` for the detailed test and acceptance ladder.
- `CODE_OF_CONDUCT.md` for community expectations and conduct reporting.

Use `uv run ...` for repo commands.

Install the repo commit hook with:

```bash
uv run prek install --hook-type pre-commit
```

## Pull Request Checklist

Before opening a pull request:

- Confirm no private files or generated business outputs are tracked:
  `git status --short`.
- Run a sensitive-content check over tracked files. At minimum, search for local
  organization names, SharePoint URLs, tenant identifiers, secrets, access
  tokens, and real client IDs derived from private or generated inputs.
- Run focused tests for the area you touched.
- Run:

```bash
uv run python -m compileall src
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check
uv run pytest
uv run prek run --all-files
git diff --check
```

If workflow behavior changes, update `README.md`. If validation behavior changes,
update `src/panorama_compliance/validation/catalog.py`, regenerate
`validation-rules.md`, and add or update tests that demonstrate the hard-fail or
warning semantics.

## Public Health Unit Adaptations

PHU-specific adaptations should usually live outside shared code:

- local school reference data,
- local workday calendars,
- mounted secret-file names and destinations,
- SharePoint folder URLs,
- local runbooks and approval processes,
- organization-specific branding assets.

Shared code changes are appropriate when they improve this reference workflow,
make validation more rigorous, clarify operator safety, or add a configuration
point that can be used without exposing local data.

## Security And Privacy

If you find a privacy or security issue, do not include sensitive examples in a
public issue. Report the issue using a minimal synthetic reproduction or contact
the maintainers through the repository's configured private security channel.
