"""Status lines in the Battlestation style: `[GOOD]`, `[WARN]`, `[ERRO]`, `[INFO]`.

Only the four-letter code is coloured (green, yellow, red, cyan). Colour is off when the stream is not a
terminal or NO_COLOR is set, and can be forced with FORCE_COLOR. Status goes to stderr by default so the
Beancount that `process --dry-run` prints on stdout stays clean.
"""

from __future__ import annotations

import os
import sys

COLOURS = {"GOOD": "32", "WARN": "33", "ERRO": "31", "INFO": "36"}
INDENT = " " * 4
_vt_enabled = False


def _enable_windows_vt() -> None:
    """Old Windows consoles need virtual-terminal processing switched on for ANSI colours."""
    global _vt_enabled
    if _vt_enabled or os.name != "nt":
        return
    _vt_enabled = True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for std in (-11, -12):  # stdout, stderr
            handle = kernel32.GetStdHandle(std)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # colour is cosmetic; never fail because of it
        pass


def use_colour(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def code(name: str, stream=None) -> str:
    """``[GOOD] `` etc., with the code coloured when the stream supports it."""
    stream = stream or sys.stderr
    if use_colour(stream):
        _enable_windows_vt()
        return f"[\x1b[{COLOURS[name]}m{name}\x1b[0m] "
    return f"[{name}] "


def _line(name: str, message: str, indent: int, file) -> None:
    file = file or sys.stderr
    print(f"{INDENT * indent}{code(name, file)}{message}", file=file)


def good(message: str, indent: int = 0, file=None) -> None:
    """Something worked."""
    _line("GOOD", message, indent, file)


def warn(message: str, indent: int = 0, file=None) -> None:
    """Something needs a look."""
    _line("WARN", message, indent, file)


def error(message: str, indent: int = 0, file=None) -> None:
    """Something failed."""
    _line("ERRO", message, indent, file)


def info(message: str, indent: int = 0, file=None) -> None:
    """Something neutral."""
    _line("INFO", message, indent, file)
