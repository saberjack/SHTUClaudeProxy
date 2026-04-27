# Security Policy

## Reporting a Vulnerability

If you discover a security issue, please report it privately to the ShanghaiTech University Library and Information Center maintainer instead of opening a public issue.

## Sensitive Data

SHTUClaudeProxy never ships with an API key. Users must provide their own GenAI Response API credentials locally.

Do not share:

- GenAI Response API keys
- Claude Code `settings.json` containing private tokens
- `%APPDATA%\SHTUClaudeProxy\config.json`

## Local Storage

The GUI stores local model configuration in:

```text
%APPDATA%\SHTUClaudeProxy\config.json
```

API keys are stored in this local JSON file in plaintext. Use appropriate device security controls and do not sync this file to GitHub.

