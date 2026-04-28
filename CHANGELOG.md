# Changelog

## v1.7.0 - 2026-04-28

Cross-platform source release for Linux and macOS.

### Added

- Linux/macOS source package: `SHTUClaudeProxy-v1.7.0-source-linux-macos.zip`.
- Headless CLI mode with `show-config`, `print-env`, `write-settings`, `install-launch-script`, and `serve` commands.
- Cross-platform path, launch script, and Claude launch helpers.
- X11 forwarding documentation for Linux GUI use.
- Smoke test script for Linux/macOS validation.

### Changed

- GUI text is now English-only to avoid missing Chinese font rendering on Linux.
- Windows v1.6.0 binaries are not rebuilt for this release.
## v1.6.0 - 2026-04-27

Zero-install release focused on ordinary end users.

### Added

- Single-file Windows EXE build: `SHTUClaudeProxy-v1.6.0-windows-x64.exe`.
- Build script support for both one-file and portable-folder packages.
- First-run setup tip explaining that no Python installation is required for release builds.
- One-click `Save + Connect + Launch` path for common first-time setup.

### Changed

- Release packaging now produces both a single-file EXE and the existing portable zip.
- README now recommends the single-file EXE for normal users and the zip for troubleshooting.
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



