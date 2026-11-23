import os
from pathlib import Path

from whaat.platform.system import system

APP_NAME = "whaat"


def state_dir(instance_suffix: str = "") -> Path:
    name = f"{APP_NAME}{instance_suffix}"
    match system():
        case "macos":
            return Path.home() / "Library" / "Application Support" / name
        case "windows":
            return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / name
        case _:
            xdg = os.environ.get("XDG_DATA_HOME", "")
            return (Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "share") / name


def make_state_dir(folder: Path) -> None:
    """A new state folder is the owner's only: under `~/.local/share` other users could otherwise read its log and
    list its identities, where on macOS `~/Library` already kept them out."""
    if not folder.exists():
        folder.mkdir(parents=True)
        folder.chmod(0o700)
