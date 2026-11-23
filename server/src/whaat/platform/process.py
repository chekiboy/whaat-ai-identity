import subprocess
from typing import IO, Any

from whaat.platform.system import system

# Windows has no sessions: a process outlives its starter, without a console, through these creation flags
WINDOWS_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def detach_options() -> dict[str, Any]:
    """The Popen arguments that let a started process run on after the one that started it ends."""
    return {"creationflags": WINDOWS_DETACHED} if system() == "windows" else {"start_new_session": True}


def spawn_detached(args: list[str], log: IO[bytes]) -> None:
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **detach_options())
