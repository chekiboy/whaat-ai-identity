import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

HOOK = Path(__file__).resolve().parents[2] / "connectors" / "claude_code" / "hooks" / "whaat_hook.py"


def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("whaat_hook", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_hook_starts_the_server_through_uv_not_the_bash_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    module = hook()
    ran: list[list[str]] = []

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", run)

    assert module.ensure_server() is True
    assert ran == [["uv", "run", "--quiet", "--project", module.SERVER, "whaat", "ensure"]]
    assert (Path(module.SERVER) / "pyproject.toml").is_file()


@pytest.mark.parametrize(("windows", "expected"), [(False, "org/repo"), (True, None)])
def test_the_hook_reads_a_drive_path_as_a_local_folder_only_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, windows: bool, expected: str | None
) -> None:
    module = hook()
    monkeypatch.setattr(module, "WINDOWS", windows)

    assert module._remote_path("x:/org/repo.git", str(tmp_path)) == expected
