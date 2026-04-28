from __future__ import annotations

import os
import sys


def has_display() -> bool:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


if __name__ == "__main__":
    if not has_display():
        print("SHTUClaudeProxy GUI requires a display server.")
        print("Use X11 forwarding, for example: ssh -X user@host")
        print("Or use CLI mode, for example:")
        print("  python cli.py show-config")
        print("  python cli.py write-settings")
        print("  python cli.py serve")
        raise SystemExit(2)

    from gui import ProxyApp

    ProxyApp().mainloop()
