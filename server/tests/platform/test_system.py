import platform as stdlib_platform
import sys

import pytest

from whaat.platform import system


@pytest.mark.parametrize(
    ("platform", "release", "distro", "expected"),
    [
        ("darwin", "24.0.0", None, "macos"),
        ("win32", "10", None, "windows"),
        ("linux", "6.8.0-45-generic", None, "linux"),
        ("linux", "5.15.167.4-microsoft-standard-WSL2", None, "wsl"),
        ("linux", "6.8.0", "Ubuntu", "wsl"),
        ("linux", "4.4.0-19041-Microsoft", None, "wsl"),
    ],
)
def test_the_system_is_read_from_the_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, release: str, distro: str | None, expected: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(stdlib_platform, "uname", lambda: type("U", (), {"release": release})())
    if distro:
        monkeypatch.setenv("WSL_DISTRO_NAME", distro)
    else:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

    assert system.system() == expected
