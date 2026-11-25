"""The line the page shows for the user to paste into a terminal of their own: it starts the identity's agent with a
first message, in the shell this machine has (PowerShell on Windows, a POSIX shell elsewhere)."""

import shlex
from pathlib import Path

from whaat.agent import Launch
from whaat.platform.system import system


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _powershell(launch: Launch, prompt: str, cwd: Path | None) -> str:
    """`$env:` holds for the rest of the window, so the line puts the earlier values back when claude ends; a folder
    that is missing stops the line before claude starts."""
    parts = [f"Set-Location -LiteralPath {_ps(str(cwd))} -ErrorAction Stop"] if cwd else []
    keep = [f"$whaat_{key}=$env:{key}" for key in launch.env]
    assignments = [f"$env:{key}={_ps(value)}" for key, value in launch.env.items()]
    back = "; ".join(f"$env:{key}=$whaat_{key}" for key in launch.env)
    run = " ".join([launch.argv[0], *map(_ps, [*launch.argv[1:], prompt])])
    return "; ".join([*parts, *keep, *assignments, f"try {{ {run} }} finally {{ {back} }}"])


def start_line(launch: Launch, prompt: str, cwd: Path | None = None, powershell: bool | None = None) -> str:
    """`launch` is the identity's agent config: its config dir and whaat's plugin."""
    if system() == "windows" if powershell is None else powershell:
        return _powershell(launch, prompt, cwd)
    parts = [f"cd {shlex.quote(str(cwd))}"] if cwd else []
    assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in launch.env.items())
    parts.append(f"{assignments + ' ' if assignments else ''}{shlex.join([*launch.argv, prompt])}")
    return " && ".join(parts)
