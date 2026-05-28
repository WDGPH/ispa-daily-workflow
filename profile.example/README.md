# profile.example

Scaffold for the private `profile/` deployment-data submodule.

This folder shows the expected top-level shape for environment-specific runtime data:

- `school_reference.json`
- `workdays.csv` (or year-specific files under `workdays/`)
- `logo.pdf`
- `privacy_notice.typ` (Typst body content injected into report footer `#text[...]`)
- `config.yaml` (example **root** config template that points to `profile/...` paths)

Rules:

- Keep credentials/secrets out of this profile repo.
- Treat `school_reference.json` as the source of truth for runtime wave/level/school metadata.
- Use `profile/config.yaml` as the runtime entrypoint (default CLI config path).
- Initialize/update submodule content with:
  - `git submodule update --init --recursive`
