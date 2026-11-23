import json

from fastapi.testclient import TestClient

from tests.conftest import CLAUDE_TOKEN, TOKEN
from whaat.config import Settings
from whaat.main import create_app

ADMIN = {"Authorization": f"Bearer {TOKEN}"}
URL = "/api/v1/preferences"


def test_the_preferences_start_with_english_and_no_identity_chosen(client: TestClient) -> None:
    prefs = client.get(URL, headers=ADMIN).json()
    assert prefs == {"language": "en", "identity": {"open_with": "last", "last": None, "agents": {}}}


def test_a_change_is_kept_in_one_file_and_the_terminal_s_old_settings_are_dropped(
    client: TestClient, settings: Settings
) -> None:
    path = settings.state_dir / "preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"terminal": {"command": "codex", "projects": []}}), encoding="utf-8")

    changed = client.patch(URL, json={"language": "hu"}, headers=ADMIN).json()

    assert changed["language"] == "hu"
    assert json.loads(path.read_text()) == {"language": "hu"}
    assert TestClient(create_app(settings, TOKEN)).get(URL, headers=ADMIN).json()["language"] == "hu"


def test_the_identity_the_app_opens_with_and_the_one_chosen_last_are_kept_apart(
    client: TestClient, settings: Settings
) -> None:
    client.patch(URL, json={"identity": {"last": "trial"}}, headers=ADMIN)
    fixed = client.patch(URL, json={"identity": {"open_with": "claude"}}, headers=ADMIN).json()
    assert fixed["identity"] == {"open_with": "claude", "last": "trial", "agents": {}}
    saved = json.loads((settings.state_dir / "preferences.json").read_text())["identity"]
    assert (saved["open_with"], saved["last"]) == ("claude", "trial")
    back = client.patch(URL, json={"identity": {"open_with": "last"}, "language": "hu"}, headers=ADMIN).json()
    assert back["identity"] == {"open_with": "last", "last": "trial", "agents": {}}
    for bad in ({"open_with": "Claude!"}, {"last": "last x"}):
        assert client.patch(URL, json={"identity": bad}, headers=ADMIN).status_code == 422


def test_only_the_admin_reads_or_changes_the_preferences_and_unknown_values_are_refused(client: TestClient) -> None:
    agent = {"Authorization": f"Bearer {CLAUDE_TOKEN}"}
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=agent).status_code == 403
    assert client.patch(URL, json={"language": "hu"}, headers=agent).status_code == 403
    assert client.patch(URL, json={"language": "de"}, headers=ADMIN).status_code == 422


def test_an_identitys_agent_config_is_kept_taken_off_and_must_be_a_folder(
    client: TestClient, settings: Settings, tmp_path
) -> None:
    folder = tmp_path / "agent-config"
    folder.mkdir()
    kept = client.patch(URL, json={"identity": {"agents": {"wHaat": str(folder)}}}, headers=ADMIN).json()
    assert kept["identity"]["agents"] == {"wHaat": str(folder)}
    missing = client.patch(URL, json={"identity": {"agents": {"wHaat": str(tmp_path / "nope")}}}, headers=ADMIN)
    assert missing.status_code == 422
    off = client.patch(URL, json={"identity": {"agents": {"wHaat": ""}}}, headers=ADMIN).json()
    assert off["identity"]["agents"] == {}
