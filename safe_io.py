from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


def powershell_copy_text(source: Path, target: Path) -> None:
    script = source.with_name(f".{target.name}.copy.ps1")
    script.write_text(
        "param([string]$src,[string]$dst)\n"
        "$parent=Split-Path -Parent $dst\n"
        "if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }\n"
        "$content=Get-Content -LiteralPath $src -Raw -Encoding UTF8\n"
        "Set-Content -LiteralPath $dst -Value $content -Encoding UTF8 -Force\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(source), str(target)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        script.unlink()
    except OSError:
        pass
    if result.returncode != 0:
        raise PermissionError(result.stderr.strip() or result.stdout.strip() or f"Could not write {target}")


def backup_existing_file(target: Path) -> Optional[Path]:
    if not target.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = target.with_name(f"{target.name}.bak_{timestamp}")
    data = target.read_bytes()
    try:
        backup.write_bytes(data)
        return backup
    except PermissionError:
        fallback_dir = Path(__file__).resolve().parent / "backups"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback = fallback_dir / f"{target.name}.bak_{timestamp}"
        fallback.write_bytes(data)
        return fallback


def atomic_write_text(
    target: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    validate: Optional[Callable[[str], None]] = None,
    backup: bool = True,
) -> Optional[Path]:
    if validate:
        validate(text)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            if target.read_text(encoding=encoding) == text:
                return None
        except UnicodeDecodeError:
            pass
    backup_path = backup_existing_file(target) if backup else None
    temp = target.with_name(f".{target.name}.tmp")
    try:
        try:
            temp.write_text(text, encoding=encoding)
        except PermissionError:
            fallback_dir = Path(__file__).resolve().parent / "backups"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            temp = fallback_dir / f".{target.name}.tmp"
            temp.write_text(text, encoding=encoding)
        if validate:
            validate(temp.read_text(encoding=encoding))
        try:
            temp.replace(target)
        except PermissionError:
            try:
                shutil.copy2(temp, target)
            except PermissionError:
                if target.drive or str(target).startswith("\\\\"):
                    powershell_copy_text(temp, target)
                else:
                    raise
    finally:
        if temp.exists():
            temp.unlink()
    return backup_path
