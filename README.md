# SHTUClaudeProxy

SHTUClaudeProxy is a Windows desktop proxy for connecting **Claude Code** to the ShanghaiTech University campus **GenAI Response API**.

This tool was created by **sunyb, ShanghaiTech University Library and Information Center** for internal campus use. It helps users access Claude Code through the university GenAI Response API by translating Claude Code's Anthropic Messages API traffic into an OpenAI Responses-style upstream request and converting streaming responses back into Claude Code-compatible Server-Sent Events.

> 中文简介：SHTUClaudeProxy 是上海科技大学图书信息中心 sunyb 制作的 Windows 图形化本地代理工具，供校内 GenAI Response API 接入 Claude Code 使用。

## What It Does

Claude Code expects an Anthropic-compatible API endpoint such as:

```text
POST /v1/messages
```

ShanghaiTech GenAI Response API returns OpenAI Responses-style streaming events such as:

```text
event: response.output_text.delta
```

SHTUClaudeProxy bridges the two formats:

```text
Claude Code
  -> Anthropic Messages request
  -> SHTUClaudeProxy on 127.0.0.1:8082
  -> GenAI Response API
  -> OpenAI Responses SSE
  -> Anthropic-style SSE
  -> Claude Code
```

## Features

- Windows GUI; no command-line environment setup required.
- Local Anthropic-compatible endpoint for Claude Code.
- Multiple model configurations.
- Per-model settings:
  - display name
  - Claude Code model ID
  - GenAI Response API base URL
  - API key
  - upstream model ID
- One-click writing of Claude Code `settings.json`.
- Auto-detection of npm-installed Claude Code.
- Portable across Windows user accounts and machines.
- PyInstaller build script for Windows release packaging.

## Intended Audience

This project is intended for ShanghaiTech University users who have access to the campus GenAI Response API and want to use that API from Claude Code.

It is not an official Anthropic product, not an OpenAI product, and not a general-purpose full Anthropic API emulator.

## Important Limitations

This project currently focuses on text streaming compatibility.

Known limitations:

- Tool calls are only partially represented and are not fully translated between Anthropic `tool_use` and OpenAI Responses tool calls.
- Token usage fields are approximate.
- Images are best-effort only.
- Very complex Claude Code workflows may need more complete tool-call translation.

For normal conversational and many coding-assistance workflows, the proxy can be sufficient. For advanced autonomous coding workflows, additional protocol translation may be required.

## Repository Layout

```text
.
├── app.py                 # GUI entry point
├── gui.py                 # Tkinter desktop UI
├── proxy.py               # Anthropic Messages <-> Responses proxy
├── config_store.py        # Config loading, defaults, path portability
├── config.example.json    # Safe example config without API key
├── build_exe.ps1          # Windows build script
├── build_exe.bat          # Double-click build helper
├── requirements-build.txt # Build-time dependency list
├── LICENSE
├── SECURITY.md
└── CONTRIBUTING.md
```

## Requirements

### Runtime

- Windows 10/11 or Windows Server with desktop UI support.
- Claude Code installed through npm or another method.
- Access to ShanghaiTech GenAI Response API.
- A valid GenAI Response API key.

The built executable bundles Python runtime files via PyInstaller.

### Development / Build

- Python 3.10+
- PyInstaller

Install build dependency:

```powershell
python -m pip install -r requirements-build.txt
```

## Quick Start for End Users

### 1. Install Claude Code

If Claude Code is installed with npm, the default executable is usually:

```text
%APPDATA%\npm\claude.cmd
```

The GUI tries to detect this automatically.

### 2. Start SHTUClaudeProxy

Run:

```text
SHTUClaudeProxy.exe
```

### 3. Configure Server Settings

Default values:

```text
Host: 127.0.0.1
Port: 8082
Claude Settings Path: %USERPROFILE%\.claude\settings.json
Claude Code Path: %APPDATA%\npm\claude.cmd
```

You can change these if your environment is different.

### 4. Configure a Model

For each model entry:

| Field | Meaning | Example |
| --- | --- | --- |
| Display Name | Friendly name shown in the GUI | ShanghaiTech GPT-5.5 |
| Model ID for Claude Code | Model name Claude Code will request | GPT-5.5 |
| Responses Base URL | Campus GenAI Response API endpoint | https://genaiapi.shanghaitech.edu.cn/api/v1/response |
| API Key | Your campus API key | keep private |
| Upstream Model | Model ID sent to GenAI Response API | GPT-5.5 |

Click:

```text
Apply Model Changes
Save Config
```

### 5. Write Claude Code Settings

Click:

```text
Write Claude Settings
```

The app updates your Claude Code settings file, usually:

```text
%USERPROFILE%\.claude\settings.json
```

It writes an `env` block like:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8082",
    "ANTHROPIC_MODEL": "GPT-5.5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "GPT-5.5",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "GPT-5.5",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "GPT-5.5",
    "ANTHROPIC_REASONING_MODEL": "GPT-5.5",
    "ANTHROPIC_AUTH_TOKEN": "local-proxy"
  },
  "includeCoAuthoredBy": false
}
```

`ANTHROPIC_AUTH_TOKEN` is only a local placeholder for Claude Code. The real upstream API key is stored in SHTUClaudeProxy's local app config and is used only by the proxy when forwarding requests to GenAI Response API.

### 6. Start Proxy

Click:

```text
Start Proxy
```

Expected status:

```text
Running on http://127.0.0.1:8082
```

### 7. Start Claude Code

You can either:

- click `Launch Claude Code` in the GUI, or
- start Claude Code manually after writing settings.

If starting manually, make sure the proxy is already running.

## Multiple Models

You can add multiple model routes.

Example:

| Model ID for Claude Code | Upstream Model | Base URL |
| --- | --- | --- |
| GPT-5.5 | GPT-5.5 | https://genaiapi.shanghaitech.edu.cn/api/v1/response |
| GPT-5.5-fast | GPT-5.5 | another compatible endpoint |
| GPT-5.5-reasoning | GPT-5.5 | another compatible endpoint |

Claude Code selects a route by the model ID it sends. The proxy then forwards to the configured upstream `base_url`, `api_key`, and `upstream_model`.

## Configuration Files

### App Config

Stored locally at:

```text
%APPDATA%\SHTUClaudeProxy\config.json
```

This file may contain your API key in plaintext. Do not commit it.

### Claude Code Settings

Usually stored at:

```text
%USERPROFILE%\.claude\settings.json
```

The GUI writes only the `env` fields needed by Claude Code and preserves other JSON fields when possible.

## Build from Source

Clone the repository and run:

```powershell
python -m pip install -r requirements-build.txt
.\build_exe.ps1
```

Or install PyInstaller automatically:

```powershell
.\build_exe.ps1 -InstallDeps
```

Output:

```text
dist\SHTUClaudeProxy\SHTUClaudeProxy.exe
```

The app is packaged as a portable folder. Distribute the whole folder:

```text
dist\SHTUClaudeProxy
```

Do not distribute only the `.exe` file, because the `_internal` runtime folder is required.

## Run from Source

```powershell
python .\gui.py
```

Run proxy only:

```powershell
python .\proxy.py --host 127.0.0.1 --port 8082
```

## Direct API Smoke Test

After starting the proxy:

```powershell
$body = @{
  model = "GPT-5.5"
  max_tokens = 100
  stream = $true
  messages = @(@{ role = "user"; content = "hi" })
} | ConvertTo-Json -Depth 10

Invoke-WebRequest -UseBasicParsing `
  -Uri http://127.0.0.1:8082/v1/messages?beta=true `
  -Method POST `
  -ContentType "application/json" `
  -Headers @{ "anthropic-version" = "2023-06-01"; "x-api-key" = "local-proxy" } `
  -Body $body
```

Expected SSE events include:

```text
event: message_start
event: content_block_start
event: content_block_delta
event: message_delta
event: message_stop
```

## Troubleshooting

### Claude Code: `ConnectionRefused`

Cause: Claude Code is pointing to `http://127.0.0.1:8082`, but the local proxy is not running.

Fix:

1. Open SHTUClaudeProxy.
2. Click `Start Proxy`.
3. Confirm status shows `Running on http://127.0.0.1:8082`.
4. Restart Claude Code.

### Claude Code Still Uses an Old Port

Check:

```text
%USERPROFILE%\.claude\settings.json
```

Make sure `ANTHROPIC_BASE_URL` is:

```text
http://127.0.0.1:8082
```

If not, click `Write Claude Settings` again.

### Claude Code Says Model Does Not Exist

Usually this means the proxy returned an error before reaching upstream.

Check:

- model ID in Claude Code matches `Model ID for Claude Code`
- API key is configured
- upstream model is valid for GenAI Response API
- proxy logs in the GUI

### Response Hangs After First Message

Use the latest version. Older builds used keep-alive SSE behavior that could cause Claude Code to wait for the connection to close.

### API Key Safety

Never paste your API key into GitHub issues. The API key is stored locally in:

```text
%APPDATA%\SHTUClaudeProxy\config.json
```

## Publishing Checklist

Before publishing or creating a release, make sure you do not commit:

```text
config.json
build/
dist/
*.spec
__pycache__/
%APPDATA%\SHTUClaudeProxy\config.json
%USERPROFILE%\.claude\settings.json
```

Run a quick scan for keys before pushing.

## Credits

Created by **sunyb**, ShanghaiTech University Library and Information Center.

Purpose: provide a convenient local bridge for ShanghaiTech campus GenAI Response API access from Claude Code.

## License

MIT License. See `LICENSE`.

