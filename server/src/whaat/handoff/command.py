"""The line the page shows for the user to paste into a terminal of their own: it starts the identity's agent with a
first message, in the shell this machine has (PowerShell on Windows, a POSIX shell elsewhere)."""

import shlex
import sys
from pathlib import Path

from whaat.terminal.agent import Launch


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def start_line(
    launch: Launch | None, command: str, prompt: str, cwd: Path | None = None, windows: bool | None = None
) -> str:
    """`launch` is the identity's agent config (its config dir and whaat's plugin); without one the plain command
    runs, as in a folder `whaat connect` set up."""
    windows = sys.platform == "win32" if windows is None else windows
    run = launch.command if launch else command
    env = launch.env if launch else {}
    if windows:
        parts = [f"Set-Location {_ps(str(cwd))}"] if cwd else []
        parts += [f"$env:{key}={_ps(value)}" for key, value in env.items()]
        return "; ".join([*parts, f"{run} {_ps(prompt)}"])
    parts = [f"cd {shlex.quote(str(cwd))}"] if cwd else []
    assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
    parts.append(f"{assignments + ' ' if assignments else ''}{run} {shlex.quote(prompt)}")
    return " && ".join(parts)
