#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VERSION="$(tr -d '\r\n' < VERSION 2>/dev/null || echo dev)"
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_NAME="$(uname -m)"
APP_NAME="SHTUClaudeProxy-v${VERSION}-${OS_NAME}-${ARCH_NAME}"

INSTALL_DEPS=0
ONE_DIR_ONLY=0
ONE_FILE_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --install-deps) INSTALL_DEPS=1 ;;
    --onedir-only) ONE_DIR_ONLY=1 ;;
    --onefile-only) ONE_FILE_ONLY=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$INSTALL_DEPS" == "1" ]]; then
  python3 -m pip install --upgrade pip
  python3 -m pip install pyinstaller
fi

mkdir -p release

if [[ "$ONE_FILE_ONLY" != "1" ]]; then
  python3 -m PyInstaller \
    --noconfirm \
    --clean \
    --name SHTUClaudeProxy \
    --add-data "proxy.py:." \
    --add-data "config_store.py:." \
    app.py

  tar -czf "release/SHTUClaudeProxy-${OS_NAME}-${ARCH_NAME}.tar.gz" -C dist SHTUClaudeProxy
  echo "Folder package complete: release/SHTUClaudeProxy-${OS_NAME}-${ARCH_NAME}.tar.gz"
fi

if [[ "$ONE_DIR_ONLY" != "1" ]]; then
  python3 -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --name "$APP_NAME" \
    --add-data "proxy.py:." \
    --add-data "config_store.py:." \
    app.py

  cp "dist/$APP_NAME" "release/$APP_NAME"
  echo "Single-file build complete: release/$APP_NAME"
fi

echo "Build complete. Release files are in: $ROOT/release"
