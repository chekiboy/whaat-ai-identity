from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import whaat.cli.main as cli
from whaat.cli.main import ForeignInstanceError, _open_or_say, running_instance
from whaat.config import Settings


@pytest.fixture
def dev(settings: Settings) -> Settings:
    from dataclasses import replace

    return replace(settings, instance="dev")


def test_nothing_answering_means_start_one(dev: Settings) -> None:
    assert running_instance(dev, None) is False


def test_our_instance_answering_is_used(dev: Settings) -> None:
    assert running_instance(dev, {"app": "whaat", "instance": "dev"}) is True


@pytest.mark.parametrize("health", [{"app": "whaat", "instance": "live"}, {"app": "whaat"}])
def test_another_or_an_unnamed_instance_is_refused(dev: Settings, health: dict[str, object]) -> None:
    with pytest.raises(ForeignInstanceError, match="refusing"):
        running_instance(dev, health)


def test_without_a_browser_to_open_the_address_is_printed_for_the_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_opener(url: str, browser: str | None) -> None:
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr("whaat.cli.main.open_url", no_opener)

    with pytest.raises(typer.Exit):
        _open_or_say("http://whaat.localhost:1111/ui/reports/abc", None)

    out = capsys.readouterr()
    assert out.out.strip() == "http://whaat.localhost:1111/ui/reports/abc"
    assert "could not open a browser" in out.err


def test_the_state_dir_command_prints_the_instance_s_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WHAAT_STATE_DIR", str(tmp_path / "state"))

    result = CliRunner().invoke(cli.app, ["state-dir"])

    assert (result.exit_code, result.stdout.strip()) == (0, str(tmp_path / "state"))


def test_a_server_out_of_reach_that_cannot_be_started_here_says_how_to_allow_it(
    dev: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_write(folder: Path) -> None:
        raise OSError(30, "Read-only file system", str(folder))

    monkeypatch.setattr("whaat.cli.main._probe", lambda settings: None)
    monkeypatch.setattr("whaat.cli.main.make_state_dir", no_write)

    with pytest.raises(typer.Exit):
        cli._start_unless_running(dev)

    err = capsys.readouterr().err
    assert "sandbox" in err and f"{dev.host}:{dev.port}" in err and str(dev.state_dir) in err


@pytest.mark.parametrize(
    ("args", "query"),
    [(["--reason", "moved to acme/web"], "?reason=moved+to+acme%2Fweb"), (["--reason", ""], "?reason="), ([], "")],
)
def test_a_delete_sends_its_reason_to_whaat(monkeypatch: pytest.MonkeyPatch, args: list[str], query: str) -> None:
    sent: list[str] = []

    class Answer:
        def __enter__(self) -> "Answer":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def urlopen(request: object, timeout: float) -> Answer:
        sent.append(request.full_url)  # type: ignore[attr-defined]
        return Answer()

    monkeypatch.setattr(cli, "_identity_token", lambda settings: "t")
    monkeypatch.setattr(cli, "_ensure_running", lambda settings: "running")
    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)

    result = CliRunner().invoke(cli.app, ["memory", "delete", "acme/shop/feedback_x.md", *args])

    assert result.exit_code == 0
    assert sent[0].endswith("/api/v1/memory/memories/acme/shop/feedback_x.md" + query)
