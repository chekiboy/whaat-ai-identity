import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from whaat.git import GitCommitter


def test_committers_sharing_a_folder_commit_every_file_when_they_run_at_once(tmp_path: Path) -> None:
    folder = tmp_path / "identity"
    folder.mkdir()
    GitCommitter().init(folder)
    for git_config in (["user.name", "probe"], ["user.email", "probe@example.invalid"]):
        subprocess.run(["git", "-C", str(folder), "config", *git_config], check=True)
    committers = [GitCommitter(), GitCommitter()]  # the memory and the journal each hold their own

    def save(i: int) -> str:
        path = folder / f"note_{i:02d}.md"
        path.write_text(f"note {i}\n")
        return committers[i % 2].commit(folder, [path], f"note {i}")

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(save, range(40)))

    log = subprocess.run(["git", "-C", str(folder), "rev-list", "--count", "HEAD"], capture_output=True, text=True)
    status = subprocess.run(["git", "-C", str(folder), "status", "--porcelain"], capture_output=True, text=True)
    assert (log.stdout.strip(), status.stdout) == ("40", "")


@pytest.fixture
def no_git_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder whose git has no user and may not guess one, as on a fresh machine or in a container."""
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tuseConfigOnly = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(name, raising=False)
    folder = tmp_path / "identity"
    (folder / "memory").mkdir(parents=True)
    GitCommitter().init(folder)
    return folder


def author(folder: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(folder), "log", "-1", "--format=%an <%ae>"], capture_output=True, text=True
    ).stdout.strip()


def commit_a_note(folder: Path) -> None:
    note = folder / "memory/note.md"
    note.write_text("note\n")
    GitCommitter().commit(folder, [note], "note")


def test_a_commit_without_a_git_user_is_authored_by_whaat(no_git_user: Path) -> None:
    folder = no_git_user
    committer = GitCommitter()
    note = folder / "memory/note.md"
    note.write_text("note\n")

    committer.commit(folder, [note], "note")
    moved = committer.move(folder, [(note, folder / "memory/moved.md")], "move")
    reverted = committer.revert(folder, [moved], "memory")

    assert (author(folder), len(reverted)) == ("whaat <whaat@localhost>", 1)


def test_a_configured_git_user_is_kept(no_git_user: Path) -> None:
    subprocess.run(["git", "-C", str(no_git_user), "config", "user.name", "Ada"], check=True)
    subprocess.run(["git", "-C", str(no_git_user), "config", "user.email", "ada@example.invalid"], check=True)

    commit_a_note(no_git_user)

    assert author(no_git_user) == "Ada <ada@example.invalid>"


def test_only_the_missing_part_of_a_git_user_is_filled_in(no_git_user: Path) -> None:
    subprocess.run(["git", "-C", str(no_git_user), "config", "user.name", "Ada"], check=True)

    commit_a_note(no_git_user)

    assert author(no_git_user) == "Ada <whaat@localhost>"


def test_an_author_git_can_work_out_itself_is_kept(
    no_git_user: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "gitconfig").write_text("")
    subprocess.run(["git", "-C", str(no_git_user), "config", "user.name", "Ada"], check=True)
    monkeypatch.setenv("EMAIL", "ada@env.invalid")

    commit_a_note(no_git_user)

    assert author(no_git_user) == "Ada <ada@env.invalid>"


def test_a_committer_from_the_environment_does_not_hide_a_missing_author(
    no_git_user: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Ci")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "ci@example.invalid")

    commit_a_note(no_git_user)

    assert author(no_git_user) == "whaat <whaat@localhost>"
