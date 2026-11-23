"""The line the page shows for the user to paste into a terminal of their own: it starts the identity's agent with a
first message, in the shell this machine has (PowerShell on Windows, a POSIX shell elsewhere)."""

import shlex
from pathlib import Path

from whaat.agent import Launch
from whaat.platform.system import windows


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def start_line(launch: Launch, prompt: str, cwd: Path | None = None, powershell: bool | None = None) -> str:
    """`launch` is the identity's agent config: its config dir and whaat's plugin."""
    if windows() if powershell is None else powershell:
        parts = [f"Set-Location {_ps(str(cwd))}"] if cwd else []
        parts += [f"$env:{key}={_ps(value)}" for key, value in launch.env.items()]
        return "; ".join([*parts, f"{launch.command} {_ps(prompt)}"])
    parts = [f"cd {shlex.quote(str(cwd))}"] if cwd else []
    assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in launch.env.items())
    parts.append(f"{assignments + ' ' if assignments else ''}{launch.command} {shlex.quote(prompt)}")
    return " && ".join(parts)
