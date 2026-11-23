import os
import shutil
import subprocess
from pathlib import Path

from whaat.platform.system import system

# Browsers that open a page as an app window (no tabs, no address bar) with --app; the first one found is used.
APP_BROWSER_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
APP_BROWSER_COMMANDS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
)


def _detached(command: list[str]) -> None:
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def open_url(url: str, browser: str | None = None) -> None:
    """`browser` is an app name on macOS and a command elsewhere. Off macOS the opener may stay in the foreground
    until the browser closes, so it runs detached."""
    kind = system()
    if kind == "macos":
        subprocess.run(["open", *(["-a", browser] if browser else []), url], check=True)
    elif browser:
        _detached([browser, url])
    elif kind == "windows":
        getattr(os, "startfile")(url)  # noqa: B009 - os.startfile exists only on Windows
    else:
        opener = shutil.which("wslview") if kind == "wsl" else None
        _detached([opener or "xdg-open", url])


def app_browser() -> str | None:
    for path in APP_BROWSER_PATHS if system() == "macos" else ():
        if Path(path).exists():
            return path
    for command in APP_BROWSER_COMMANDS:
        found = shutil.which(command)
        if found:
            return found
    return None


def app_window_command(browser: str, url: str, profile: Path) -> list[str]:
    """The page in a window of its own, with a profile of its own so it never touches the user's browser session."""
    return [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1600,1000",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def open_app_window(url: str, profile: Path) -> bool:
    """Open `url` as an app window; False when no browser that can do it is installed."""
    browser = app_browser()
    if browser is None:
        return False
    _detached(app_window_command(browser, url, profile))
    return True
