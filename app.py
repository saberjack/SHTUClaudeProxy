from __future__ import annotations

import os
import sys


def has_display() -> bool:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        from cli import main

        raise SystemExit(main(sys.argv[1:]))

    if not has_display():
        print("SHTUClaudeProxy GUI requires a display server.")
        print("Use X11 forwarding, for example: ssh -X user@host")
        print("Or use CLI mode, for example:")
        print("  SHTUCodeProxy status")
        print("  SHTUCodeProxy configure-model --model-id MODEL --api-key KEY --upstream-model MODEL --default --codex")
        print("  SHTUCodeProxy start")
        raise SystemExit(2)

    from pyqt_gui import run

    raise SystemExit(run())
