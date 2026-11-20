import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CLAUDE_TOKEN, TOKEN, write
from whaat.config import Settings
from whaat.handoff.store import LISTEN_SECONDS, HandoffStore
from whaat.main import create_app
from whaat.terminal.agent import Launch

ADMIN = {"Authorization": f"Bearer {TOKEN}"}
CLAUDE = {"Authorization": f"Bearer {CLAUDE_TOKEN}"}
ROW = {"n": 1, "file": "feedback_x.md", "actions": ["verify"], "target": None, "reason": "old", "evidence": None}
REPORT = {"lint_summary": "0 problems", "rows": [ROW, {**ROW, "n": 2}], "unchecked": "nothing"}


@pytest.fixture(autouse=True)
def the_memory_the_rows_name(settings: Settings) -> None:
    write(
        settings.identities["claude"] / "memory/feedback_x.md",
        "---\nname: feedback_x\ndescription: d\ntype: feedback\n---\nB.\n",
    )


@pytest.fixture
def app(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, TOKEN))


def saved_report(client: TestClient) -> str:
    response = client.post("/api/v1/journal/curation-reports", json={"report": REPORT}, headers=CLAUDE)
    assert response.status_code == 201, response.text
    report_id: str = response.json()["report_id"]
    return report_id


def next_call(client: TestClient) -> str | None:
    """What the session's `whaat wait curation` asks with the identity's token; asking also marks it as waiting."""
    response = client.post("/api/v1/handoff/next", json={"kind": "curation"}, headers=CLAUDE)
    assert response.status_code == 200, response.text
    call: str | None = response.json()["call"]
    return call


def test_the_start_line_runs_the_report_with_the_identity_s_agent_config(app: TestClient) -> None:
    app.app.state.launch = lambda persona: Launch(  # type: ignore[attr-defined]
        command="claude --plugin-dir /c/claude_code", env={"CLAUDE_CONFIG_DIR": "/cfg/claude"}
    )

    started = app.post("/api/v1/curation/start", json={"identity": "claude", "cwd": "/w x"}, headers=ADMIN).json()

    assert started == {
        "command": "cd '/w x' && CLAUDE_CONFIG_DIR=/cfg/claude claude --plugin-dir /c/claude_code"
        " '/whaat:memory-curation report'",
        "waiting": False,
    }


def test_the_decisions_are_saved_and_handed_once_to_the_waiting_session(app: TestClient, settings: Settings) -> None:
    report_id = saved_report(app)
    assert next_call(app) is None

    sent = app.post(
        "/api/v1/curation/decisions",
        json={"report_id": report_id, "rows": [{"n": 1, "decision": "apply", "note": "only the path"}]},
        headers=ADMIN,
    ).json()

    call = f"/whaat:memory-curation apply-rows report={report_id} confirmed=report-page"
    stored = json.loads(next((settings.identities["claude"] / "memory-curation").rglob("*.json")).read_text())
    assert (sent["handed"], sent["command"], sent["detail"]) == (True, call, None)
    assert (next_call(app), next_call(app)) == (call, None)
    assert [(r["decision"], r["note"]) for r in stored["body"]["rows"]] == [("apply", "only the path"), (None, None)]
    assert stored["body"]["rows"][0]["sent_at"] == sent["at"]


def test_without_a_waiting_session_the_decisions_are_saved_and_the_call_is_handed_back(app: TestClient) -> None:
    report_id = saved_report(app)
    body = {"report_id": report_id, "rows": [{"n": 2, "decision": "apply"}]}

    sent = app.post("/api/v1/curation/decisions", json=body, headers=ADMIN).json()

    assert (sent["handed"], sent["detail"]) == (False, "no curation session of this identity waits for the page")
    assert sent["command"].endswith(f"report={report_id} confirmed=report-page")
    assert next_call(app) is None


def test_revert_and_done_reach_the_waiting_session_in_the_order_sent(app: TestClient) -> None:
    applied = {**ROW, "n": 2, "applied": "store abc"}
    response = app.post(
        "/api/v1/journal/curation-reports", json={"report": {**REPORT, "rows": [ROW, applied]}}, headers=CLAUDE
    )
    report_id = response.json()["report_id"]
    next_call(app)

    reverted = app.post("/api/v1/curation/revert", json={"report_id": report_id, "n": 2}, headers=ADMIN).json()
    done = app.post("/api/v1/curation/done", json={"identity": "claude"}, headers=ADMIN).json()

    assert reverted["handed"] and done["handed"]
    assert (
        next_call(app) == f"/whaat:memory-curation revert-applied-rows report={report_id} rows=2 confirmed=report-page"
    )
    assert next_call(app) == "/whaat:session-end steps=none confirmed=report-page"


def test_a_handed_call_waits_on_disk_through_a_server_restart(app: TestClient, settings: Settings) -> None:
    next_call(app)
    app.post("/api/v1/curation/done", json={"identity": "claude"}, headers=ADMIN)

    restarted = TestClient(create_app(settings, TOKEN))

    assert next_call(restarted) == "/whaat:session-end steps=none confirmed=report-page"


def test_a_session_counts_as_waiting_only_shortly_after_its_last_ask(tmp_path: Path) -> None:
    now = [1000.0]
    store = HandoffStore(tmp_path, clock=lambda: now[0])
    store.take("claude", "curation")

    waiting = store.listening("claude", "curation")
    now[0] += LISTEN_SECONDS + 1

    assert (waiting, store.listening("claude", "curation"), store.listening("claude", "migration")) == (
        True,
        False,
        False,
    )


def test_only_the_identity_s_own_token_takes_its_calls(app: TestClient) -> None:
    assert app.post("/api/v1/handoff/next", json={"kind": "curation"}, headers=ADMIN).status_code == 403
    assert app.post("/api/v1/handoff/next", json={"kind": "nope"}, headers=CLAUDE).status_code == 422


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
    next_call(app)
    body = {"report_id": report_id, "rows": [{"n": 2, "decision": "reject", "note": "not now"}]}

    sent = app.post("/api/v1/curation/decisions", json=body, headers=ADMIN).json()
    discarded = app.get("/api/v1/curation/discarded", headers=CLAUDE).json()

    assert (sent["handed"], sent["detail"]) == (False, "only discarded rows: nothing to apply, the decisions are saved")
    assert next_call(app) is None
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
