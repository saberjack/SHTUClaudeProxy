# Changelog

## v2.0.0 - 2026-04-30

Tool-call hardening release for Claude Code compatibility.

### Added

- Broader smoke-test coverage for multiple tool calls, cumulative streamed arguments, model suffix routing, and tool argument repair.
- Estimated `/count_tokens` responses instead of a fixed zero count.

### Changed

- Hardened Chat Completions and Responses tool-call parsing for streamed and non-streamed upstream responses.
- Improved `tool_result` ordering and visible fallback context for Chat Completions-compatible upstreams.
- Claude model routing now accepts common date-suffixed model IDs.
- GPT-series models are documented to use the `responses` API Format.

### Fixed

- Chat Completions responses that include both `content` and `tool_calls` now prioritize tool calls instead of dropping them.
- Tool arguments wrapped in JSON strings, markdown fences, thinking tags, or cumulative streamed snapshots are repaired more reliably.
- Multiple tool calls in one upstream chunk are no longer dropped.

## v1.9.0 - 2026-04-28

Claude Code tool-call compatibility release.

### Added

- Bidirectional tool-call translation between Anthropic `tool_use/tool_result` and upstream Chat Completions `tool_calls`.
- Bidirectional tool-call translation between Anthropic `tool_use/tool_result` and upstream Responses `function_call/function_call_output`.
- Streaming conversion from upstream tool-call events into Anthropic-style `tool_use` content blocks.
- Smoke-test coverage for tool schema conversion, tool history conversion, streamed tool-call deltas, and `stop_reason: tool_use`.

### Changed

- Tool schemas are now sent as real upstream tools instead of text-only context notes.
- Tool results are now preserved as structured tool outputs instead of plain text fallbacks.
## v1.8.0 - 2026-04-28

Default API format and Base URL update.

### Changed

- Renamed GUI field `Responses Base URL` to `Base URL`.
- Changed default API Format to `chat_completions`.
- Changed default Base URL to `https://genaiapi.shanghaitech.edu.cn/api/v1/start`.
- API Format selection now automatically updates Base URL:
  - `chat_completions` -> `https://genaiapi.shanghaitech.edu.cn/api/v1/start`
  - `responses` -> `https://genaiapi.shanghaitech.edu.cn/api/v1/response`
- Added GUI hint text listing valid API Format options.
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
