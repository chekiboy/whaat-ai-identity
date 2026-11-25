from pathlib import Path

import pytest

from whaat.platform import browser


def test_the_app_window_opens_the_page_without_browser_chrome_in_a_profile_of_its_own(tmp_path: Path) -> None:
    command = browser.app_window_command("/bin/chrome", "http://whaat.localhost:1111/ui/", tmp_path / "app-window")

    assert command[0] == "/bin/chrome"
    assert "--app=http://whaat.localhost:1111/ui/" in command
    assert f"--user-data-dir={tmp_path / 'app-window'}" in command


def test_the_first_installed_app_browser_is_used_and_none_when_there_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chromium = tmp_path / "Chromium"
    chromium.touch()
    monkeypatch.setattr(browser, "system", lambda: "macos")
    monkeypatch.setattr(browser, "APP_BROWSER_PATHS", (str(tmp_path / "Chrome"), str(chromium)))
    monkeypatch.setattr(browser.shutil, "which", lambda _: None)
    found = browser.app_browser()
    monkeypatch.setattr(browser, "APP_BROWSER_PATHS", ())

    assert found == str(chromium)
    assert browser.app_browser() is None


@pytest.mark.parametrize(
    ("system", "named", "wslview", "waits", "expected"),
    [
        ("macos", None, None, True, ["open", "http://x/"]),
        ("macos", "Firefox", None, True, ["open", "-a", "Firefox", "http://x/"]),
        ("linux", None, None, False, ["xdg-open", "http://x/"]),
        ("linux", "firefox", None, False, ["firefox", "http://x/"]),
        ("wsl", None, "/usr/bin/wslview", False, ["/usr/bin/wslview", "http://x/"]),
        ("wsl", None, None, False, ["xdg-open", "http://x/"]),
    ],
)
def test_a_link_opens_with_the_system_s_own_opener_and_waits_only_for_macos_open(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    named: str | None,
    wslview: str | None,
    waits: bool,
    expected: list[str],
) -> None:
    ran: list[tuple[bool, list[str]]] = []
    monkeypatch.setattr(browser, "system", lambda: system)
    monkeypatch.setattr("whaat.platform.browser.shutil.which", lambda name: wslview if name == "wslview" else None)
    monkeypatch.setattr("whaat.platform.browser.subprocess.run", lambda command, check: ran.append((True, command)))
    monkeypatch.setattr("whaat.platform.browser.subprocess.Popen", lambda command, **_: ran.append((False, command)))

    browser.open_url("http://x/", named)

    assert ran == [(waits, expected)]


def test_on_windows_the_link_goes_to_the_file_association(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(browser, "system", lambda: "windows")
    monkeypatch.setattr("os.startfile", opened.append, raising=False)

    browser.open_url("http://x/")

    assert opened == ["http://x/"]


def test_the_macos_app_bundles_are_looked_for_only_on_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chrome = tmp_path / "Chrome"
    chrome.touch()
    monkeypatch.setattr(browser, "APP_BROWSER_PATHS", (str(chrome),))
    monkeypatch.setattr("whaat.platform.browser.shutil.which", lambda _: None)
    monkeypatch.setattr(browser, "system", lambda: "linux")

    assert browser.app_browser() is None
