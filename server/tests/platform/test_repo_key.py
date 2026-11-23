from pathlib import Path

import pytest

from whaat.platform import repo_key


@pytest.mark.parametrize(
    ("system", "url", "expected"),
    [
        ("linux", "x:/org/repo.git", "org/repo"),
        ("macos", "C:/repos/x", "repos/x"),
        ("windows", "x:/org/repo.git", None),
        ("windows", "C:\\repos\\x", None),
        ("windows", "git@github.com:acme/web.git", "acme/web"),
    ],
)
def test_a_drive_path_is_a_local_folder_only_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, system: str, url: str, expected: str | None
) -> None:
    monkeypatch.setattr(repo_key, "system", lambda: system)

    assert repo_key.remote_path(url, tmp_path) == expected
