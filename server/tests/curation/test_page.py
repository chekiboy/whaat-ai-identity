import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CLAUDE_TOKEN, TOKEN, write
from whaat.config import Settings
from whaat.main import create_app

ADMIN = {"Authorization": f"Bearer {TOKEN}"}
CLAUDE = {"Authorization": f"Bearer {CLAUDE_TOKEN}"}


def memory(folder: Path, rel: str, body: str) -> None:
    stem = Path(rel).stem
    write(folder / "memory" / rel, f"---\nname: {stem}\ndescription: d\ntype: feedback\n---\n{body}")


@pytest.fixture
def app(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, TOKEN))


def report(client: TestClient, rows: list[dict[str, object]]) -> str:
    body = {"report": {"lint_summary": "x", "rows": rows, "unchecked": "nothing"}}
    response = client.post("/api/v1/journal/curation-reports", json=body, headers=CLAUDE)
    assert response.status_code == 201, response.text
    report_id: str = response.json()["report_id"]
    return report_id


def row(n: int, file: str, action: str, target: str | None = None, applied: str | None = None) -> dict[str, object]:
    return {
        "n": n,
        "file": file,
        "actions": [action],
        "target": target,
        "reason": "r",
        "evidence": "e",
        "applied": applied,
    }


def waiting_session(client: TestClient) -> None:
    """The curation session's `whaat wait curation` asks once, so the page hands its clicks over."""
    assert client.post("/api/v1/handoff/next", json={"kind": "curation"}, headers=CLAUDE).json()["call"] is None


def test_the_view_counts_the_map_as_the_live_page_and_draws_each_row(app: TestClient, settings: Settings) -> None:
    home = settings.identities["claude"]
    memory(home, "feedback_old.md", "x" * 1300)
    memory(home, "feedback_kept.md", "y")
    write(home / "memory/MEMORY.md", "- feedback_old.md — when old\n- feedback_kept.md — when kept\n")
    memory(home, "acme/feedback_far.md", "z")
    memory(home, "personal/feedback_mine.md", "p")
    report_id = report(
        app,
        [
            row(1, "`feedback_old.md`", "delete"),
            row(2, "`feedback_kept.md`", "retrigger", 'new line "when it matters"'),
            row(3, "`acme/feedback_far.md`", "move", "to the global level"),
            row(4, "`feedback_old.md`", "trim"),
        ],
    )

    view = app.get("/api/v1/curation/view", params={"report_id": report_id}, headers=ADMIN).json()

    dirs = {d["dir"]: (d["before"], d["after_lo"], d["after_hi"]) for d in view["map"]["dirs"]}
    assert dirs == {"": (2, 2, 2), "acme": (1, 0, 0)}
    assert (view["map"]["total_before"], view["map"]["total_hi"]) == (3, 2)
    figures = {f["n"]: f for f in view["rows"]}
    assert figures[2]["now"] == "when kept" and figures[2]["after"] == "when it matters"
    assert (figures[3]["from_dir"], figures[3]["dest"]) == ("acme", "")
    assert (figures[4]["size"], figures[4]["budget"]) == (1300, 1200)
    assert not any("personal" in c["file"] for d in view["map"]["dirs"] for c in d["cells"])


def test_a_sent_row_is_stamped_refused_again_and_open_again_after_a_revert(app: TestClient, settings: Settings) -> None:
    memory(settings.identities["claude"], "feedback_a.md", "a")
    memory(settings.identities["claude"], "feedback_b.md", "b")
    report_id = report(
        app, [row(1, "feedback_a.md", "verify"), row(2, "feedback_b.md", "fix", "the fix", applied="store abc")]
    )
    waiting_session(app)
    send = {"report_id": report_id, "rows": [{"n": 1, "decision": "apply"}]}

    first = app.post("/api/v1/curation/decisions", json=send, headers=ADMIN).json()
    again = app.post("/api/v1/curation/decisions", json=send, headers=ADMIN)
    refused = app.post("/api/v1/curation/revert", json={"report_id": report_id, "n": 1}, headers=ADMIN)
    reverted = app.post("/api/v1/curation/revert", json={"report_id": report_id, "n": 2}, headers=ADMIN).json()

    stored = json.loads(next((settings.identities["claude"] / "memory-curation").rglob("*.json")).read_text())
    assert first["handed"] and first["at"]
    assert stored["body"]["rows"][0]["sent_at"] == first["at"]
    assert (again.status_code, again.json()["detail"]) == (409, "already sent: rows 1")
    assert (refused.status_code, refused.json()["detail"]) == (400, "rows must be applied rows of this report")
    assert reverted["handed"]
    assert reverted["command"].endswith(f"report={report_id} rows=2 confirmed=report-page")
