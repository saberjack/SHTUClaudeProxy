# Contributing

Thanks for your interest in SHTUClaudeProxy.

## Development

- Use Python 3.10+ on Windows.
- The GUI uses the Python standard library `tkinter`.
- Runtime proxy code intentionally avoids third-party dependencies.
- PyInstaller is only needed for building Windows release packages.

## Local checks

```powershell
python -m py_compile app.py config_store.py gui.py proxy.py
```

## Build

```powershell
.\build_exe.ps1 -InstallDeps
```

## Security

Do not commit:

- `config.json`
- API keys or tokens
- `%APPDATA%\SHTUClaudeProxy\config.json`
- `%USERPROFILE%\.claude\settings.json`
- `build/` or `dist/` output folders

Before opening a pull request, run a secret scan or at least search for your API key manually.

