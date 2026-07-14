# profile.example

Demonstration scaffold for local deployment data. Initialize it from the
repository root with:

```bash
cp -R profile.example profile
```

This folder shows the expected top-level shape for environment-specific runtime data:

- `school_reference.json`
- `workdays.csv` (demonstration calendar only; replace before operational use)
- `logo.pdf`
- `privacy_notice.typ` (Typst body content injected into report footer `#text[...]`)
- `config.yaml` (default runtime config; relative paths resolve from `profile/`)

Rules:

- Replace every demonstration value with locally reviewed configuration.
- The included `workdays.csv` is intentionally incomplete and is not an
  authoritative Ontario or WDGPH calendar. Replace it with a reviewed local
  calendar covering every operational date and holiday before running the
  workflow.
- Keep credentials/secrets out of this profile repo.
- Treat `school_reference.json` as the source of truth for runtime wave/level/school metadata.
- Use `profile/config.yaml` as the runtime entrypoint (default CLI config path).
