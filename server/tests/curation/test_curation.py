import json
import shlex
import stat
from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import whaat.cli.main as cli
from tests.conftest import CLAUDE_TOKEN, TOKEN, write
from whaat.agent import CONNECTOR, Launch
from whaat.config import Settings
from whaat.handoff.command import start_line
from whaat.handoff.store import CALL_SECONDS, WAIT_SECONDS, HandoffStore
from whaat.main import create_app

ADMIN = {"Authorization": f"Bearer {TOKEN}"}
CLAUDE = {"Authorization": f"Bearer {CLAUDE_TOKEN}"}
ROW = {"n": 1, "file": "feedback_x.md", "actions": ["verify"], "target": None, "reason": "old", "evidence": None}
REPORT = {"lint_summary": "0 problems", "rows": [ROW, {**ROW, "n": 2}], "unchecked": "nothing"}
LAUNCH = Launch(command="claude --plugin-dir /c/claude_code", env={"CLAUDE_CONFIG_DIR": "/cfg/claude"})
DONE = "/whaat:session-end steps=none confirmed=report-page"


@pytest.fixture(autouse=True)
def the_memory_the_rows_name(settings: Settings) -> None:
    write(
        settings.identities["claude"] / "memory/feedback_x.md",
        "---\nname: feedback_x\ndescription: d\ntype: feedback\n---\nB.\n",
    )


@pytest.fixture
def app(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, TOKEN))


def saved_report(client: TestClient, report: Mapping[str, object] = REPORT) -> str:
    response = client.post("/api/v1/journal/curation-reports", json={"report": report}, headers=CLAUDE)
    assert response.status_code == 201, response.text
    report_id: str = response.json()["report_id"]
    return report_id


def next_call(client: TestClient, report_id: str) -> str | None:
    """What the session's `whaat wait curation --report` asks with the identity's token; an empty ask marks it
    waiting."""
    response = client.post("/api/v1/handoff/next", json={"kind": "curation", "work": report_id}, headers=CLAUDE)
    assert response.status_code == 200, response.text
    call: str | None = response.json()["call"]
    return call


def test_the_start_line_runs_the_report_with_the_identity_s_agent_config(app: TestClient) -> None:
    app.app.state.launch = lambda persona: LAUNCH  # type: ignore[attr-defined]

    started = app.post("/api/v1/curation/start", json={"identity": "claude", "cwd": "/w x"}, headers=ADMIN).json()
    next_call(app, "private-claude:memory-curation/any.json")
    again = app.post("/api/v1/curation/start", json={"identity": "claude"}, headers=ADMIN).json()

    assert started == {
        "command": "cd '/w x' && CLAUDE_CONFIG_DIR=/cfg/claude claude --plugin-dir /c/claude_code"
        " '/whaat:memory-curation report'",
        "waiting": False,
    }
    assert again["waiting"] is True


def test_the_powershell_line_quotes_its_values_and_sets_the_config_first() -> None:
    launch = Launch(command="claude --plugin-dir 'C:\\w hat\\cc'", env={"CLAUDE_CONFIG_DIR": "C:\\o'neil\\cfg"})

    line = start_line(launch, "/whaat:memory-curation report", Path("C:/p x"), powershell=True)

    assert line == (
        "Set-Location 'C:/p x'; $env:CLAUDE_CONFIG_DIR='C:\\o''neil\\cfg'; "
        "claude --plugin-dir 'C:\\w hat\\cc' '/whaat:memory-curation report'"
    )


def test_the_decisions_are_saved_and_handed_once_to_the_session_waiting_for_that_report(
    app: TestClient, settings: Settings
) -> None:
    report_id = saved_report(app)
    assert next_call(app, report_id) is None

    sent = app.post(
        "/api/v1/curation/decisions",
        json={"report_id": report_id, "rows": [{"n": 1, "decision": "apply", "note": "only the path"}]},
        headers=ADMIN,
    ).json()

    call = f"/whaat:memory-curation apply-rows report={report_id} confirmed=report-page"
    stored = json.loads(next((settings.identities["claude"] / "memory-curation").rglob("*.json")).read_text())
    assert (sent["handed"], sent["command"], sent["detail"]) == (True, call, None)
    assert next_call(app, "private-claude:memory-curation/another.json") is None
    assert (next_call(app, report_id), next_call(app, report_id)) == (call, None)
    assert [(r["decision"], r["note"]) for r in stored["body"]["rows"]] == [("apply", "only the path"), (None, None)]
    assert stored["body"]["rows"][0]["sent_at"] == sent["at"]


def test_without_a_waiting_session_the_decisions_are_saved_and_the_call_is_handed_back(app: TestClient) -> None:
    report_id = saved_report(app)
    next_call(app, "private-claude:memory-curation/another.json")
    body = {"report_id": report_id, "rows": [{"n": 2, "decision": "apply"}]}

    sent = app.post("/api/v1/curation/decisions", json=body, headers=ADMIN).json()

    assert (sent["handed"], sent["detail"]) == (False, "no curation session waits for this report")
    assert sent["command"].endswith(f"report={report_id} confirmed=report-page")
    assert next_call(app, report_id) is None


def test_right_after_a_wait_took_a_call_the_next_click_is_shown_to_paste(app: TestClient) -> None:
    report_id = saved_report(app)
    next_call(app, report_id)
    app.post("/api/v1/curation/done", json={"report_id": report_id}, headers=ADMIN)
    assert next_call(app, report_id) == DONE

    late = app.post(
        "/api/v1/curation/decisions",
        json={"report_id": report_id, "rows": [{"n": 1, "decision": "apply"}]},
        headers=ADMIN,
    ).json()

    assert (late["handed"], late["at"]) == (False, None)


def test_revert_and_done_reach_the_waiting_session_in_the_order_sent(app: TestClient) -> None:
    report_id = saved_report(app, {**REPORT, "rows": [ROW, {**ROW, "n": 2, "applied": "store abc"}]})
    next_call(app, report_id)

    reverted = app.post("/api/v1/curation/revert", json={"report_id": report_id, "n": 2}, headers=ADMIN).json()
    done = app.post("/api/v1/curation/done", json={"report_id": report_id}, headers=ADMIN).json()

    assert reverted["handed"] and done["handed"]
    assert next_call(app, report_id) == (
        f"/whaat:memory-curation revert-applied-rows report={report_id} rows=2 confirmed=report-page"
    )
    assert next_call(app, report_id) == DONE


def test_a_handed_call_waits_on_disk_through_a_server_restart(app: TestClient, settings: Settings) -> None:
    report_id = saved_report(app)
    next_call(app, report_id)
    app.post("/api/v1/curation/done", json={"report_id": report_id}, headers=ADMIN)

    restarted = TestClient(create_app(settings, TOKEN))

    assert next_call(restarted, report_id) == DONE


def test_a_session_waits_only_shortly_after_an_empty_ask_and_an_old_call_is_dropped(tmp_path: Path) -> None:
    now = [1000.0]
    store = HandoffStore(tmp_path, clock=lambda: now[0])
    store.take("claude", "curation", "r1")

    waiting = (store.waiting("claude", "curation", "r1"), store.waiting("claude", "curation", "r2"))
    handed = store.hand("claude", "curation", "r1", "call")
    now[0] += WAIT_SECONDS + 1
    late = store.hand("claude", "curation", "r1", "late")
    now[0] += CALL_SECONDS
    stale = store.take("claude", "curation", "r1")

    assert (waiting, handed, late, stale) == ((True, False), True, False, None)
    assert store.waiting("claude", "migration") is False


def test_only_the_identity_s_own_token_takes_its_calls(app: TestClient) -> None:
    body = {"kind": "curation", "work": "r1"}
    assert app.post("/api/v1/handoff/next", json=body, headers=ADMIN).status_code == 403
    assert app.post("/api/v1/handoff/next", json={**body, "kind": "nope"}, headers=CLAUDE).status_code == 422
    assert app.post("/api/v1/handoff/next", json={"kind": "curation"}, headers=CLAUDE).status_code == 422


def test_the_wait_asks_for_its_report_until_a_call_comes_then_prints_it(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([{"call": None}, {"call": DONE}])
    asked: list[object] = []

    def post(_settings: object, path: str, body: object, _token: str) -> object:
        asked.append((path, body))
        return next(answers)

    monkeypatch.setenv("WHAAT_TOKEN", CLAUDE_TOKEN)
    monkeypatch.setattr(cli, "_post_json", post)
    monkeypatch.setattr("whaat.cli.main.time.sleep", lambda _: None)

    result = CliRunner().invoke(cli.app, ["wait", "curation", "--report", "private-claude:r.json"])
    missing = CliRunner().invoke(cli.app, ["wait", "migration", "--report", "private-claude:r.json"])
    slow = CliRunner().invoke(cli.app, ["wait", "curation", "--report", "r", "--every", str(WAIT_SECONDS)])

    assert (result.exit_code, result.stdout.splitlines()[-1]) == (0, DONE)
    assert asked == [("/api/v1/handoff/next", {"kind": "curation", "work": "private-claude:r.json"})] * 2
    assert missing.exit_code == 2 and slow.exit_code == 2


def test_decisions_are_refused_for_an_unknown_row_or_report_and_for_an_identity(app: TestClient) -> None:
    report_id = saved_report(app)
    row = [{"n": 9, "decision": "apply"}]
    assert (
        app.post("/api/v1/curation/decisions", json={"report_id": report_id, "rows": row}, headers=ADMIN).status_code
        == 422
    )
    missing = {"report_id": "private-claude:memory-curation/x.json", "rows": []}
    assert app.post("/api/v1/curation/decisions", json=missing, headers=ADMIN).status_code == 404
    assert (
        app.post("/api/v1/curation/decisions", json={"report_id": report_id, "rows": []}, headers=CLAUDE).status_code
        == 403
    )


def test_an_identity_without_an_agent_config_cannot_start_a_curation(app: TestClient) -> None:
    response = app.post("/api/v1/curation/start", json={"identity": "claude"}, headers=ADMIN)
    assert response.status_code == 409


def test_discarding_only_saves_and_hands_nothing_and_the_next_run_sees_it(app: TestClient) -> None:
    report_id = saved_report(app)
    next_call(app, report_id)
    body = {"report_id": report_id, "rows": [{"n": 2, "decision": "reject", "note": "not now"}]}

    sent = app.post("/api/v1/curation/decisions", json=body, headers=ADMIN).json()
    discarded = app.get("/api/v1/curation/discarded", headers=CLAUDE).json()

    assert (sent["handed"], sent["detail"]) == (False, "only discarded rows: nothing to apply, the decisions are saved")
    assert next_call(app, report_id) is None
    assert [(d["file"], d["actions"], d["note"], d["report_id"]) for d in discarded] == [
        ("feedback_x.md", ["verify"], "not now", report_id)
    ]
    assert discarded[0]["changed_since"] is False


def test_a_rejected_row_of_a_report_saved_before_the_actions_list_is_still_discarded(
    app: TestClient, settings: Settings
) -> None:
    saved_report(app)
    path = next((settings.identities["claude"] / "memory-curation").rglob("*_memory-curation.json"))
    document = json.loads(path.read_text(encoding="utf-8"))
    old = {k: v for k, v in document["body"]["rows"][0].items() if k != "actions"}
    document["body"]["rows"] = [old | {"action": "verify", "decision": "reject"}]
    path.write_text(json.dumps(document), encoding="utf-8")

    discarded = app.get("/api/v1/curation/discarded", headers=CLAUDE).json()

    assert [(d["file"], d["actions"]) for d in discarded] == [("feedback_x.md", ["verify"])]


def test_the_real_start_line_runs_claude_with_the_plugin_and_keeps_the_token_in_the_config(
    app: TestClient, tmp_path: Path
) -> None:
    token = app.post("/api/v1/identities", json={"id": "agent"}, headers=ADMIN).json()["token"]
    config = tmp_path / "agent config"
    config.mkdir()
    (config / "settings.json").write_text(json.dumps({"model": "opus", "env": {"OTHER": "1"}}), encoding="utf-8")
    app.patch("/api/v1/preferences", json={"identity": {"agents": {"agent": str(config)}}}, headers=ADMIN)

    started = app.post("/api/v1/curation/start", json={"identity": "agent"}, headers=ADMIN).json()

    settings_file = config / "settings.json"
    written = json.loads(settings_file.read_text(encoding="utf-8"))
    assert started["command"] == (
        f"CLAUDE_CONFIG_DIR={shlex.quote(str(config))} claude --plugin-dir {shlex.quote(str(CONNECTOR))}"
        " '/whaat:memory-curation report'"
    )
    assert token not in started["command"]
    assert (CONNECTOR / ".claude-plugin" / "plugin.json").is_file()
    assert (written["model"], written["env"]["OTHER"], written["env"]["WHAAT_TOKEN"]) == ("opus", "1", token)
    assert stat.S_IMODE(settings_file.stat().st_mode) == 0o600


def test_an_agent_config_without_a_kept_token_refuses_the_start_and_writes_nothing(
    app: TestClient, tmp_path: Path
) -> None:
    config = tmp_path / "agent-config"
    config.mkdir()
    app.patch("/api/v1/preferences", json={"identity": {"agents": {"claude": str(config)}}}, headers=ADMIN)

    refused = app.post("/api/v1/curation/start", json={"identity": "claude"}, headers=ADMIN)

    assert refused.status_code == 409 and "new token" in refused.json()["detail"]
    assert not (config / "settings.json").exists()
