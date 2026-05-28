## Summary

<!-- What changed, and why is it needed? -->

## Operational impact

<!-- Describe affected commands, sources, datasets, outputs, or operator steps. -->

- [ ] This change preserves existing runtime contracts, or the migration is
      explained above.
- [ ] Operator-visible behavior is documented in `README.md`, or no update is
      needed.
- [ ] Validation policy changes document hard-fail versus warning behavior,
      evidence location, and affected tests, or no validation policy changed.
- [ ] Dataset registry, versioned schemas, code, and tests remain in sync, or no
      schema changed.

## Privacy and publication safety

- [ ] Examples, fixtures, and screenshots are synthetic or de-identified.
- [ ] No student or client records, real school routing, non-example SharePoint
      URLs, tenant IDs, credentials, mounted secret values, logs, or generated
      business outputs are included.
- [ ] I followed `SECURITY.md` for any security or privacy concern and did not
      place sensitive evidence in this pull request.

## Verification

<!-- List focused checks and acceptance commands, including results. -->

- [ ] Focused tests cover the changed behavior.
- [ ] `uv run python -m compileall src`
- [ ] `uv run ruff check src tests`
- [ ] `uv run ruff format --check src tests`
- [ ] `uv run ty check`
- [ ] `uv run pytest`
- [ ] `uv run prek run --all-files`
- [ ] `git diff --check`
- [ ] `local-acceptance` was run when command behavior changed, or is not
      applicable.

## Collaboration

- [ ] I have read `CONTRIBUTING.md` and will follow `CODE_OF_CONDUCT.md`.
