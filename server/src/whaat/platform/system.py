"""Which system the server runs on, read from the platform itself; the rest of whaat asks here and nowhere else."""

import os
import platform
import sys
from typing import Literal

System = Literal["macos", "linux", "wsl", "windows"]


def system() -> System:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    # a WSL2 kernel reports e.g. 5.15.167.4-microsoft-standard-WSL2, WSL1 4.4.0-19041-Microsoft
    if os.environ.get("WSL_DISTRO_NAME") or "microsoft" in platform.uname().release.lower():
        return "wsl"
    return "linux"
