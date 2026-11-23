from pathlib import Path

import pytest

from whaat.platform import paths


def test_the_state_dir_is_where_the_system_keeps_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    found = {}
    for kind in ("macos", "linux", "wsl", "windows"):
        monkeypatch.setattr(paths, "system", lambda kind=kind: kind)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        found[kind] = paths.state_dir("-dev")
    monkeypatch.setattr(paths, "system", lambda: "windows")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    appdata = paths.state_dir()
    monkeypatch.setattr(paths, "system", lambda: "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    xdg = paths.state_dir()
    monkeypatch.setenv("XDG_DATA_HOME", "relative/ignored")
    relative = paths.state_dir()

    assert found == {
        "macos": tmp_path / "Library/Application Support/whaat-dev",
        "linux": tmp_path / ".local/share/whaat-dev",
        "wsl": tmp_path / ".local/share/whaat-dev",
        "windows": tmp_path / "AppData/Roaming/whaat-dev",
    }
    assert (xdg, relative, appdata) == (
        tmp_path / "xdg/whaat",
        tmp_path / ".local/share/whaat",
        tmp_path / "Roaming/whaat",
    )


def test_a_new_state_dir_is_the_owner_s_only_and_an_existing_one_is_left_as_it_is(tmp_path: Path) -> None:
    new, existing = tmp_path / "a" / "whaat", tmp_path / "old"
    existing.mkdir(mode=0o755)
    existing.chmod(0o755)

    paths.make_state_dir(new)
    paths.make_state_dir(existing)

    assert (new.stat().st_mode & 0o777, existing.stat().st_mode & 0o777) == (0o700, 0o755)
