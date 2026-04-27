# Changelog

## v1.5.0 - 2026-04-27

Stable guided-setup release.

### Added

- Guided quick-start GUI with `Save Config`, `Write Claude Settings`, and `Start Proxy + Launch Claude` steps.
- Full-window vertical scrolling and larger default window for smaller displays.
- Per-role Claude model routing for:
  - `ANTHROPIC_MODEL`
  - `ANTHROPIC_DEFAULT_HAIKU_MODEL`
  - `ANTHROPIC_DEFAULT_SONNET_MODEL`
  - `ANTHROPIC_DEFAULT_OPUS_MODEL`
  - `ANTHROPIC_REASONING_MODEL`
- Effective model-routing summary in the GUI.
- `model_env` configuration block in `config.example.json`.
- Chat Completions upstream URL normalization.

### Changed

- Reworked the GUI layout to prioritize the first-time setup flow.
- Moved advanced actions into a separate optional section.
- Improved non-streaming and streaming upstream error reporting.
- Updated the release zip with the latest Windows build.
